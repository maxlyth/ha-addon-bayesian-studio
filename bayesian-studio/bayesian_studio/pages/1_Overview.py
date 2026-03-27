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


@st.cache_data(ttl=300, show_spinner="Loading history…")
def _load_timelines(entity_ids_key: tuple, s: float, e: float):
    engine = _get_engine()
    with get_read_connection(engine) as conn:
        return load_state_timelines(list(entity_ids_key), s, e, load_attrs=False, conn=conn)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

st.title("Bayesian Studio")
st.caption(f"Last {WINDOW_DAYS} days · {now.strftime('%Y-%m-%d %H:%M')} UTC")

sensor_ids = _get_sensor_ids()
if not sensor_ids:
    st.error(f"No Bayesian sensors found in {CONFIG_DIR}.")
    st.stop()

# --- Collect all entity IDs needed for timelines ---
configs = {}
all_obs_entity_ids: set[str] = set()
for sid in sensor_ids:
    raw, source = _get_config(sid)
    configs[sid] = (raw, source)
    if raw:
        for obs in raw.get("observations", []):
            if "entity_id" in obs:
                all_obs_entity_ids.add(obs["entity_id"])
        # Include the sensor itself for fire frequency
        all_obs_entity_ids.add(sid)

timelines = _load_timelines(tuple(sorted(all_obs_entity_ids)), start_ts, end_ts)

# --- Build rows ---
def _health_badge(coverage_avg: float, has_problem: bool) -> str:
    if has_problem:
        return "🔴"
    if coverage_avg < 0.5:
        return "🟡"
    return "🟢"


rows = []
for sid in sensor_ids:
    raw, source = configs[sid]
    if raw is None:
        rows.append({
            "": "🔴", "Entity": sid, "Obs": "—", "Avg coverage": "—",
            "Issues": "config error", "Fire freq": "—", "Prior": "—",
            "Threshold": "—", "Source": "—",
        })
        continue

    observations = raw.get("observations", [])
    prior = float(raw.get("prior", 0.5))
    threshold = float(raw.get("probability_threshold", 0.5))
    source_str = source.kind if source else "?"

    coverages = [
        observation_coverage(obs, timelines, start_ts, end_ts)
        for obs in observations
        if "entity_id" in obs
    ]
    avg_cov = sum(coverages) / len(coverages) if coverages else 0.0

    zero_cov = sum(1 for c in coverages if c == 0.0)
    issues = f"{zero_cov} obs no data" if zero_cov else ""

    sensor_tl = timelines.get(sid, [])
    freq = fire_frequency_from_timeline(sensor_tl, start_ts, end_ts)

    rows.append({
        "": _health_badge(avg_cov, bool(issues)),
        "Entity": sid,
        "Obs": len(observations),
        "Avg coverage": f"{avg_cov:.0%}",
        "Issues": issues or "—",
        "Fire freq": f"{freq:.0%}",
        "Prior": f"{prior:.2f}",
        "Threshold": f"{threshold:.2f}",
        "Source": source_str,
    })

# --- Table with navigate buttons ---
header = st.columns([0.3, 3, 0.5, 1.2, 1.5, 1, 0.7, 0.8, 0.7, 0.8])
labels = ["", "Entity", "Obs", "Coverage", "Issues", "Fire freq", "Prior", "Threshold", "Source", ""]
for col, lbl in zip(header, labels):
    col.markdown(f"**{lbl}**")

st.divider()

for row in rows:
    cols = st.columns([0.3, 3, 0.5, 1.2, 1.5, 1, 0.7, 0.8, 0.7, 0.8])
    cols[0].write(row[""])
    cols[1].write(row["Entity"])
    cols[2].write(row["Obs"])
    cols[3].write(row["Avg coverage"])
    cols[4].write(row["Issues"])
    cols[5].write(row["Fire freq"])
    cols[6].write(row["Prior"])
    cols[7].write(row["Threshold"])
    cols[8].write(row["Source"])
    if cols[9].button("Tune →", key=f"tune_{sid}"):
        st.session_state["_nav_sensor"] = sid
        st.switch_page("pages/2_Studio.py")
