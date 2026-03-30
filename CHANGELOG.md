# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.3.1] - 2026-03-27

### Fixed
- Sidebar sensor list not rendering — removed `st.sidebar.error()` from inside `@st.cache_data` (Streamlit anti-pattern that silently drops subsequent widgets)
- Overview page `StreamlitDuplicateElementKey` crash — "Tune →" buttons now use `row['Entity']` as key instead of stale loop variable
- Numeric observation history charts slow to load — downsampled to 500 points (min/max bucket preservation), default period changed from 7 days to 1 day

### Added
- Dark mode support: Auto/Light/Dark theme toggle in sidebar; Plotly charts use transparent backgrounds to inherit Streamlit's theme
- Fixed top bar ("Bayesian Studio" title) spanning sidebar and main pane
- Time period selector: 1 hour / 1 day / 1 week / 1 month / Custom (with date pickers)
- Observations section grouped into a single pane with per-observation summary captions and a single "Details" expander
- Direct container deployment via `deploy.sh` (no GitHub push required for Python-only changes)

## [0.3.0] - 2026-03-26

### Added
- Initial public release
- Overview page: sensor health table with coverage, fire frequency, prior, threshold, and config source
- Studio page: probability trace chart, observation tuning with sliders, config reset
- YAML and UI config source support
- HA Supervisor add-on with ingress on port 8501
