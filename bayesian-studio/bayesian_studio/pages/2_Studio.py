"""Bayesian Studio — per-sensor tuning page (Phase 1 tracer bullet)."""
import os
import re
from datetime import datetime, timedelta, timezone

import plotly.graph_objects as go
import streamlit as st

from bayesian_studio.engine.bayes import (
    _extract_template_entity_ids,
    compute_probability_trace,
)
from bayesian_studio.engine.config_loader import (
    get_bayesian_entity_ids,
    load_bayesian_config,
    load_location,
)
from bayesian_studio.engine.database import get_engine, get_read_connection
from bayesian_studio.engine.state_db import load_state_timelines

st.set_page_config(page_title="Bayesian Studio", layout="wide")

# ---------------------------------------------------------------------------
# Config dir — add-on mounts /config; fall back to HASS_CONFIG for local dev
# ---------------------------------------------------------------------------

CONFIG_DIR = os.environ.get("HASS_CONFIG", "/config")

# ---------------------------------------------------------------------------
# Cached data loaders
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner="Connecting to recorder database…")
def _get_engine():
    return get_engine(CONFIG_DIR)


@st.cache_data(show_spinner="Loading sensor list…", ttl=120)
def _get_sensor_ids():
    return get_bayesian_entity_ids("binary_sensor.*", CONFIG_DIR)


@st.cache_data(show_spinner="Loading sensor config…", ttl=120)
def _get_config(entity_id: str):
    return load_bayesian_config(entity_id, CONFIG_DIR)


@st.cache_data(show_spinner="Loading state timelines from database…", ttl=300)
def _get_timelines(entity_ids: tuple, start_ts: float, end_ts: float, load_attrs: bool):
    engine = _get_engine()
    with get_read_connection(engine) as conn:
        return load_state_timelines(list(entity_ids), start_ts, end_ts, load_attrs, conn)


@st.cache_data(ttl=120)
def _get_location():
    return load_location(CONFIG_DIR)

# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------

st.title("🎛️ Bayesian Studio")

# --- Sensor selector ---
sensor_ids = _get_sensor_ids()
if not sensor_ids:
    st.error(f"No Bayesian sensors found in {CONFIG_DIR}. Check your HA config.")
    st.stop()

default_idx = 0
nav_sensor = st.session_state.pop("_nav_sensor", None)
preselect = nav_sensor or st.query_params.get("sensor")
if preselect and preselect in sensor_ids:
    default_idx = sensor_ids.index(preselect)

selected = st.selectbox("Sensor", sensor_ids, index=default_idx)
st.query_params["sensor"] = selected

# --- Date range picker ---
col_start, col_end = st.columns(2)
with col_start:
    start_date = st.date_input(
        "From",
        value=(datetime.now(timezone.utc) - timedelta(days=7)).date(),
    )
with col_end:
    end_date = st.date_input("To", value=datetime.now(timezone.utc).date())

start_ts = datetime(
    start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc
).timestamp()
end_ts = datetime(
    end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc
).timestamp()

if start_ts >= end_ts:
    st.error("Start date must be before end date.")
    st.stop()

# --- Load config ---
try:
    raw_config, source = _get_config(selected)
except ValueError as e:
    st.error(str(e))
    st.stop()

observations_orig = raw_config.get("observations", [])
prior_orig = float(raw_config.get("prior", 0.5))
threshold_orig = float(raw_config.get("probability_threshold", 0.5))

# Working config in session state (reset when sensor changes)
state_key = f"working_config_{selected}"
if state_key not in st.session_state:
    import copy
    st.session_state[state_key] = {
        "observations": copy.deepcopy(observations_orig),
        "prior": prior_orig,
        "threshold": threshold_orig,
    }

working = st.session_state[state_key]

# --- Sliders ---
st.subheader("Sensor parameters")
col_prior, col_thresh = st.columns(2)
with col_prior:
    working["prior"] = st.slider(
        "Prior", 0.01, 0.99, float(working["prior"]), 0.01, key=f"prior_{selected}"
    )
with col_thresh:
    working["threshold"] = st.slider(
        "Threshold", 0.01, 0.99, float(working["threshold"]), 0.01, key=f"thresh_{selected}"
    )

st.subheader("Observations")
for i, obs in enumerate(working["observations"]):
    platform = obs.get("platform", "?")
    eid = obs.get("entity_id", obs.get("value_template", "")[:40])
    label = f"`{platform}` · {eid}"
    with st.expander(label, expanded=False):
        col_t, col_f = st.columns(2)
        with col_t:
            obs["prob_given_true"] = st.slider(
                "prob_given_true",
                0.001, 0.999,
                float(obs.get("prob_given_true", 0.5)),
                0.001,
                key=f"pgt_{selected}_{i}",
            )
        with col_f:
            obs["prob_given_false"] = st.slider(
                "prob_given_false",
                0.001, 0.999,
                float(obs.get("prob_given_false", 0.1)),
                0.001,
                key=f"pgf_{selected}_{i}",
            )

# Reset button
if st.button("Reset to original"):
    import copy
    st.session_state[state_key] = {
        "observations": copy.deepcopy(observations_orig),
        "prior": prior_orig,
        "threshold": threshold_orig,
    }
    st.rerun()

# --- Chart placeholder (renders immediately; replaced once trace is ready) ---
_CHART_HEIGHT = 420
chart_slot = st.empty()
stats_slot = st.empty()
with chart_slot.container():
    st.markdown(
        f'<div style="height:{_CHART_HEIGHT}px;display:flex;align-items:center;'
        f'justify-content:center;color:#888;">⏳ Computing probability trace…</div>',
        unsafe_allow_html=True,
    )

# --- Load timelines (cached) ---
obs_entity_ids = [
    obs["entity_id"]
    for obs in working["observations"]
    if "entity_id" in obs
]
template_entity_ids = _extract_template_entity_ids(working["observations"])
all_entity_ids = list(set(obs_entity_ids + template_entity_ids))
load_attrs = any(
    "state_attr(" in obs.get("value_template", "")
    for obs in working["observations"]
)
timelines = _get_timelines(tuple(sorted(all_entity_ids)), start_ts, end_ts, load_attrs)

# --- Compute trace ---
lat, lon = _get_location()
trace = compute_probability_trace(
    working["observations"],
    working["prior"],
    working["threshold"],
    timelines,
    start_ts,
    end_ts,
    lat,
    lon,
)

rows = trace["rows"]
if not rows:
    chart_slot.warning("No events found in this time window.")
    st.stop()

ts_vals = [r["ts"] for r in rows]
prob_vals = [r["probability"] for r in rows]
state_vals = [r["state"] for r in rows]
dt_vals = [datetime.fromtimestamp(ts, tz=timezone.utc) for ts in ts_vals]
end_dt = datetime.fromtimestamp(end_ts, tz=timezone.utc)

# --- Build chart ---
fig = go.Figure()

# ON/OFF shading — step from each event to the next; last segment extends to end_ts
prev_dt = dt_vals[0]
prev_state = state_vals[0]
for i in range(1, len(rows)):
    if state_vals[i] != prev_state:
        color = "rgba(0,200,100,0.08)" if prev_state == "on" else "rgba(200,80,80,0.06)"
        fig.add_vrect(x0=prev_dt, x1=dt_vals[i], fillcolor=color, line_width=0)
        prev_dt = dt_vals[i]
        prev_state = state_vals[i]
color = "rgba(0,200,100,0.08)" if prev_state == "on" else "rgba(200,80,80,0.06)"
fig.add_vrect(x0=prev_dt, x1=end_dt, fillcolor=color, line_width=0)

# Probability trace — step/square-wave (hv: horizontal first, then vertical)
fig.add_trace(go.Scatter(
    x=dt_vals, y=prob_vals,
    mode="lines",
    name="Probability",
    line=dict(color="#1f77b4", width=2, shape="hv"),
))

# Threshold line
fig.add_hline(
    y=working["threshold"],
    line_dash="dash",
    line_color="orange",
    annotation_text=f"Threshold {working['threshold']:.2f}",
    annotation_position="top right",
)

# Y-axis: fit to data + threshold, with padding, clamped to [0, 1]
y_all = prob_vals + [working["threshold"]]
y_lo = max(0.0, min(y_all) - 0.05)
y_hi = min(1.0, max(y_all) + 0.05)

fig.update_layout(
    title=selected,
    xaxis_title="Time",
    yaxis_title="Probability",
    yaxis=dict(range=[y_lo, y_hi]),
    height=_CHART_HEIGHT,
    margin=dict(l=40, r=20, t=50, b=40),
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
)

# Replace placeholder with chart
with chart_slot.container():
    st.plotly_chart(fig, width="stretch")

# --- Warnings ---
if trace["warnings"]:
    with st.expander(f"⚠️ {len(trace['warnings'])} warning(s)", expanded=False):
        for w in trace["warnings"]:
            st.warning(f"**{w['type']}** (obs {w.get('observation_index', '?')}): {w['detail']}")

# --- Stats (replace placeholder) ---
stats_slot.caption(
    f"Computed {len(rows)} events in {trace['computation_seconds']:.3f}s · "
    f"Source: `{source.kind}` "
    + (f"· `{os.path.relpath(source.file_path, CONFIG_DIR)}`" if source.file_path else "")
)
