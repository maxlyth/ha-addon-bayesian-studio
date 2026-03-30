"""Bayesian Studio — sensor overview with calibration health."""
import os
from datetime import datetime, timedelta, timezone

import streamlit as st

from bayesian_studio.engine.config_loader import get_bayesian_entity_ids, load_bayesian_config
from bayesian_studio.engine.database import get_engine, get_read_connection
from bayesian_studio.engine.state_db import load_state_timelines
from bayesian_studio.health import (
    fire_frequency_from_timeline,
    observation_coverage,
)

CONFIG_DIR = os.environ.get("HASS_CONFIG", "/config")

WINDOW_DAYS = 7
now = datetime.now(timezone.utc)
end_ts = now.timestamp()
start_ts = (now - timedelta(days=WINDOW_DAYS)).timestamp()


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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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

st.caption(f"Last {WINDOW_DAYS} days · {now.strftime('%Y-%m-%d %H:%M')} UTC")

sensor_ids = _get_sensor_ids()
if not sensor_ids:
    st.error(f"No Bayesian sensors found in {CONFIG_DIR}.")
    st.stop()

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
        st.switch_page("pages/2_Studio.py")
