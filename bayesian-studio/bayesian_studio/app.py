"""Bayesian Studio — entry point with shared sidebar navigation."""
import os

import streamlit as st

from bayesian_studio.engine.config_loader import get_bayesian_entity_ids

CONFIG_DIR = os.environ.get("HASS_CONFIG", "/config")

st.set_page_config(
    page_title="Bayesian Studio",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data(ttl=120, show_spinner=False)
def _sidebar_sensor_ids():
    try:
        return get_bayesian_entity_ids("binary_sensor.*", CONFIG_DIR)
    except Exception:
        return []


overview_page = st.Page("pages/1_Overview.py", title="Overview", icon="📊")
studio_page = st.Page("pages/2_Studio.py", title="Studio", icon="🎛️")

# ---------------------------------------------------------------------------
# Sidebar — sensor navigator (replaces the default page list)
# ---------------------------------------------------------------------------
current = st.session_state.get("_current_sensor", "")

with st.sidebar:
    if st.button("📊 Overview", use_container_width=True):
        st.switch_page(overview_page)

    st.divider()
    st.caption("SENSORS")

    sensor_ids = _sidebar_sensor_ids()
    if not sensor_ids:
        st.caption("No sensors found")
    else:
        for sid in sensor_ids:
            label = sid.split(".")[-1] if "." in sid else sid
            if st.button(
                label,
                key=f"sb_{sid}",
                help=sid,
                use_container_width=True,
                type="primary" if sid == current else "secondary",
            ):
                st.session_state["_nav_sensor"] = sid
                st.session_state["_current_sensor"] = sid
                st.switch_page(studio_page)

# ---------------------------------------------------------------------------
# Navigation — page list hidden; sidebar above is the sole navigation
# ---------------------------------------------------------------------------
pg = st.navigation([overview_page, studio_page], position="hidden")
pg.run()
