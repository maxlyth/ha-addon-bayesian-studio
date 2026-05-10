# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.4.11] - 2026-05-10

### Changed
- Distribution: add-on now installs via pre-built multi-arch images on GHCR (`ghcr.io/maxlyth/{arch}-bayesian-studio`) instead of building from source on the supervisor host. Faster install, no per-host Dockerfile rebuild. The add-on now belongs to a household add-on collection at `maxlyth/home-assistant-addons`.

### Added
- `bayesian-studio/build.yaml` — declares per-arch base images (HA 3.19 base) and OCI labels.
- `.github/workflows/builder.yaml` — multi-arch (`aarch64`, `amd64`) build/push to GHCR on every push to `main`. Adapted from the canonical `home-assistant/builder@2026.03.2` pattern.
- `.github/workflows/lint.yaml` — runs `frenck/action-addon-linter` on push/PR and nightly.

## [0.4.10] - 2026-03-30

### Added
- Full HA Jinja2 template extension support: `utcnow()`, `today_at()`, `as_timestamp()`, `as_datetime()`, `as_local()`, `strptime()`, `timedelta()`, `float()`, `int()`, `bool()`, `is_number()`, `iif()` — available as both globals and filters
- State access functions: `is_state()`, `is_state_attr()`, `has_value()`, dotted `states.domain.name` access
- Adaptive synthetic timestamps for template observations: 40s (last 24h), 5min (last 7d), 15min (older) — ensures time-dependent templates (sun elevation, `now()`) are re-evaluated at appropriate intervals
- Observation friendly names: stored as inline YAML comments, editable per observation, maintained through add/remove/reset
- Auto-backfill on save for selected time period with full-history backfill option
- Dynamic overview page time window: benchmarks system performance and adjusts window (1h–7d) to target 8-second page load
- Overview page health metrics: observation coverage, fire frequency, health badges

### Fixed
- Sun elevation template evaluating as active after sunset — synthetic timestamps ensure re-evaluation between entity state changes
- Deduplication in backfill: skip rows where probability and state are unchanged (prevents DB bloat from synthetic timestamps)

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
