"""AppTest smoke tests for the Overview page (overview.py).

These tests verify structural correctness — the page renders without errors,
sensor rows appear with tune buttons, and sort controls work. All database
and HA config access is patched at the engine layer.
"""
import pathlib
import time
from unittest.mock import MagicMock, patch

import streamlit as st
from streamlit.testing.v1 import AppTest

# ---------------------------------------------------------------------------
# Page path
# ---------------------------------------------------------------------------

_PAGE = str(
    pathlib.Path(__file__).parent.parent
    / "bayesian-studio"
    / "bayesian_studio"
    / "pages"
    / "overview.py"
)

# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------

_SENSOR_IDS = [
    "binary_sensor.test_sensor_a",
    "binary_sensor.test_sensor_b",
]

_now = time.time()

_TIMELINES = {
    "binary_sensor.motion": {
        "ts": [_now - 3600, _now - 1800, _now - 600],
        "state": ["off", "on", "off"],
        "attrs": [None, None, None],
    },
    "binary_sensor.test_sensor_a": {
        "ts": [_now - 3600, _now - 600],
        "state": ["off", "on"],
        "attrs": [None, None],
    },
    "binary_sensor.test_sensor_b": {
        "ts": [_now - 3600, _now - 600],
        "state": ["off", "off"],
        "attrs": [None, None],
    },
}


def _mock_config():
    from bayesian_studio.engine.config_loader import ConfigSource
    config = {
        "prior": 0.5,
        "probability_threshold": 0.5,
        "observations": [
            {
                "platform": "state",
                "entity_id": "binary_sensor.motion",
                "to_state": "on",
                "prob_given_true": 0.9,
                "prob_given_false": 0.2,
            },
        ],
    }
    return config, ConfigSource(kind="yaml", file_path="/config/test.yaml")


def _run_overview(sensor_ids=None):
    if sensor_ids is None:
        sensor_ids = _SENSOR_IDS
    config, source = _mock_config()
    with (
        patch(
            "bayesian_studio.engine.config_loader.get_bayesian_entity_ids",
            return_value=sensor_ids,
        ),
        patch(
            "bayesian_studio.engine.config_loader.load_bayesian_config",
            return_value=(config, source),
        ),
        patch("bayesian_studio.engine.config_loader.load_timezone", return_value="UTC"),
        patch("bayesian_studio.engine.database.get_engine", return_value=MagicMock()),
        patch("bayesian_studio.engine.database.get_read_connection"),
        patch(
            "bayesian_studio.engine.state_db.load_state_timelines",
            return_value=_TIMELINES,
        ),
    ):
        # Clear cached results so each test gets fresh data from the active mocks.
        st.cache_data.clear()
        st.cache_resource.clear()
        at = AppTest.from_file(_PAGE, default_timeout=15)
        at.run()
    return at


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_overview_renders_without_error():
    at = _run_overview()
    assert not at.exception, f"Page raised: {at.exception}"


def test_overview_shows_one_tune_button_per_sensor():
    at = _run_overview()
    assert not at.exception
    tune_buttons = [b for b in at.button if b.label == "🔧"]
    assert len(tune_buttons) == len(_SENSOR_IDS), (
        f"Expected {len(_SENSOR_IDS)} tune buttons, got {len(tune_buttons)}"
    )


def test_overview_tune_buttons_have_unique_keys():
    """Regression: duplicate keys crash Streamlit."""
    at = _run_overview()
    assert not at.exception, (
        "Duplicate widget key detected — ensure each tune button uses unique key"
    )


def test_overview_sort_headers_present():
    """Sortable columns have button headers."""
    at = _run_overview()
    assert not at.exception
    sort_buttons = [b for b in at.button if b.key and b.key.startswith("sort_")]
    assert len(sort_buttons) >= 4, (
        f"Expected at least 4 sort header buttons, got {len(sort_buttons)}"
    )


def test_overview_no_sensors_shows_error():
    at = _run_overview(sensor_ids=[])
    assert not at.exception, f"Page raised unexpectedly: {at.exception}"
    assert len(at.error) > 0, "Expected st.error() when no sensors are found"
