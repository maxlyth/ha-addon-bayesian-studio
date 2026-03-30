"""AppTest smoke tests for the Studio page (bayesian_details.py).

Tests verify the page renders without errors, key widgets are present, and
widget keys are unique across all observations. All database and HA config
access is patched at the engine layer.

See test_ui_overview.py for notes on the patching strategy.
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
    / "bayesian_details.py"
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
    "sensor.temperature": {
        "ts": [_now - 3600, _now - 1800, _now - 600],
        "state": ["18.5", "22.3", "19.1"],
        "attrs": [None, None, None],
    },
}

_TRACE = {
    "rows": [
        {
            "ts": _now - 3600,
            "probability": 0.5,
            "state": "off",
            "obs_results": [False, False],
        },
        {
            "ts": _now - 1800,
            "probability": 0.85,
            "state": "on",
            "obs_results": [True, True],
        },
        {
            "ts": _now - 600,
            "probability": 0.3,
            "state": "off",
            "obs_results": [False, False],
        },
    ],
    "warnings": [],
    "computation_seconds": 0.01,
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
            {
                "platform": "numeric_state",
                "entity_id": "sensor.temperature",
                "above": 20.0,
                "prob_given_true": 0.8,
                "prob_given_false": 0.3,
            },
        ],
    }
    return config, ConfigSource(kind="yaml", file_path="/config/test.yaml")


def _run_studio(sensor_id="binary_sensor.test_sensor_a"):
    config, source = _mock_config()
    with (
        patch(
            "bayesian_studio.engine.config_loader.get_bayesian_entity_ids",
            return_value=_SENSOR_IDS,
        ),
        patch(
            "bayesian_studio.engine.config_loader.load_bayesian_config",
            return_value=(config, source),
        ),
        patch(
            "bayesian_studio.engine.config_loader.load_location",
            return_value=[51.0, -1.0],
        ),
        patch("bayesian_studio.engine.config_loader.load_timezone", return_value="UTC"),
        patch("bayesian_studio.engine.database.get_engine", return_value=MagicMock()),
        patch("bayesian_studio.engine.database.get_read_connection"),
        patch(
            "bayesian_studio.engine.state_db.load_state_timelines",
            return_value=_TIMELINES,
        ),
        patch(
            "bayesian_studio.engine.bayes.compute_probability_trace",
            return_value=_TRACE,
        ),
    ):
        # Clear cached results so each test gets fresh data from the active mocks.
        st.cache_data.clear()
        st.cache_resource.clear()
        at = AppTest.from_file(_PAGE, default_timeout=15)
        at.session_state["_nav_sensor"] = sensor_id
        at.session_state["_current_sensor"] = sensor_id
        at.run()
    return at


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_studio_renders_without_error():
    at = _run_studio()
    assert not at.exception, f"Page raised: {at.exception}"


def test_studio_prior_and_threshold_sliders_present():
    at = _run_studio()
    assert not at.exception
    labels = [s.label for s in at.slider]
    assert "Prior" in labels, f"Prior slider missing. Sliders: {labels}"
    assert "Threshold" in labels, f"Threshold slider missing. Sliders: {labels}"


def test_studio_observation_prob_sliders_present():
    at = _run_studio()
    assert not at.exception
    labels = [s.label for s in at.slider]
    pgt_count = sum(1 for l in labels if l == "prob_given_true")
    pgf_count = sum(1 for l in labels if l == "prob_given_false")
    # 2 from observations + 1 from the "Add observation" form
    assert pgt_count >= 2, f"Expected at least 2 prob_given_true sliders, got {pgt_count}"
    assert pgf_count >= 2, f"Expected at least 2 prob_given_false sliders, got {pgf_count}"


def test_studio_period_selector_has_five_options():
    at = _run_studio()
    assert not at.exception
    period_radios = [r for r in at.radio if "period" in r.key]
    assert period_radios, "No time period radio widget found"
    assert len(period_radios[0].options) == 5, (
        f"Expected 5 period options (1h/1d/1w/1m/Custom), "
        f"got {period_radios[0].options}"
    )


def test_studio_observations_summary_caption():
    at = _run_studio()
    assert not at.exception
    captions = [c.value for c in at.caption]
    assert any("2 observation" in c for c in captions), (
        f"Expected '2 observations' caption. Got: {captions}"
    )


def test_studio_observation_sliders_render_directly():
    """Observation prob sliders render directly (no expander wrapper)."""
    at = _run_studio()
    assert not at.exception
    # No "Details" expanders — content renders inline
    details = [e for e in at.expander if e.label == "Details"]
    assert len(details) == 0, (
        f"Expected 0 Details expanders (removed), got {len(details)}"
    )
    # Sliders still present (2 from observations + 1 from add form)
    labels = [s.label for s in at.slider]
    pgt_count = sum(1 for l in labels if l == "prob_given_true")
    assert pgt_count >= 2, f"Expected at least 2 prob_given_true sliders, got {pgt_count}"


def test_studio_reset_button_present():
    at = _run_studio()
    assert not at.exception
    reset = [b for b in at.button if "Reset" in b.label]
    assert reset, "No 'Reset to original' button found"


def test_studio_widget_keys_unique():
    """Regression: duplicate keys crash Streamlit when observations share
    the same index variable or sensor ID scope is incorrect."""
    at = _run_studio()
    assert not at.exception, (
        "Duplicate widget key or other error — check observation index scoping"
    )


def test_studio_save_button_hidden_when_clean():
    """No save button when working config matches the original."""
    at = _run_studio()
    assert not at.exception
    save_buttons = [b for b in at.button if "Save" in b.label]
    assert not save_buttons, f"Save button should not appear when config is unchanged; got {[b.label for b in save_buttons]}"


def test_studio_save_button_visible_when_dirty():
    """Save button appears when the working config has been modified."""
    import copy
    sensor_id = "binary_sensor.test_sensor_a"
    config, source = _mock_config()
    dirty_working = {
        "prior": 0.9,  # changed from 0.5
        "threshold": 0.5,
        "observations": copy.deepcopy(config["observations"]),
    }
    with (
        patch(
            "bayesian_studio.engine.config_loader.get_bayesian_entity_ids",
            return_value=_SENSOR_IDS,
        ),
        patch(
            "bayesian_studio.engine.config_loader.load_bayesian_config",
            return_value=(config, source),
        ),
        patch(
            "bayesian_studio.engine.config_loader.load_location",
            return_value=[51.0, -1.0],
        ),
        patch("bayesian_studio.engine.config_loader.load_timezone", return_value="UTC"),
        patch("bayesian_studio.engine.database.get_engine", return_value=MagicMock()),
        patch("bayesian_studio.engine.database.get_read_connection"),
        patch(
            "bayesian_studio.engine.state_db.load_state_timelines",
            return_value=_TIMELINES,
        ),
        patch(
            "bayesian_studio.engine.bayes.compute_probability_trace",
            return_value=_TRACE,
        ),
    ):
        st.cache_data.clear()
        st.cache_resource.clear()
        at = AppTest.from_file(_PAGE, default_timeout=15)
        at.session_state["_nav_sensor"] = sensor_id
        at.session_state["_current_sensor"] = sensor_id
        at.session_state[f"working_config_{sensor_id}"] = dirty_working
        at.run()

    assert not at.exception
    save_buttons = [b for b in at.button if "Save" in b.label]
    assert save_buttons, "Expected a Save button when config is dirty"


def test_studio_ui_sensor_shows_snippet_not_save_button():
    """UI-sourced sensors get a YAML snippet, not a Save button."""
    import copy
    from bayesian_studio.engine.config_loader import ConfigSource
    sensor_id = "binary_sensor.test_sensor_a"
    config, _ = _mock_config()
    ui_source = ConfigSource(kind="ui")
    dirty_working = {
        "prior": 0.9,
        "threshold": 0.5,
        "observations": copy.deepcopy(config["observations"]),
    }
    with (
        patch(
            "bayesian_studio.engine.config_loader.get_bayesian_entity_ids",
            return_value=_SENSOR_IDS,
        ),
        patch(
            "bayesian_studio.engine.config_loader.load_bayesian_config",
            return_value=(config, ui_source),
        ),
        patch(
            "bayesian_studio.engine.config_loader.load_location",
            return_value=[51.0, -1.0],
        ),
        patch("bayesian_studio.engine.config_loader.load_timezone", return_value="UTC"),
        patch("bayesian_studio.engine.database.get_engine", return_value=MagicMock()),
        patch("bayesian_studio.engine.database.get_read_connection"),
        patch(
            "bayesian_studio.engine.state_db.load_state_timelines",
            return_value=_TIMELINES,
        ),
        patch(
            "bayesian_studio.engine.bayes.compute_probability_trace",
            return_value=_TRACE,
        ),
    ):
        st.cache_data.clear()
        st.cache_resource.clear()
        at = AppTest.from_file(_PAGE, default_timeout=15)
        at.session_state["_nav_sensor"] = sensor_id
        at.session_state["_current_sensor"] = sensor_id
        at.session_state[f"working_config_{sensor_id}"] = dirty_working
        at.run()

    assert not at.exception
    save_buttons = [b for b in at.button if "Save to YAML" in b.label]
    assert not save_buttons, "UI sensors should not have a Save to YAML button"
    # Code block from generate_yaml_snippet should be present
    code_blocks = at.code
    assert code_blocks, "Expected a YAML snippet code block for UI sensor"


# ---------------------------------------------------------------------------
# Observation friendly names
# ---------------------------------------------------------------------------


def _run_studio_with_names(names, sensor_id="binary_sensor.test_sensor_a"):
    """Run studio page with obs names pre-populated in working config."""
    config, source = _mock_config()
    obs = config["observations"]
    working_with_names = {
        "observations": obs[:],
        "prior": config["prior"],
        "threshold": config["probability_threshold"],
        "_obs_names": list(names),
        "_orig_obs_names": list(names),
    }
    with (
        patch(
            "bayesian_studio.engine.config_loader.get_bayesian_entity_ids",
            return_value=_SENSOR_IDS,
        ),
        patch(
            "bayesian_studio.engine.config_loader.load_bayesian_config",
            return_value=(config, source),
        ),
        patch(
            "bayesian_studio.engine.config_loader.load_location",
            return_value=[51.0, -1.0],
        ),
        patch("bayesian_studio.engine.config_loader.load_timezone", return_value="UTC"),
        patch("bayesian_studio.engine.database.get_engine", return_value=MagicMock()),
        patch("bayesian_studio.engine.database.get_read_connection"),
        patch(
            "bayesian_studio.engine.state_db.load_state_timelines",
            return_value=_TIMELINES,
        ),
        patch(
            "bayesian_studio.engine.bayes.compute_probability_trace",
            return_value=_TRACE,
        ),
        patch(
            "bayesian_studio.pages.bayesian_details._get_obs_names",
            return_value=list(names),
        ),
    ):
        st.cache_data.clear()
        st.cache_resource.clear()
        at = AppTest.from_file(_PAGE, default_timeout=15)
        at.session_state["_nav_sensor"] = sensor_id
        at.session_state["_current_sensor"] = sensor_id
        at.session_state[f"working_config_{sensor_id}"] = working_with_names
        at.run()
    return at


def test_studio_shows_friendly_name_in_header():
    """When obs has a name, the name appears in bold in the markdown header."""
    at = _run_studio_with_names(["Motion in hall", ""])
    assert not at.exception
    md_texts = [m.value for m in at.markdown]
    assert any("Motion in hall" in t for t in md_texts), (
        f"Name not found in any markdown. Texts: {md_texts}"
    )


def test_studio_name_input_fields_present_for_yaml_sensor():
    """YAML sensors show a text_input for each observation name."""
    at = _run_studio_with_names(["", ""])
    assert not at.exception
    # Should have name inputs (label_visibility=collapsed means label is "Name")
    name_inputs = [ti for ti in at.text_input if ti.label == "Name"]
    assert len(name_inputs) == 2, (
        f"Expected 2 name inputs, got {len(name_inputs)}"
    )


def test_studio_name_edit_marks_dirty():
    """Editing an obs name makes the config dirty (Reset button enabled)."""
    at = _run_studio_with_names(["", ""])
    assert not at.exception

    # Find a name input and set a value
    name_inputs = [ti for ti in at.text_input if ti.label == "Name"]
    assert name_inputs
    name_inputs[0].set_value("My new name").run()

    assert not at.exception
    reset_buttons = [b for b in at.button if "Reset" in b.label]
    assert reset_buttons
    assert not reset_buttons[0].disabled, "Reset button should be enabled after name edit"
