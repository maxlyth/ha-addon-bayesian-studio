"""Bayesian Studio — per-sensor tuning page."""
import copy
import os
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

# ---------------------------------------------------------------------------
# Config dir
# ---------------------------------------------------------------------------

CONFIG_DIR = os.environ.get("HASS_CONFIG", "/config")

# ---------------------------------------------------------------------------
# HA history-graph colors (from frontend source: timeline-color.ts)
# ---------------------------------------------------------------------------

_ACTIVE_COLOR = "#FDD835"              # amber/yellow — HA binary_sensor on
_INACTIVE_COLOR = "#e0e0e0"            # grey — HA binary_sensor off
_UNKNOWN_COLOR = "rgba(128,128,128,0.15)"  # translucent grey — works on light and dark

_BINARY_CHART_H = 40
_NUMERIC_CHART_H = 120
_SPINNER_HTML = (
    '<div style="height:{h}px;display:flex;align-items:center;'
    'justify-content:center;font-size:12px;color:inherit;">'
    '⏳ Loading history…</div>'
)

# ---------------------------------------------------------------------------
# Shared Plotly layout — transparent backgrounds so Streamlit theme applies
# ---------------------------------------------------------------------------

_HA_CHART = dict(
    font=dict(family="Roboto, Noto, sans-serif", size=12),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    xaxis=dict(
        tickfont=dict(size=11),
        tickformat="%b %d\n%H:%M",
        dtick=43200000,  # 12h in ms
    ),
    yaxis=dict(tickfont=dict(size=11)),
    margin=dict(l=40, r=20, t=50, b=40),
)

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
# Helpers
# ---------------------------------------------------------------------------


def _observed_states(entity_id: str, timelines: dict) -> list[str]:
    """Return sorted unique non-unavailable states observed in the loaded timelines."""
    tl = timelines.get(entity_id, {})
    states = tl.get("state", []) if isinstance(tl, dict) else []
    return sorted(set(s for s in states if s not in ("unavailable", "unknown")))


def _config_changed(
    working: dict,
    orig_obs: list,
    orig_prior: float,
    orig_threshold: float,
) -> bool:
    """Return True if working config differs from the original in any Bayes-relevant field."""
    if working["prior"] != orig_prior or working["threshold"] != orig_threshold:
        return True
    if len(working["observations"]) != len(orig_obs):
        return True
    for w_obs, o_obs in zip(working["observations"], orig_obs):
        for key in ("prob_given_true", "prob_given_false", "to_state", "above", "below"):
            if w_obs.get(key) != o_obs.get(key):
                return True
    return False


def _render_condition_inputs(obs: dict, i: int, sensor_id: str, timelines: dict) -> None:
    """Render editable condition fields for an observation (mutates obs in-place)."""
    platform = obs.get("platform", "")

    if platform == "state":
        entity_id = obs.get("entity_id", "")
        observed = _observed_states(entity_id, timelines)
        current_val = obs.get("to_state", "")
        if observed:
            # Ensure current value is in the list (may come from config before history loaded)
            if current_val and current_val not in observed:
                observed = [current_val] + observed
            idx = observed.index(current_val) if current_val in observed else 0
            obs["to_state"] = st.selectbox(
                "to_state",
                options=observed,
                index=idx,
                key=f"to_state_{sensor_id}_{i}",
            )
        else:
            obs["to_state"] = st.text_input(
                "to_state",
                value=current_val,
                key=f"to_state_{sensor_id}_{i}",
            )

    elif platform == "numeric_state":
        col_a, col_b = st.columns(2)
        if "above" in obs:
            with col_a:
                obs["above"] = st.number_input(
                    "above",
                    value=float(obs["above"]) if obs["above"] is not None else 0.0,
                    key=f"above_{sensor_id}_{i}",
                )
        if "below" in obs:
            with col_b:
                obs["below"] = st.number_input(
                    "below",
                    value=float(obs["below"]) if obs["below"] is not None else 0.0,
                    key=f"below_{sensor_id}_{i}",
                )

    elif platform == "template":
        template_text = obs.get("value_template", "")
        if template_text:
            st.code(template_text, language="jinja2")


def _build_binary_chart(
    results_col: list,
    dt_vals: list,
    end_dt: datetime,
    height: int = 40,
) -> go.Figure:
    """Build an HA history-graph style activation timeline from obs_results."""
    fig = go.Figure()
    if not results_col or not dt_vals:
        return fig

    # Build segments of consecutive equal values
    segments = []
    seg_start = dt_vals[0]
    seg_val = results_col[0]
    for j in range(1, len(results_col)):
        if results_col[j] != seg_val:
            segments.append((seg_start, dt_vals[j], seg_val))
            seg_start = dt_vals[j]
            seg_val = results_col[j]
    segments.append((seg_start, end_dt, seg_val))

    total_span = (end_dt - dt_vals[0]).total_seconds()

    for x0, x1, val in segments:
        color = (
            _ACTIVE_COLOR if val is True
            else _INACTIVE_COLOR if val is False
            else _UNKNOWN_COLOR
        )
        fig.add_shape(
            type="rect", x0=x0, x1=x1, y0=0, y1=1,
            fillcolor=color, line_width=0, layer="below",
        )
        # Add state label if segment is wide enough (> 8% of total range)
        seg_span = (x1 - x0).total_seconds()
        if val is not None and total_span > 0 and seg_span / total_span > 0.08:
            label = "active" if val is True else "inactive"
            mid_x = x0 + (x1 - x0) / 2
            fig.add_annotation(
                x=mid_x, y=0.5, text=label, showarrow=False,
                font=dict(size=10),
                xanchor="center", yanchor="middle",
            )

    # Invisible scatter to anchor x-axis range
    fig.add_trace(go.Scatter(
        x=[dt_vals[0], end_dt], y=[0.5, 0.5],
        mode="lines", line=dict(width=0),
        showlegend=False, hoverinfo="skip",
    ))
    fig.update_layout(
        height=height,
        margin=dict(l=0, r=0, t=2, b=2),
        xaxis=dict(
            showticklabels=False, showgrid=False, zeroline=False,
            range=[dt_vals[0], end_dt],
        ),
        yaxis=dict(
            showticklabels=False, showgrid=False, zeroline=False,
            range=[0, 1], fixedrange=True,
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def _build_numeric_chart(
    tl: dict,
    obs: dict,
    start_ts: float,
    end_ts: float,
) -> go.Figure:
    """Build a step-line chart for a numeric_state observation with threshold lines."""
    fig = go.Figure()
    ts_list = tl.get("ts", [])
    state_list = tl.get("state", [])

    # Convert states to floats
    pts = []
    for ts, s in zip(ts_list, state_list):
        try:
            pts.append((ts, float(s)))
        except (ValueError, TypeError):
            pass

    if pts:
        x_vals = [datetime.fromtimestamp(ts, tz=timezone.utc) for ts, _ in pts]
        y_vals = [v for _, v in pts]
        # Extend to end of window
        x_vals.append(datetime.fromtimestamp(end_ts, tz=timezone.utc))
        y_vals.append(y_vals[-1])

        fig.add_trace(go.Scatter(
            x=x_vals, y=y_vals,
            mode="lines",
            name="Value",
            line=dict(color="#009ac7", width=1.5, shape="hv"),
            showlegend=False,
        ))

        y_all = list(y_vals)
        above = obs.get("above")
        below = obs.get("below")
        if above is not None:
            y_all.append(float(above))
            fig.add_hline(
                y=float(above),
                line_dash="dash", line_color="#ff9800", line_width=1,
                annotation_text=f"above {above}",
                annotation_position="top right",
                annotation_font_size=10,
            )
        if below is not None:
            y_all.append(float(below))
            fig.add_hline(
                y=float(below),
                line_dash="dash", line_color="#dc3146", line_width=1,
                annotation_text=f"below {below}",
                annotation_position="bottom right",
                annotation_font_size=10,
            )

        y_lo = min(y_all) - abs(min(y_all)) * 0.05 - 0.1
        y_hi = max(y_all) + abs(max(y_all)) * 0.05 + 0.1

        chart_layout = dict(_HA_CHART)
        chart_layout["xaxis"] = dict(
            _HA_CHART["xaxis"],
            tickformat="%b %d\n%H:%M",
            dtick=43200000,
        )
        chart_layout["yaxis"] = dict(_HA_CHART["yaxis"], range=[y_lo, y_hi])
        fig.update_layout(
            **chart_layout,
            height=120,
            margin=dict(l=40, r=40, t=4, b=0),
        )
    return fig


def _fill_obs_charts(
    slots: list,
    observations: list,
    timelines: dict,
    trace: dict,
    dt_vals: list,
    end_dt: datetime,
    start_ts: float,
    end_ts: float,
) -> None:
    """Fill observation chart placeholders after trace is computed."""
    rows = trace["rows"]
    for i, platform, obs, slot in slots:
        entity_id = obs.get("entity_id", "")

        if platform == "numeric_state" and entity_id:
            tl = timelines.get(entity_id, {})
            fig = _build_numeric_chart(tl, obs, start_ts, end_ts)
            if fig.data:
                with slot.container():
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            else:
                with slot.container():
                    st.caption("No data in selected range")
        else:
            # state / template — use obs_results
            results_col = [r["obs_results"][i] for r in rows if i < len(r["obs_results"])]
            if results_col:
                fig = _build_binary_chart(results_col, dt_vals, end_dt)
                with slot.container():
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            else:
                with slot.container():
                    st.caption("No data in selected range")


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
st.session_state["_current_sensor"] = selected

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

# --- Load timelines early so condition inputs can use them ---
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

# --- Observations ---
st.subheader("Observations")
obs_chart_slots = []

for i, obs in enumerate(working["observations"]):
    platform = obs.get("platform", "?")
    eid = obs.get("entity_id", obs.get("value_template", "")[:40])

    # Label — always visible
    st.markdown(f"**`{platform}`** · {eid}")

    # Chart placeholder — visible immediately with spinner matching final chart height
    h = _NUMERIC_CHART_H if platform == "numeric_state" else _BINARY_CHART_H
    slot = st.empty()
    with slot.container():
        st.markdown(_SPINNER_HTML.format(h=h), unsafe_allow_html=True)
    obs_chart_slots.append((i, platform, copy.copy(obs), slot))

    # Settings expander — collapsed by default
    with st.expander("Settings", expanded=False):
        _render_condition_inputs(obs, i, selected, timelines)
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

    if i < len(working["observations"]) - 1:
        st.divider()

# Reset button (enabled only when config has changed)
is_dirty = _config_changed(working, observations_orig, prior_orig, threshold_orig)
if st.button("Reset to original", disabled=not is_dirty):
    st.session_state[state_key] = {
        "observations": copy.deepcopy(observations_orig),
        "prior": prior_orig,
        "threshold": threshold_orig,
    }
    st.rerun()

# --- Chart placeholder ---
_CHART_HEIGHT = 420
chart_slot = st.empty()
stats_slot = st.empty()
with chart_slot.container():
    st.markdown(
        f'<div style="height:{_CHART_HEIGHT}px;display:flex;align-items:center;'
        f'justify-content:center;color:#5e5e5e;">⏳ Computing probability trace…</div>',
        unsafe_allow_html=True,
    )

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

# --- Build probability chart ---
fig = go.Figure()

# ON/OFF shading
prev_dt = dt_vals[0]
prev_state = state_vals[0]
for i in range(1, len(rows)):
    if state_vals[i] != prev_state:
        color = "rgba(0,154,199,0.08)" if prev_state == "on" else "rgba(220,49,70,0.06)"
        fig.add_vrect(x0=prev_dt, x1=dt_vals[i], fillcolor=color, line_width=0)
        prev_dt = dt_vals[i]
        prev_state = state_vals[i]
color = "rgba(0,154,199,0.08)" if prev_state == "on" else "rgba(220,49,70,0.06)"
fig.add_vrect(x0=prev_dt, x1=end_dt, fillcolor=color, line_width=0)

# Probability trace
fig.add_trace(go.Scatter(
    x=dt_vals, y=prob_vals,
    mode="lines",
    name="Probability",
    line=dict(color="#009ac7", width=2, shape="hv"),
))

# Threshold line
fig.add_hline(
    y=working["threshold"],
    line_dash="dash",
    line_color="#ff9800",
    annotation_text=f"Threshold {working['threshold']:.2f}",
    annotation_position="top right",
    annotation_font_size=11,
)

# Y-axis fitted to data + threshold
y_all = prob_vals + [working["threshold"]]
y_lo = max(0.0, min(y_all) - 0.05)
y_hi = min(1.0, max(y_all) + 0.05)

chart_layout = dict(_HA_CHART)
chart_layout["yaxis"] = dict(_HA_CHART["yaxis"], range=[y_lo, y_hi])
fig.update_layout(
    **chart_layout,
    title=selected,
    xaxis_title=None,
    yaxis_title="Probability",
    height=_CHART_HEIGHT,
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
)

with chart_slot.container():
    st.plotly_chart(fig, use_container_width=True)

# --- Warnings ---
if trace["warnings"]:
    with st.expander(f"⚠️ {len(trace['warnings'])} warning(s)", expanded=False):
        for w in trace["warnings"]:
            st.warning(f"**{w['type']}** (obs {w.get('observation_index', '?')}): {w['detail']}")

# --- Stats ---
stats_slot.caption(
    f"Computed {len(rows)} events in {trace['computation_seconds']:.3f}s · "
    f"Source: `{source.kind}` "
    + (f"· `{os.path.relpath(source.file_path, CONFIG_DIR)}`" if source.file_path else "")
)

# --- Fill observation history charts ---
_fill_obs_charts(obs_chart_slots, working["observations"], timelines, trace, dt_vals, end_dt, start_ts, end_ts)
