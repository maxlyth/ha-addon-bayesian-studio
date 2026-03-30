"""Bayesian Studio — entry point."""
import os

import streamlit as st

VERSION = os.environ.get("VERSION", "dev")

st.set_page_config(
    page_title="Bayesian Studio",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Global CSS + fixed top bar
# ---------------------------------------------------------------------------

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap');

html, body, [class*="st-"], [data-testid] {
    font-family: 'Roboto', Noto, sans-serif !important;
}
h2 { font-size: 24px !important; font-weight: 700 !important; }
h3 { font-size: 14px !important; font-weight: 500 !important; }
p, li { font-size: 14px; }
small, [data-testid="stCaptionContainer"] { font-size: 12px; }

/* Hide sidebar entirely */
section[data-testid="stSidebar"] { display: none !important; }

/* Fixed top bar */
#bayesian-topbar {
    position: fixed;
    top: 0; left: 0;
    width: 100%;
    height: 48px;
    z-index: 999;
    display: flex;
    align-items: center;
    padding: 0 20px;
    font-family: 'Roboto', Noto, sans-serif;
    font-size: 16px;
    font-weight: 700;
    border-bottom: 1px solid var(--secondary-background-color);
    background: var(--background-color);
    color: var(--text-color);
    box-sizing: border-box;
}

header[data-testid="stHeader"] { display: none !important; }

/* Push Streamlit content below the top bar */
[data-testid="stAppViewContainer"] > section > div:first-child { padding-top: 60px !important; }

</style>
<div id="bayesian-topbar">Bayesian Studio<span style="margin-left:auto;font-size:11px;font-weight:400;opacity:0.6">v""" + VERSION + """</span></div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

overview_page = st.Page("pages/overview.py", title="Overview", icon="📊")
studio_page = st.Page("pages/bayesian_details.py", title="Studio", icon="🎛️")

pg = st.navigation([overview_page, studio_page], position="hidden")
pg.run()
