# Bayesian Studio

![Tests](https://github.com/maxlyth/ha-addon-bayesian-studio/actions/workflows/test.yml/badge.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![HA Add-on](https://img.shields.io/badge/HA-Add--on-41BDF5?logo=homeassistant)

Visual interactive tuning UI for Home Assistant Bayesian binary sensors. Runs as a local HA Supervisor add-on with ingress.

## Features

- **Overview page** — sensor health table with observation coverage, fire frequency, prior, threshold, and config source. Dynamic time window adapts to system performance (targets 8-second page load).
- **Studio page** — per-sensor tuning with interactive probability chart, observation sliders, and save-to-YAML with auto-backfill.
- **Observation friendly names** — editable names stored as inline YAML comments, shown in the UI for clarity.
- **Full HA template support** — Jinja2 environment with `states()`, `state_attr()`, `is_state()`, `has_value()`, `now()`, `utcnow()`, `today_at()`, `as_timestamp()`, `as_local()`, `timedelta()`, `float()`, `int()`, `bool()`, `is_number()`, `iif()`, and dotted `states.domain.name` access.
- **Adaptive synthetic timestamps** — time-dependent template observations (sun elevation, `now()` comparisons) are re-evaluated at appropriate intervals: every 40s (last 24h), 5min (last 7d), 15min (older).
- **Auto light/dark theme** — follows system preference via `prefers-color-scheme`.

## Installation

### As a local add-on (development)

1. Clone this repo into your HA `addons/` directory or use `deploy_local.sh` to sync:
   ```sh
   ./deploy_local.sh
   ```

2. In HA, go to **Settings > Add-ons > Add-on Store** and reload. The add-on appears under **Local add-ons**.

### From GitHub (public release)

Add this repository URL to your HA add-on store:
```
https://github.com/maxlyth/ha-addon-bayesian-studio
```

## Configuration

The add-on reads Bayesian sensor config from both:
- **YAML files** — scans your config directory for `platform: bayesian` entries
- **UI-created sensors** — reads from `.storage/core.config_entries`

Sensor changes made in the Studio page are written back to the source YAML file with round-trip comment preservation.

## Development

### Running tests

```sh
python -m pytest tests/ -q -m "not integration"
```

### Version bump

Three files must match (enforced by `test_version.py`):
- `bayesian-studio/config.yaml` — `version:`
- `bayesian-studio/Dockerfile` — `ARG VERSION=`
- `pyproject.toml` — `version =`

### Deploy locally

```sh
./deploy_local.sh
```

## Stack

- [Streamlit](https://streamlit.io/) behind HA ingress (port 8501)
- [s6-overlay](https://github.com/just-containers/s6-overlay) for process supervision
- SQLAlchemy + SQLite for HA recorder database access
- ruamel.yaml for round-trip YAML editing with comment preservation

## License

[MIT](LICENSE)
