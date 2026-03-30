"""Bayesian Studio — per-sensor tuning page."""
import copy
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import plotly.graph_objects as go
import streamlit as st

from bayesian_studio.engine.bayes import (
    _extract_template_entity_ids,
    compute_probability_trace,
    extract_template_entity_ids_for_obs,
)
from bayesian_studio.engine.config_loader import (
    extract_observation_names,
    get_bayesian_entity_ids,
    load_bayesian_config,
    load_location,
    load_timezone,
    search_entity_ids,
)
from bayesian_studio.engine.config_writer import (
    compute_change_summary,
    generate_yaml_snippet,
    reload_bayesian_integration,
    save_yaml_config,
)
from bayesian_studio.engine.database import get_engine, get_read_connection
from bayesian_studio.engine.state_db import get_attr_at, get_state_at, load_state_timelines

# ---------------------------------------------------------------------------
# Config dir
# ---------------------------------------------------------------------------

CONFIG_DIR = os.environ.get("HASS_CONFIG", "/config")

# ---------------------------------------------------------------------------
# HA history-graph colors (from frontend source: timeline-color.ts)
# ---------------------------------------------------------------------------

_ACTIVE_COLOR = "#FDD835"                  # amber/yellow — HA binary_sensor on
_INACTIVE_COLOR = "#e0e0e0"                # grey — HA binary_sensor off
_UNKNOWN_COLOR = "rgba(128,128,128,0.15)"  # translucent grey — light + dark

_BINARY_CHART_H = 40    # thin horizontal timeline
_NUMERIC_CHART_H = 360  # taller step-line chart
_CHART_HEIGHT = 420     # main probability chart

_SPINNER_HTML = (
    '<div style="height:{h}px;display:flex;align-items:center;'
    'justify-content:center;font-size:12px;color:inherit;">'
    '⏳ Loading history…</div>'
)

_MAX_CHART_POINTS = 500

# States that are considered "active" when rendering a raw entity timeline as binary
_ACTIVE_BINARY_STATES = frozenset({"on", "home", "open", "unlocked", "true"})
# All recognised binary states (both active and inactive sides)
_BINARY_STATES = frozenset({
    "on", "off", "home", "not_home", "open", "closed",
    "locked", "unlocked", "true", "false",
})

# ---------------------------------------------------------------------------
# Time period options
# ---------------------------------------------------------------------------

_PERIODS = {
    "1 hour":  timedelta(hours=1),
    "1 day":   timedelta(days=1),
    "1 week":  timedelta(weeks=1),
    "1 month": timedelta(days=30),
}

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
    margin=dict(l=20, r=20, t=50, b=40),
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
def _get_config(entity_id: str, _version: int = 0):
    return load_bayesian_config(entity_id, CONFIG_DIR)


@st.cache_data(show_spinner="Loading state timelines from database…", ttl=300)
def _get_timelines(entity_ids: tuple, start_ts: float, end_ts: float, load_attrs: bool):
    engine = _get_engine()
    with get_read_connection(engine) as conn:
        return load_state_timelines(list(entity_ids), start_ts, end_ts, load_attrs, conn)


@st.cache_data(ttl=120)
def _get_location():
    return load_location(CONFIG_DIR)


@st.cache_data(ttl=120)
def _search_entities(query: str) -> list[str]:
    return search_entity_ids(query, CONFIG_DIR)


@st.cache_resource(show_spinner=False)
def _get_local_tz():
    return ZoneInfo(load_timezone(CONFIG_DIR))


@st.cache_data(show_spinner=False, ttl=120)
def _get_obs_names(file_path: str, unique_id: str, _version: int = 0) -> list[str]:
    return extract_observation_names(file_path, unique_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _downsample(pts: list, max_pts: int = _MAX_CHART_POINTS) -> list:
    """Reduce (ts, value) pairs to max_pts, preserving min/max per bucket."""
    if len(pts) <= max_pts:
        return pts
    bucket_count = max_pts // 2
    bucket_size = len(pts) / bucket_count
    result = [pts[0]]
    for b in range(bucket_count):
        lo = int(b * bucket_size)
        hi = int((b + 1) * bucket_size)
        bucket = pts[lo:hi]
        if not bucket:
            continue
        min_pt = min(bucket, key=lambda p: p[1])
        max_pt = max(bucket, key=lambda p: p[1])
        if min_pt[0] <= max_pt[0]:
            result.extend([min_pt, max_pt])
        else:
            result.extend([max_pt, min_pt])
    result.append(pts[-1])
    return result


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
        for key in ("prob_given_true", "prob_given_false", "to_state", "above", "below", "value_template"):
            if w_obs.get(key) != o_obs.get(key):
                return True
    if working.get("_obs_names") != working.get("_orig_obs_names"):
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
        obs["value_template"] = st.text_area(
            "value_template",
            value=template_text,
            key=f"tpl_{sensor_id}_{i}",
            height=68,
        )


def _is_binary_entity(entity_id: str, timelines: dict) -> bool:
    """Return True if all observed states for entity_id are known binary values."""
    tl = timelines.get(entity_id, {})
    observed = {s for s in tl.get("state", []) if s not in ("unavailable", "unknown", None)}
    if not observed:
        return True  # no data — default to binary display
    return observed.issubset(_BINARY_STATES)


def _entity_binary_results(entity_id: str, timelines: dict, dt_vals: list) -> list:
    """Convert entity timeline to True/False/None list aligned with dt_vals."""
    tl = timelines.get(entity_id, {})
    results = []
    for dt in dt_vals:
        state = get_state_at(tl, dt.timestamp())
        if state is None:
            results.append(None)
        else:
            results.append(state in _ACTIVE_BINARY_STATES)
    return results


def _build_binary_chart(
    results_col: list,
    dt_vals: list,
    end_dt: datetime,
    height: int = _BINARY_CHART_H,
    start_dt: datetime | None = None,
) -> go.Figure:
    """Build an HA history-graph style activation timeline from obs_results."""
    fig = go.Figure()
    if not results_col or not dt_vals:
        return fig

    range_start = start_dt or dt_vals[0]

    segments = []
    seg_start = dt_vals[0]
    seg_val = results_col[0]
    for j in range(1, len(results_col)):
        if results_col[j] != seg_val:
            segments.append((seg_start, dt_vals[j], seg_val))
            seg_start = dt_vals[j]
            seg_val = results_col[j]
    segments.append((seg_start, end_dt, seg_val))

    total_span = (end_dt - range_start).total_seconds()

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
        seg_span = (x1 - x0).total_seconds()
        if val is not None and total_span > 0 and seg_span / total_span > 0.08:
            label = "active" if val is True else "inactive"
            mid_x = x0 + (x1 - x0) / 2
            fig.add_annotation(
                x=mid_x, y=0.5, text=label, showarrow=False,
                font=dict(size=10, color="gray"),
                xanchor="center", yanchor="middle",
            )

    # One hover point per segment start — shows state label + time
    x_hover = [seg[0] for seg in segments]
    labels = [
        "active" if val is True else ("inactive" if val is False else "unknown")
        for _, _, val in segments
    ]
    fig.add_trace(go.Scatter(
        x=x_hover, y=[0.5] * len(x_hover),
        mode="markers", marker=dict(opacity=0, size=1),
        showlegend=False,
        customdata=labels,
        hovertemplate="%{customdata} — %{x|%b %d %H:%M}<extra></extra>",
    ))
    fig.update_layout(
        height=height,
        margin=dict(l=40, r=0, t=2, b=2),
        xaxis=dict(
            showticklabels=False, showgrid=False, zeroline=False,
            range=[range_start, end_dt], fixedrange=True,
        ),
        yaxis=dict(
            showticklabels=False, showgrid=False, zeroline=False,
            range=[0, 1], fixedrange=True,
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hovermode="x",
        dragmode=False,
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

    pts = []
    for ts, s in zip(ts_list, state_list):
        try:
            pts.append((ts, float(s)))
        except (ValueError, TypeError):
            pass

    # Forward-fill: if no numeric points, use the last known state as a flat
    # line across the range.  This matches HA behaviour — no state-change means
    # the entity keeps its most recent value.
    if not pts:
        last = get_state_at(tl, start_ts)
        if last is not None:
            try:
                pts = [(start_ts, float(last))]
            except (ValueError, TypeError):
                pass

    pts = _downsample(pts)

    if pts:
        x_vals = [datetime.fromtimestamp(ts, tz=_get_local_tz()) for ts, _ in pts]
        y_vals = [v for _, v in pts]
        x_vals.append(datetime.fromtimestamp(end_ts, tz=timezone.utc))
        y_vals.append(y_vals[-1])

        fig.add_trace(go.Scatter(
            x=x_vals, y=y_vals,
            mode="lines",
            name="Value",
            line=dict(color="#009ac7", width=1.5, shape="hv"),
            showlegend=False,
            hovertemplate="%{y:.2f}<br>%{x|%b %d %H:%M}<extra></extra>",
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

        start_dt = datetime.fromtimestamp(start_ts, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end_ts, tz=timezone.utc)
        chart_layout = dict(_HA_CHART)
        chart_layout["xaxis"] = dict(_HA_CHART["xaxis"], tickformat="%b %d\n%H:%M", dtick=43200000,
                                     range=[start_dt, end_dt])
        chart_layout["yaxis"] = dict(_HA_CHART["yaxis"], range=[y_lo, y_hi])
        chart_layout["xaxis"] = dict(chart_layout["xaxis"], fixedrange=True)
        chart_layout["yaxis"] = dict(chart_layout["yaxis"], fixedrange=True)
        chart_layout["margin"] = dict(l=40, r=0, t=4, b=0)
        fig.update_layout(**chart_layout, height=_NUMERIC_CHART_H, dragmode=False)
    return fig


_TRACE_COLORS = ["#009ac7", "#ff9800", "#dc3146", "#4caf50", "#9c27b0", "#795548"]


def _build_multi_numeric_chart(
    entities: list,  # [(entity_id, timeline), ...]
    start_ts: float,
    end_ts: float,
    unit: str = "",
) -> go.Figure:
    """Build a step-line chart with one trace per entity, sharing the same y-axis."""
    fig = go.Figure()
    y_all = []

    for idx, (eid, tl) in enumerate(entities):
        ts_list = tl.get("ts", [])
        state_list = tl.get("state", [])
        pts = []
        for ts, s in zip(ts_list, state_list):
            try:
                pts.append((ts, float(s)))
            except (ValueError, TypeError):
                pass
        if not pts:
            last = get_state_at(tl, start_ts)
            if last is not None:
                try:
                    pts = [(start_ts, float(last))]
                except (ValueError, TypeError):
                    pass
        pts = _downsample(pts)
        if not pts:
            continue

        x_vals = [datetime.fromtimestamp(ts, tz=_get_local_tz()) for ts, _ in pts]
        y_vals = [v for _, v in pts]
        x_vals.append(datetime.fromtimestamp(end_ts, tz=timezone.utc))
        y_vals.append(y_vals[-1])
        y_all.extend(y_vals)

        short_name = eid.split(".")[-1]
        color = _TRACE_COLORS[idx % len(_TRACE_COLORS)]
        fig.add_trace(go.Scatter(
            x=x_vals, y=y_vals,
            mode="lines",
            name=short_name,
            line=dict(color=color, width=1.5, shape="hv"),
            hovertemplate=f"{short_name}: %{{y:.2f}}<br>%{{x|%b %d %H:%M}}<extra></extra>",
        ))

    if not y_all:
        return fig

    y_lo = min(y_all) - abs(min(y_all)) * 0.05 - 0.1
    y_hi = max(y_all) + abs(max(y_all)) * 0.05 + 0.1
    start_dt = datetime.fromtimestamp(start_ts, tz=timezone.utc)
    end_dt = datetime.fromtimestamp(end_ts, tz=timezone.utc)
    chart_layout = dict(_HA_CHART)
    chart_layout["xaxis"] = dict(_HA_CHART["xaxis"], tickformat="%b %d\n%H:%M", dtick=43200000,
                                 range=[start_dt, end_dt])
    chart_layout["yaxis"] = dict(_HA_CHART["yaxis"], range=[y_lo, y_hi],
                                 title=dict(text=unit, font=dict(size=11)) if unit else {})
    chart_layout["xaxis"] = dict(chart_layout["xaxis"], fixedrange=True)
    chart_layout["yaxis"] = dict(chart_layout["yaxis"], fixedrange=True)
    chart_layout["margin"] = dict(l=40, r=0, t=4, b=0)
    fig.update_layout(**chart_layout, height=_NUMERIC_CHART_H, dragmode=False,
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, font=dict(size=11)))
    return fig


def _build_entity_preview_chart(
    entity_id: str, timelines: dict, start_ts: float, end_ts: float
) -> go.Figure:
    """Build a preview chart from raw entity timeline data (for the add-observation form)."""
    tl = timelines.get(entity_id, {})
    if _is_binary_entity(entity_id, timelines):
        ts_list = tl.get("ts", [])
        state_list = tl.get("state", [])
        pts = [(ts, s) for ts, s in zip(ts_list, state_list) if start_ts <= ts <= end_ts]
        if not pts:
            last = get_state_at(tl, start_ts)
            if last is not None:
                pts = [(start_ts, last)]
        if not pts:
            return go.Figure()
        dt_p = [datetime.fromtimestamp(ts, tz=_get_local_tz()) for ts, _ in pts]
        res_p = [s in _ACTIVE_BINARY_STATES for _, s in pts]
        return _build_binary_chart(
            res_p, dt_p,
            end_dt=datetime.fromtimestamp(end_ts, tz=timezone.utc),
            start_dt=datetime.fromtimestamp(start_ts, tz=timezone.utc),
        )
    else:
        return _build_numeric_chart(tl, {}, start_ts, end_ts)


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
    range_start = datetime.fromtimestamp(start_ts, tz=timezone.utc)
    for i, platform, obs, slot in slots:
        entity_id = obs.get("entity_id", "")

        if platform == "numeric_state" and entity_id:
            tl = timelines.get(entity_id, {})
            results_col = [r["obs_results"][i] for r in rows if i < len(r["obs_results"])]
            with slot.container():
                if results_col:
                    fig = _build_binary_chart(results_col, dt_vals, end_dt, start_dt=range_start)
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False},
                                    key=f"obs_result_num_{i}_{entity_id}")
                if tl:
                    fig = _build_numeric_chart(tl, obs, start_ts, end_ts)
                    if fig.data:
                        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False},
                                        key=f"obs_chart_num_{i}_{entity_id}")
                    else:
                        st.caption("No recorder data found for this entity")
                elif not results_col:
                    st.caption("No recorder data found for this entity")
        elif platform == "template":
            results_col = [r["obs_results"][i] for r in rows if i < len(r["obs_results"])]
            sub_entity_ids = extract_template_entity_ids_for_obs(obs)
            with slot.container():
                if results_col:
                    fig = _build_binary_chart(results_col, dt_vals, end_dt, start_dt=range_start)
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False},
                                    key=f"obs_chart_tpl_{i}")
                else:
                    st.caption("No data in selected range")

                # Partition sub-entities into binary vs numeric
                binary_subs = []
                numeric_subs = []  # [(eid, tl, unit), ...]
                for eid in sub_entity_ids:
                    if eid not in timelines:
                        continue
                    if _is_binary_entity(eid, timelines):
                        binary_subs.append(eid)
                    else:
                        tl = timelines[eid]
                        unit = get_attr_at(tl, end_ts, "unit_of_measurement") or ""
                        numeric_subs.append((eid, tl, unit))

                for eid in binary_subs:
                    st.caption(eid)
                    sub_results = _entity_binary_results(eid, timelines, dt_vals)
                    if sub_results:
                        fig = _build_binary_chart(sub_results, dt_vals, end_dt, start_dt=range_start)
                        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False},
                                        key=f"obs_chart_tpl_sub_{i}_{eid}")

                numeric_subs.sort(key=lambda x: x[2])
                from itertools import groupby
                for unit, group in groupby(numeric_subs, key=lambda x: x[2]):
                    group_entities = [(eid, tl) for eid, tl, _ in group]
                    if len(group_entities) == 1:
                        eid, tl = group_entities[0]
                        st.caption(eid)
                        fig = _build_numeric_chart(tl, {}, start_ts, end_ts)
                    else:
                        st.caption(unit or "Numeric entities")
                        fig = _build_multi_numeric_chart(group_entities, start_ts, end_ts, unit)
                    if fig.data:
                        grp_key = "_".join(eid for eid, _ in group_entities)
                        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False},
                                        key=f"obs_chart_tpl_sub_num_{i}_{grp_key}")
        else:
            results_col = [r["obs_results"][i] for r in rows if i < len(r["obs_results"])]
            if results_col:
                fig = _build_binary_chart(results_col, dt_vals, end_dt, start_dt=range_start)
                with slot.container():
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False},
                                    key=f"obs_chart_bin_{i}_{entity_id}")
            else:
                with slot.container():
                    st.caption("No data in selected range")


# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------

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

col_back, col_sensor = st.columns([1, 5])
with col_back:
    if st.button("← Overview"):
        st.switch_page("pages/overview.py")
with col_sensor:
    selected = st.selectbox(
        "Sensor", sensor_ids, index=default_idx,
        format_func=lambda s: s.removeprefix("binary_sensor."),
    )
st.query_params["sensor"] = selected
st.session_state["_current_sensor"] = selected

# --- Load config ---
try:
    _cfg_ver = st.session_state.get(f"_cfg_ver_{selected}", 0)
    raw_config, source = _get_config(selected, _cfg_ver)
except ValueError as e:
    st.error(str(e))
    st.stop()

observations_orig = raw_config.get("observations", [])
prior_orig = float(raw_config.get("prior", 0.5))
threshold_orig = float(raw_config.get("probability_threshold", 0.5))

# Working config in session state (reset when sensor changes)
state_key = f"working_config_{selected}"
if state_key not in st.session_state:
    names = (
        _get_obs_names(source.file_path, raw_config.get("unique_id", ""), _cfg_ver)
        if source.kind == "yaml" and source.file_path else None
    )
    if names is not None:
        # Pad/truncate to match observation count
        n = len(observations_orig)
        names = (names + [""] * n)[:n]
    st.session_state[state_key] = {
        "observations": copy.deepcopy(observations_orig),
        "prior": prior_orig,
        "threshold": threshold_orig,
        "_obs_names": list(names) if names is not None else None,
        "_orig_obs_names": list(names) if names is not None else None,
    }

working = st.session_state[state_key]

# --- Sensor parameters ---
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

# --- Probability chart placeholder (filled after trace computation) ---
chart_slot = st.empty()
stats_slot = st.empty()
with chart_slot.container():
    st.markdown(
        f'<div style="height:{_CHART_HEIGHT}px;display:flex;align-items:center;'
        f'justify-content:center;color:inherit;">⏳ Computing probability trace…</div>',
        unsafe_allow_html=True,
    )

# --- Time period selector ---
_tz_label = datetime.now(_get_local_tz()).strftime("%Z")
period = st.radio(
    f"Time period ({_tz_label})",
    options=list(_PERIODS.keys()) + ["Custom"],
    index=1,  # default: 1 day
    horizontal=True,
    key=f"period_{selected}",
)

_local_tz = _get_local_tz()
now = datetime.now(_local_tz)
if period == "Custom":
    col_start, col_end = st.columns(2)
    with col_start:
        start_date = st.date_input("From", value=(now - timedelta(days=1)).date())
    with col_end:
        end_date = st.date_input("To", value=now.date())
    start_ts = datetime(
        start_date.year, start_date.month, start_date.day, tzinfo=_local_tz
    ).timestamp()
    end_ts = datetime(
        end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=_local_tz
    ).timestamp()
else:
    _QUANT = 300
    _raw_ts = now.timestamp()
    _now_ts = _raw_ts - (_raw_ts % _QUANT) + _QUANT  # round up to next 5-min boundary
    end_ts = _now_ts
    start_ts = end_ts - _PERIODS[period].total_seconds()

if start_ts >= end_ts:
    st.error("Start date must be before end date.")
    st.stop()

# --- Load timelines ---
obs_entity_ids = [obs["entity_id"] for obs in working["observations"] if "entity_id" in obs]
template_entity_ids = _extract_template_entity_ids(working["observations"])
all_entity_ids = list(set(obs_entity_ids + template_entity_ids))
load_attrs = any(
    obs.get("platform") == "template" or "state_attr(" in obs.get("value_template", "")
    for obs in working["observations"]
)
timelines = _get_timelines(tuple(sorted(all_entity_ids)), start_ts, end_ts, load_attrs)

# --- Observations ---
st.subheader("Observations")

obs_count = len(working["observations"])
st.caption(f"{obs_count} observation{'s' if obs_count != 1 else ''}")

# Per-observation: prominent summary + subdued expander for details
obs_chart_slots = []
for i, obs in enumerate(working["observations"]):
    platform = obs.get("platform", "?")
    eid = obs.get("entity_id", "") if platform != "template" else ""
    pgt = obs.get("prob_given_true", 0.5)
    pgf = obs.get("prob_given_false", 0.1)

    obs_names = working.get("_obs_names")
    name = obs_names[i] if obs_names is not None and i < len(obs_names) else ""

    col_hdr, col_rm = st.columns([10, 1])
    with col_hdr:
        if name and eid:
            st.markdown(
                f"**{name}**  \n"
                f"{platform} · `{eid}` · P(true) {pgt} · P(false) {pgf}"
            )
        elif name:
            st.markdown(
                f"**{name}**  \n"
                f"{platform} · P(true) {pgt} · P(false) {pgf}"
            )
        elif eid:
            st.markdown(
                f"**{platform}** · `{eid}`  \n"
                f"P(true) {pgt} · P(false) {pgf}"
            )
        else:
            st.markdown(
                f"**{platform}**  \n"
                f"P(true) {pgt} · P(false) {pgf}"
            )
    with col_rm:
        if st.button("✕", key=f"rm_{selected}_{i}", help="Remove observation"):
            working["observations"].pop(i)
            if working.get("_obs_names") is not None:
                working["_obs_names"].pop(i)
            if working.get("_orig_obs_names") is not None:
                working["_orig_obs_names"].pop(i)
            st.rerun()

    if obs_names is not None:
        new_name = st.text_input(
            "Name", value=name,
            key=f"obs_name_{selected}_{i}",
            placeholder="Give this observation a name…",
            label_visibility="collapsed",
        )
        obs_names[i] = new_name

    # Chart placeholder with spinner
    h = (_BINARY_CHART_H + _NUMERIC_CHART_H) if platform == "numeric_state" else _BINARY_CHART_H
    slot = st.empty()
    with slot.container():
        st.markdown(_SPINNER_HTML.format(h=h), unsafe_allow_html=True)
    obs_chart_slots.append((i, platform, copy.copy(obs), slot))

    # Condition inputs + prob sliders
    _render_condition_inputs(obs, i, selected, timelines)
    col_t, col_f = st.columns(2)
    with col_t:
        obs["prob_given_true"] = st.slider(
            "prob_given_true", 0.001, 0.999,
            float(obs.get("prob_given_true", 0.5)), 0.001,
            key=f"pgt_{selected}_{i}",
        )
    with col_f:
        obs["prob_given_false"] = st.slider(
            "prob_given_false", 0.001, 0.999,
            float(obs.get("prob_given_false", 0.1)), 0.001,
            key=f"pgf_{selected}_{i}",
        )

    if i < len(working["observations"]) - 1:
        st.divider()

# --- Add observation ---
with st.expander("➕ Add observation"):
    _add_key = st.session_state.get(f"_add_key_{selected}", 0)

    _new_plat = st.selectbox(
        "Platform", ["state", "numeric_state", "template"],
        key=f"_new_plat_{selected}_{_add_key}",
    )

    _preview_tl: dict = {}
    _new_entity: str | None = None

    if _new_plat in ("state", "numeric_state"):
        _search_q = st.text_input(
            "Search entities", placeholder="Type to search…",
            key=f"_new_q_{selected}_{_add_key}",
        )
        _results = _search_entities(_search_q)
        if _results:
            _new_entity = st.selectbox("Entity", _results, key=f"_new_ent_{selected}_{_add_key}")
        elif _search_q:
            st.caption("No matching entities.")

        if _new_entity:
            _preview_tl = _get_timelines((_new_entity,), start_ts, end_ts, False)
            _prev_fig = _build_entity_preview_chart(_new_entity, _preview_tl, start_ts, end_ts)
            if _prev_fig.data:
                st.plotly_chart(_prev_fig, use_container_width=True, config={"displayModeBar": False},
                                key=f"preview_{_new_entity}_{_add_key}")
            else:
                st.caption("No recorder history in this time window.")

    # Platform-specific fields
    _new_to_state = "on"
    _new_above: float | None = None
    _new_below: float | None = None
    _new_template = ""

    if _new_plat == "state":
        _obs_states = _observed_states(_new_entity, _preview_tl) if _new_entity else []
        if _obs_states:
            _new_to_state = st.selectbox("to_state", _obs_states, key=f"_new_ts_{selected}_{_add_key}")
        else:
            _new_to_state = st.text_input("to_state", value="on", key=f"_new_ts_{selected}_{_add_key}")

    elif _new_plat == "numeric_state":
        _col_a, _col_b = st.columns(2)
        with _col_a:
            _use_above = st.checkbox("Set 'above'", key=f"_above_cb_{selected}_{_add_key}")
            if _use_above:
                _new_above = st.number_input("above", value=0.0, key=f"_above_v_{selected}_{_add_key}")
        with _col_b:
            _use_below = st.checkbox("Set 'below'", key=f"_below_cb_{selected}_{_add_key}")
            if _use_below:
                _new_below = st.number_input("below", value=100.0, key=f"_below_v_{selected}_{_add_key}")

    elif _new_plat == "template":
        _new_template = st.text_area(
            "value_template", placeholder="{{ states('sensor.foo') == 'on' }}",
            key=f"_new_tpl_{selected}_{_add_key}",
        )
        if _new_template:
            _extracted = extract_template_entity_ids_for_obs(
                {"platform": "template", "value_template": _new_template}
            )
            if _extracted:
                st.caption(f"Referenced entities: {', '.join(_extracted)}")

    _col_t, _col_f = st.columns(2)
    with _col_t:
        _new_pgt = st.slider("prob_given_true", 0.001, 0.999, 0.5, 0.001,
                             key=f"_new_pgt_{selected}_{_add_key}")
    with _col_f:
        _new_pgf = st.slider("prob_given_false", 0.001, 0.999, 0.1, 0.001,
                             key=f"_new_pgf_{selected}_{_add_key}")

    _can_add = (
        (_new_plat in ("state", "numeric_state") and _new_entity is not None) or
        (_new_plat == "template" and bool(_new_template.strip()))
    )

    if st.button("Add", key=f"_add_btn_{selected}_{_add_key}", disabled=not _can_add, type="primary"):
        _new_obs: dict = {
            "platform": _new_plat,
            "prob_given_true": _new_pgt,
            "prob_given_false": _new_pgf,
        }
        if _new_plat == "state":
            _new_obs["entity_id"] = _new_entity
            _new_obs["to_state"] = _new_to_state
        elif _new_plat == "numeric_state":
            _new_obs["entity_id"] = _new_entity
            if _new_above is not None:
                _new_obs["above"] = _new_above
            if _new_below is not None:
                _new_obs["below"] = _new_below
        elif _new_plat == "template":
            _new_obs["value_template"] = _new_template.strip()
        working["observations"].append(_new_obs)
        if working.get("_obs_names") is not None:
            working["_obs_names"].append("")
            working["_orig_obs_names"].append("")
        st.session_state[f"_add_key_{selected}"] = _add_key + 1
        st.rerun()

# --- Reset button ---
is_dirty = _config_changed(working, observations_orig, prior_orig, threshold_orig)
if st.button("Reset to original", disabled=not is_dirty):
    orig_names = working.get("_orig_obs_names")
    st.session_state[state_key] = {
        "observations": copy.deepcopy(observations_orig),
        "prior": prior_orig,
        "threshold": threshold_orig,
        "_obs_names": list(orig_names) if orig_names is not None else None,
        "_orig_obs_names": list(orig_names) if orig_names is not None else None,
    }
    # Clear widget state so sliders/inputs re-initialize from reset values
    _reset_prefixes = (
        f"prior_{selected}", f"thresh_{selected}",
        f"pgt_{selected}_", f"pgf_{selected}_",
        f"obs_name_{selected}_",
        f"to_state_{selected}_", f"above_{selected}_",
        f"below_{selected}_", f"tpl_{selected}_",
    )
    for _k in list(st.session_state.keys()):
        if isinstance(_k, str) and any(_k.startswith(_p) for _p in _reset_prefixes):
            del st.session_state[_k]
    st.rerun()

_save_ok_key = f"_save_ok_{selected}"
_backfill_key = f"_backfill_{selected}"

# --- Save / copy UI ---
if is_dirty:
    changes = compute_change_summary(working, observations_orig, prior_orig, threshold_orig)

    if source.kind == "yaml":
        with st.expander("Pending changes", expanded=True):
            for c in changes:
                st.markdown(f"- **{c['field']}**: `{c['old']}` → `{c['new']}`")

        confirm_key = f"save_confirm_{selected}"
        if not st.session_state.get(confirm_key):
            if st.button("💾 Save to YAML", type="primary", key=f"save_{selected}"):
                st.session_state[confirm_key] = True
                st.rerun()
        else:
            st.warning("This will overwrite your YAML config file and backfill the selected time period.")
            col_yes, col_no = st.columns(2)
            with col_yes:
                if st.button("Confirm save", type="primary", key=f"confirm_yes_{selected}"):
                    unique_id = raw_config.get("unique_id", "")
                    save_yaml_config(source.file_path, unique_id, working)
                    reloaded = reload_bayesian_integration()
                    st.session_state[f"_cfg_ver_{selected}"] = st.session_state.get(f"_cfg_ver_{selected}", 0) + 1
                    del st.session_state[state_key]
                    del st.session_state[confirm_key]
                    # Auto-backfill the selected time period
                    from bayesian_studio.engine.backfill import get_sqlite_path, run_backfill
                    _db_path = get_sqlite_path(CONFIG_DIR)
                    _bf_result = None
                    if _db_path:
                        try:
                            _bf_lat, _bf_lon = _get_location()
                            _bf_result = run_backfill(
                                entity_id=selected,
                                working=working,
                                timelines=timelines,
                                start_ts=start_ts,
                                end_ts=end_ts,
                                lat=_bf_lat,
                                lon=_bf_lon,
                                config_dir=CONFIG_DIR,
                                tz=_local_tz,
                            )
                            _bf_result["period_seconds"] = end_ts - start_ts
                        except Exception as _bf_err:
                            _bf_result = {"error": str(_bf_err)}
                    msg = "Saved and reloaded!" if reloaded else "Saved. Reload HA to apply changes."
                    st.session_state[_save_ok_key] = msg
                    st.session_state[_backfill_key] = _bf_result
                    st.rerun()
            with col_no:
                if st.button("Cancel", key=f"confirm_no_{selected}"):
                    del st.session_state[confirm_key]
                    st.rerun()

    elif source.kind == "ui":
        st.info("UI-configured sensors can't be saved directly. Copy the YAML snippet below.")
        st.code(generate_yaml_snippet(working), language="yaml")

# --- Post-save banner + backfill results ---
if _save_ok_key in st.session_state:
    st.success(st.session_state.pop(_save_ok_key))

_bf_state = st.session_state.get(_backfill_key)
if isinstance(_bf_state, dict) and "rows_written" in _bf_state:
    st.success(
        f"Backfilled selected period: {_bf_state['rows_written']} rows "
        f"in {_bf_state['total_seconds']}s."
    )

    # Estimate full history backfill and offer the option
    from bayesian_studio.engine.backfill import get_full_history_range, get_sqlite_path, run_full_backfill
    _full_range = get_full_history_range(selected, CONFIG_DIR)
    if _full_range and _bf_state.get("period_seconds", 0) > 0:
        _full_start, _full_end = _full_range
        _full_span = _full_end - _full_start
        _period_span = _bf_state["period_seconds"]
        _period_time = _bf_state["total_seconds"]
        _est_seconds = (_full_span / _period_span) * _period_time if _period_span > 0 else 0
        _full_days = _full_span / 86400

        if _full_span > _period_span * 1.5:
            if _est_seconds < 60:
                _est_label = f"{_est_seconds:.0f}s"
            else:
                _est_label = f"{_est_seconds / 60:.1f} min"
            st.info(
                f"Full history spans {_full_days:.0f} days. "
                f"Estimated backfill time: **{_est_label}**."
            )
            _full_bf_key = f"_full_bf_{selected}"
            _full_bf_state = st.session_state.get(_full_bf_key)
            if _full_bf_state is None:
                if st.button("Backfill all history", key=f"_full_bf_btn_{selected}"):
                    _bf_lat, _bf_lon = _get_location()
                    _prog = st.progress(0.0, text="Backfilling full history…")
                    try:
                        _full_res = run_full_backfill(
                            entity_id=selected,
                            working=working,
                            start_ts=_full_start,
                            end_ts=_full_end,
                            lat=_bf_lat,
                            lon=_bf_lon,
                            config_dir=CONFIG_DIR,
                            progress_callback=lambda f: _prog.progress(f),
                            tz=_local_tz,
                        )
                        _prog.empty()
                        st.session_state[_full_bf_key] = _full_res
                        st.rerun()
                    except Exception as _bf_err:
                        _prog.empty()
                        st.session_state[_full_bf_key] = {"error": str(_bf_err)}
                        st.rerun()
            elif isinstance(_full_bf_state, dict) and "rows_written" in _full_bf_state:
                st.success(
                    f"Full backfill complete: {_full_bf_state['rows_written']} rows "
                    f"in {_full_bf_state['total_seconds']}s."
                )
            elif isinstance(_full_bf_state, dict) and "error" in _full_bf_state:
                st.error(f"Full backfill failed: {_full_bf_state['error']}")

elif isinstance(_bf_state, dict) and "error" in _bf_state:
    st.error(f"Backfill failed: {_bf_state['error']}")

# --- Compute trace ---
lat, lon = _get_location()
with st.spinner("Recalculating…"):
    trace = compute_probability_trace(
        working["observations"],
        working["prior"],
        working["threshold"],
        timelines,
        start_ts,
        end_ts,
        lat,
        lon,
        tz=_local_tz,
    )

rows = trace["rows"]
if not rows:
    chart_slot.warning("No events found in this time window.")
    st.stop()

ts_vals = [r["ts"] for r in rows]
prob_vals = [r["probability"] for r in rows]
state_vals = [r["state"] for r in rows]
dt_vals = [datetime.fromtimestamp(ts, tz=_get_local_tz()) for ts in ts_vals]
end_dt = datetime.fromtimestamp(end_ts, tz=timezone.utc)

# --- Build probability chart ---
fig = go.Figure()

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

fig.add_trace(go.Scatter(
    x=dt_vals, y=prob_vals,
    mode="lines",
    name="Probability",
    line=dict(color="#009ac7", width=2, shape="hv"),
))

fig.add_hline(
    y=working["threshold"],
    line_dash="dash",
    line_color="#ff9800",
    annotation_text=f"Threshold {working['threshold']:.2f}",
    annotation_position="top right",
    annotation_font_size=11,
)

y_all = prob_vals + [working["threshold"]]
y_lo = max(0.0, min(y_all) - 0.05)
y_hi = min(1.0, max(y_all) + 0.05)

start_dt = datetime.fromtimestamp(start_ts, tz=timezone.utc)
chart_layout = dict(_HA_CHART)
chart_layout["xaxis"] = dict(_HA_CHART["xaxis"], range=[start_dt, end_dt])
chart_layout["yaxis"] = dict(_HA_CHART["yaxis"], range=[y_lo, y_hi])
latest_prob = prob_vals[-1] if prob_vals else 0.0
latest_state = state_vals[-1] if state_vals else "off"
fig.update_layout(
    **chart_layout,
    title=f"{selected}  ·  {latest_prob:.1%} ({latest_state})",
    xaxis_title=None,
    yaxis_title="Probability",
    height=_CHART_HEIGHT,
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
)

with chart_slot.container():
    st.plotly_chart(fig, use_container_width=True, key=f"prob_{selected}")

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
