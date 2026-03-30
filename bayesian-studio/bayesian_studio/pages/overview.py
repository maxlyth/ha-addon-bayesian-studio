"""Bayesian Studio — sensor overview with calibration health."""
import os
import time
from datetime import datetime, timezone

import streamlit as st

from zoneinfo import ZoneInfo

from bayesian_studio.engine.config_loader import get_bayesian_entity_ids, load_bayesian_config, load_timezone
from bayesian_studio.engine.database import get_engine, get_read_connection
from bayesian_studio.engine.state_db import load_state_timelines
from bayesian_studio.health import (
    fire_frequency_from_timeline,
    observation_coverage,
)

CONFIG_DIR = os.environ.get("HASS_CONFIG", "/config")

_QUANT = 300          # 5-minute quantization for stable cache keys
_LOAD_TARGET = 8.0    # target total page-load seconds
_BENCH_WINDOW = 1800  # 30-minute benchmark window
_MIN_WINDOW = 3600    # 1-hour floor
_MAX_WINDOW = 7 * 86400  # 7-day ceiling


@st.cache_resource(show_spinner=False)
def _get_local_tz():
    return ZoneInfo(load_timezone(CONFIG_DIR))


now = datetime.now(_get_local_tz())
_raw_end = now.timestamp()
end_ts = _raw_end - (_raw_end % _QUANT) + _QUANT  # round up to next 5-min boundary


# ---------------------------------------------------------------------------
# Cached loaders
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def _get_engine():
    return get_engine(CONFIG_DIR)


@st.cache_data(ttl=120, show_spinner="Discovering Bayesian sensors…")
def _get_sensor_ids():
    return get_bayesian_entity_ids("binary_sensor.*", CONFIG_DIR)


@st.cache_data(ttl=300, show_spinner=False)
def _get_config(entity_id):
    try:
        return load_bayesian_config(entity_id, CONFIG_DIR)
    except Exception:
        return None, None


@st.cache_data(ttl=300, show_spinner=False)
def _load_sensor_timelines(sensor_id: str, obs_entity_ids: tuple, s: float, e: float):
    """Load timelines for a single sensor and its observation entities."""
    all_ids = list(set(obs_entity_ids) | {sensor_id})
    engine = _get_engine()
    with get_read_connection(engine) as conn:
        return load_state_timelines(all_ids, s, e, load_attrs=False, conn=conn)


@st.cache_data(ttl=300, show_spinner=False)
def _get_window(sensor_count: int, bench_sid: str, bench_obs_ids: tuple, _end_ts: float) -> int:
    """Benchmark one sensor at 30 min and return window_seconds within the 8s budget.

    Cached with the same TTL as the timeline loader so the window stays stable
    within a cache period and _load_sensor_timelines cache hits are preserved.
    """
    b_start = _end_ts - _BENCH_WINDOW
    t0 = time.perf_counter()
    _load_sensor_timelines(bench_sid, bench_obs_ids, b_start, _end_ts)
    elapsed = time.perf_counter() - t0

    # Near-zero elapsed means the DB call was cached (warm reload) or the DB
    # is empty. In both cases the full window is fine.
    if elapsed < 0.005:
        return _MAX_WINDOW

    budget_per_sensor = _LOAD_TARGET / sensor_count
    window = _BENCH_WINDOW * (budget_per_sensor / elapsed)
    window = max(_MIN_WINDOW, min(_MAX_WINDOW, window))
    # Quantize to 5-min boundary so start_ts is stable across renders
    return int(round(window / _QUANT) * _QUANT)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_window(seconds: int) -> str:
    if seconds < 7200:        # < 2 hours → minutes
        return f"{seconds // 60} minutes"
    if seconds < 172800:      # < 48 hours → hours
        return f"{seconds // 3600} hours"
    return f"{seconds / 86400:.1f} days"


def _health_badge(coverage_avg: float, has_problem: bool) -> str:
    if has_problem:
        return "🔴"
    if coverage_avg < 0.5:
        return "🟡"
    return "🟢"


# ---------------------------------------------------------------------------
# Column layout
# ---------------------------------------------------------------------------

_COL_WIDTHS = [0.3, 3, 0.5, 1, 1.2, 0.8, 0.6, 0.7, 0.6, 0.5]
_COL_LABELS = ["", "Entity", "Obs", "Coverage", "Issues", "Fire freq",
               "Prior", "Threshold", "Source", ""]
_SORTABLE = {"Entity", "Obs", "Coverage", "Issues", "Fire freq", "Prior", "Threshold", "Source"}


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

sensor_ids = _get_sensor_ids()
if not sensor_ids:
    st.error(f"No Bayesian sensors found in {CONFIG_DIR}.")
    st.stop()

# --- Benchmark: find first sensor with valid config ---
window_seconds = _MAX_WINDOW
for _bench_sid in sensor_ids:
    _bench_raw, _ = _get_config(_bench_sid)
    if _bench_raw is not None:
        _bench_obs_ids = tuple(sorted(
            obs["entity_id"] for obs in _bench_raw.get("observations", []) if "entity_id" in obs
        ))
        window_seconds = _get_window(len(sensor_ids), _bench_sid, _bench_obs_ids, end_ts)
        break

start_ts = end_ts - window_seconds

st.caption(f"Last {_format_window(window_seconds)} · {now.strftime('%Y-%m-%d %H:%M %Z')}")

# --- Build rows: config instant, stats from per-sensor cached timeline queries ---
rows = []
_progress = st.progress(0, text=f"Loading sensor 1/{len(sensor_ids)}…")
for _i, sid in enumerate(sensor_ids):
    raw, source = _get_config(sid)
    label = sid.removeprefix("binary_sensor.")

    if raw is None:
        rows.append({
            "_sid": sid, "": "🔴", "Entity": label, "Obs": "—",
            "Coverage": "—", "Issues": "config error", "Fire freq": "—",
            "Prior": "—", "Threshold": "—", "Source": "—",
        })
        _progress.progress((_i + 1) / len(sensor_ids),
                           text=f"Loading sensor {_i + 2}/{len(sensor_ids)}…" if _i + 1 < len(sensor_ids) else "Done")
        continue

    observations = raw.get("observations", [])
    prior = float(raw.get("prior", 0.5))
    threshold = float(raw.get("probability_threshold", 0.5))
    source_str = source.kind if source else "?"

    obs_ids = tuple(sorted(
        obs["entity_id"] for obs in observations if "entity_id" in obs
    ))
    timelines = _load_sensor_timelines(sid, obs_ids, start_ts, end_ts)

    coverages = [
        observation_coverage(obs, timelines, start_ts, end_ts)
        for obs in observations
        if "entity_id" in obs
    ]
    avg_cov = sum(coverages) / len(coverages) if coverages else 0.0
    zero_cov = sum(1 for c in coverages if c == 0.0)
    issues = f"{zero_cov} obs no data" if zero_cov else "—"

    sensor_tl = timelines.get(sid, {})
    freq = fire_frequency_from_timeline(sensor_tl, start_ts, end_ts)

    rows.append({
        "_sid": sid,
        "": _health_badge(avg_cov, zero_cov > 0),
        "Entity": label,
        "Obs": len(observations),
        "Coverage": f"{avg_cov:.0%}",
        "Issues": issues,
        "Fire freq": f"{freq:.0%}",
        "Prior": f"{prior:.2f}",
        "Threshold": f"{threshold:.2f}",
        "Source": source_str,
    })
    _progress.progress((_i + 1) / len(sensor_ids),
                       text=f"Loading sensor {_i + 2}/{len(sensor_ids)}…" if _i + 1 < len(sensor_ids) else "Done")

_progress.empty()

# --- Sort ---
sort_col = st.session_state.get("_sort_col", "Entity")
sort_asc = st.session_state.get("_sort_asc", True)

if rows:
    rows.sort(key=lambda r: str(r.get(sort_col, "")), reverse=not sort_asc)

# --- Header row with sort buttons ---
header = st.columns(_COL_WIDTHS)
for col, lbl in zip(header, _COL_LABELS):
    if lbl in _SORTABLE:
        arrow = " ↑" if sort_col == lbl and sort_asc else " ↓" if sort_col == lbl else ""
        if col.button(f"{lbl}{arrow}", key=f"sort_{lbl}", use_container_width=True):
            if sort_col == lbl:
                st.session_state["_sort_asc"] = not sort_asc
            else:
                st.session_state["_sort_col"] = lbl
                st.session_state["_sort_asc"] = True
            st.rerun()
    elif lbl:
        col.markdown(f"**{lbl}**")

st.divider()

# --- Data rows with per-row tune button ---
for row in rows:
    cols = st.columns(_COL_WIDTHS)
    cols[0].write(row[""])
    cols[1].write(row["Entity"])
    cols[2].write(row["Obs"])
    cols[3].write(row["Coverage"])
    cols[4].write(row["Issues"])
    cols[5].write(row["Fire freq"])
    cols[6].write(row["Prior"])
    cols[7].write(row["Threshold"])
    cols[8].write(row["Source"])
    if cols[9].button("🔧", key=f"tune_{row['_sid']}"):
        st.session_state["_nav_sensor"] = row["_sid"]
        st.switch_page("pages/bayesian_details.py")
