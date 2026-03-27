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

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap');

html, body, [class*="st-"], [data-testid] {
    font-family: 'Roboto', Noto, sans-serif !important;
}
h1 { font-size: 20px !important; font-weight: 700 !important; }
h2 { font-size: 16px !important; font-weight: 700 !important; }
h3 { font-size: 14px !important; font-weight: 500 !important; }
p, li { font-size: 14px; }
small, [data-testid="stCaptionContainer"] { font-size: 12px; }

div[data-testid="stExpander"] {
    border-radius: 12px !important;
}
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=120, show_spinner=False)
def _sidebar_sensor_ids():
    try:
        return get_bayesian_entity_ids("binary_sensor.*", CONFIG_DIR)
    except Exception as e:
        st.sidebar.error(f"Failed to load sensors: {e}")
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
        labels = [sid.split(".")[-1] if "." in sid else sid for sid in sensor_ids]
        current_idx = sensor_ids.index(current) if current in sensor_ids else 0
        chosen_label = st.radio(
            "sensor",
            options=labels,
            index=current_idx,
            label_visibility="collapsed",
        )
        chosen_sid = sensor_ids[labels.index(chosen_label)]
        if chosen_sid != current:
            st.session_state["_nav_sensor"] = chosen_sid
            st.session_state["_current_sensor"] = chosen_sid
            st.switch_page(studio_page)

# ---------------------------------------------------------------------------
# Navigation — page list hidden; sidebar above is the sole navigation
# ---------------------------------------------------------------------------
pg = st.navigation([overview_page, studio_page], position="hidden")
pg.run()
