# Bayesian Studio

![Tests](https://github.com/maxlyth/ha-addon-bayesian-studio/actions/workflows/test.yml/badge.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![HA Add-on](https://img.shields.io/badge/HA-Add--on-41BDF5?logo=homeassistant)

Visual interactive tuning UI for Home Assistant Bayesian binary sensors that can recalculate historical outcomes on current observation configuration. Bayesian Studio runs as a local HA Supervisor add-on with ingress.

## The problem

Bayesian sensors should be incredibly useful in Home Assistant for non-deterministic outcomes based on multiple entities (fuzzy logic) but in practice are rarely used for two reasons:
1. A sensor requires foundation parameters that are then modulated by multiple observations. The values to set for the parameters are not obvious and determining starting values generally requires inspecting historical entity trends which is very awkward within the HA UI.
2. Sensors calculate a probability based on observations and trigger at a threshold. Within HA it is only possible to calculate the current probability and record that going forward. Days must pass to collect new data by which time the goal has been forgotten. The iteration cycle is just too long to be viable.

## The solution

Bayesian studio allows the observations and parameters to be freely explored and restrospectively calculates and displays the probability timeline so a user can see how that correlates with how the entities changed and ultimately what result was expected.

Bayesian Studio gives an overview for all the bayesian sensors in an HA instance and supports modification and tuning of both old-school sensors defined in YAML and more recently supported JSON sensors created in the UI.

## Features

- **Overview page** — sensor health table with observation coverage, fire frequency, prior, threshold, and config source. Dynamic time window adapts to system performance (targets 8-second page load).
- **Studio page** — per-sensor tuning with interactive probability chart, observation sliders, and save-to-YAML with auto-backfill.
- **Simulated sensors** - The state of critical sensors such as time() or sun() are often not stored in the history DB so dependant observations cannot be recreated. Bayesian Studio uses TimeZone, Lat and Long settings from HA to simulate historical data.
- **HA template support** — Bayesian Studio can eveluate Jinja2 templates and will also evaluate many HA extensions such as `states()`, `state_attr()`, `is_state()`, `has_value()`, `now()`, `utcnow()`, `today_at()`, `as_timestamp()`, `as_local()`, `timedelta()`, `float()`, `int()`, `bool()`, `is_number()`, `iif()`, and dotted `states.domain.name` access.
- **Adaptive synthetic timestamps** — time-dependent template observations (sun elevation, `now()` comparisons) are re-evaluated at appropriate intervals: every 40s (last 24h), 5min (last 7d), 15min (older).
- **History backfill** - Bayesian Studio uses the [Bayesian Backfill](https://github.com/maxlyth/homeassistant-bayesian-backfill) project to not only simulate the recent sensor history for exploratory purposes but can also recalculate the entire state history for a modifed sensor.

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

## Stack

- [Streamlit](https://streamlit.io/) behind HA ingress (port 8501)
- [s6-overlay](https://github.com/just-containers/s6-overlay) for process supervision
- SQLAlchemy + SQLite for HA recorder database access
- ruamel.yaml for round-trip YAML editing with comment preservation

## License

[MIT](LICENSE)
