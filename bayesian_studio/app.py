"""Bayesian Studio — Streamlit entry point."""
import streamlit as st

st.set_page_config(
    page_title="Bayesian Studio",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("Bayesian Studio")
st.write("Select a sensor from the Studio page to begin tuning.")
st.page_link("pages/2_Studio.py", label="Open Studio →", icon="🎛️")
