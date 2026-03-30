"""Unit tests for bayesian_studio.engine.config_writer."""
import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml as pyyaml

from bayesian_studio.engine.config_writer import (
    _find_sensor,
    compute_change_summary,
    generate_yaml_snippet,
    reload_bayesian_integration,
    save_yaml_config,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_OBS_ORIG = [
    {
        "platform": "state",
        "entity_id": "binary_sensor.motion",
        "to_state": "on",
        "prob_given_true": 0.9,
        "prob_given_false": 0.2,
    },
    {
        "platform": "numeric_state",
        "entity_id": "sensor.temp",
        "above": 20.0,
        "prob_given_true": 0.8,
        "prob_given_false": 0.3,
    },
]

_WORKING = {
    "prior": 0.5,
    "threshold": 0.5,
    "observations": [dict(o) for o in _OBS_ORIG],
}

_YAML_SINGLE = """\
# Header comment
- name: Test sensor
  unique_id: test_sensor
  platform: bayesian
  prior: 0.5
  probability_threshold: 0.5
  observations:
    - platform: state
      entity_id: binary_sensor.motion
      to_state: "on"
      prob_given_true: 0.9
      prob_given_false: 0.2
    - platform: numeric_state
      entity_id: sensor.temp
      above: 20.0
      prob_given_true: 0.8
      prob_given_false: 0.3
"""

_YAML_TWO_SENSORS = """\
- name: Sensor A
  unique_id: sensor_a
  platform: bayesian
  prior: 0.5
  probability_threshold: 0.5
  observations:
    - platform: state
      entity_id: binary_sensor.x
      to_state: "on"
      prob_given_true: 0.9
      prob_given_false: 0.2

- name: Sensor B
  unique_id: sensor_b
  platform: bayesian
  prior: 0.4
  probability_threshold: 0.6
  observations:
    - platform: state
      entity_id: binary_sensor.y
      to_state: "on"
      prob_given_true: 0.7
      prob_given_false: 0.1
"""

_YAML_DICT_FORMAT = """\
binary_sensor:
  - name: Test sensor
    unique_id: test_sensor
    platform: bayesian
    prior: 0.5
    probability_threshold: 0.5
    observations:
      - platform: state
        entity_id: binary_sensor.motion
        to_state: "on"
        prob_given_true: 0.9
        prob_given_false: 0.2
"""


# ---------------------------------------------------------------------------
# compute_change_summary
# ---------------------------------------------------------------------------

def test_change_summary_no_changes():
    import copy
    w = {"prior": 0.5, "threshold": 0.5, "observations": copy.deepcopy(_OBS_ORIG)}
    assert compute_change_summary(w, _OBS_ORIG, 0.5, 0.5) == []


def test_change_summary_prior_changed():
    import copy
    w = {"prior": 0.7, "threshold": 0.5, "observations": copy.deepcopy(_OBS_ORIG)}
    changes = compute_change_summary(w, _OBS_ORIG, 0.5, 0.5)
    assert len(changes) == 1
    assert changes[0] == {"field": "prior", "old": 0.5, "new": 0.7}


def test_change_summary_threshold_changed():
    import copy
    w = {"prior": 0.5, "threshold": 0.8, "observations": copy.deepcopy(_OBS_ORIG)}
    changes = compute_change_summary(w, _OBS_ORIG, 0.5, 0.5)
    assert any(c["field"] == "probability_threshold" for c in changes)


def test_change_summary_obs_prob_changed():
    import copy
    obs = copy.deepcopy(_OBS_ORIG)
    obs[0]["prob_given_true"] = 0.95
    w = {"prior": 0.5, "threshold": 0.5, "observations": obs}
    changes = compute_change_summary(w, _OBS_ORIG, 0.5, 0.5)
    assert len(changes) == 1
    assert "prob_given_true" in changes[0]["field"]
    assert changes[0]["old"] == pytest.approx(0.9)
    assert changes[0]["new"] == pytest.approx(0.95)


def test_change_summary_multiple_fields():
    import copy
    obs = copy.deepcopy(_OBS_ORIG)
    obs[1]["prob_given_false"] = 0.05
    w = {"prior": 0.6, "threshold": 0.5, "observations": obs}
    changes = compute_change_summary(w, _OBS_ORIG, 0.5, 0.5)
    assert len(changes) == 2
    fields = {c["field"] for c in changes}
    assert "prior" in fields
    assert any("prob_given_false" in f for f in fields)


# ---------------------------------------------------------------------------
# save_yaml_config — list format
# ---------------------------------------------------------------------------

def test_save_yaml_single_sensor(tmp_path):
    f = tmp_path / "bayesian.yaml"
    f.write_text(_YAML_SINGLE)

    import copy
    obs = copy.deepcopy(_OBS_ORIG)
    obs[0]["prob_given_true"] = 0.95
    working = {"prior": 0.6, "threshold": 0.7, "observations": obs}

    save_yaml_config(str(f), "test_sensor", working)

    result = pyyaml.safe_load(f.read_text())
    sensor = result[0]
    assert sensor["prior"] == pytest.approx(0.6)
    assert sensor["probability_threshold"] == pytest.approx(0.7)
    assert sensor["observations"][0]["prob_given_true"] == pytest.approx(0.95)
    assert sensor["observations"][0]["prob_given_false"] == pytest.approx(0.2)  # unchanged
    assert sensor["observations"][1]["prob_given_true"] == pytest.approx(0.8)   # unchanged


def test_save_yaml_preserves_comments(tmp_path):
    f = tmp_path / "bayesian.yaml"
    f.write_text(_YAML_SINGLE)

    import copy
    working = {"prior": 0.6, "threshold": 0.5, "observations": copy.deepcopy(_OBS_ORIG)}
    save_yaml_config(str(f), "test_sensor", working)

    raw = f.read_text()
    assert "# Header comment" in raw


def test_save_yaml_multi_sensor_only_touches_target(tmp_path):
    f = tmp_path / "bayesian.yaml"
    f.write_text(_YAML_TWO_SENSORS)

    import copy
    obs = [{"platform": "state", "entity_id": "binary_sensor.x", "to_state": "on",
            "prob_given_true": 0.99, "prob_given_false": 0.01}]
    working = {"prior": 0.9, "threshold": 0.8, "observations": obs}
    save_yaml_config(str(f), "sensor_a", working)

    result = pyyaml.safe_load(f.read_text())
    sensor_a = next(s for s in result if s["unique_id"] == "sensor_a")
    sensor_b = next(s for s in result if s["unique_id"] == "sensor_b")

    assert sensor_a["prior"] == pytest.approx(0.9)
    assert sensor_a["observations"][0]["prob_given_true"] == pytest.approx(0.99)
    # Sensor B untouched
    assert sensor_b["prior"] == pytest.approx(0.4)
    assert sensor_b["observations"][0]["prob_given_true"] == pytest.approx(0.7)


def test_save_yaml_dict_format(tmp_path):
    f = tmp_path / "bayesian.yaml"
    f.write_text(_YAML_DICT_FORMAT)

    import copy
    obs = [{"platform": "state", "entity_id": "binary_sensor.motion",
            "to_state": "on", "prob_given_true": 0.85, "prob_given_false": 0.15}]
    working = {"prior": 0.55, "threshold": 0.6, "observations": obs}
    save_yaml_config(str(f), "test_sensor", working)

    result = pyyaml.safe_load(f.read_text())
    sensor = result["binary_sensor"][0]
    assert sensor["prior"] == pytest.approx(0.55)
    assert sensor["observations"][0]["prob_given_true"] == pytest.approx(0.85)


def test_save_yaml_not_found_raises(tmp_path):
    f = tmp_path / "bayesian.yaml"
    f.write_text(_YAML_SINGLE)
    import copy
    working = {"prior": 0.5, "threshold": 0.5, "observations": copy.deepcopy(_OBS_ORIG)}
    with pytest.raises(ValueError, match="not found"):
        save_yaml_config(str(f), "nonexistent_id", working)


# ---------------------------------------------------------------------------
# _find_sensor
# ---------------------------------------------------------------------------

def test_find_sensor_list_format():
    data = pyyaml.safe_load(_YAML_SINGLE)
    sensor = _find_sensor(data, "test_sensor")
    assert sensor is not None
    assert sensor["name"] == "Test sensor"


def test_find_sensor_dict_format():
    data = pyyaml.safe_load(_YAML_DICT_FORMAT)
    sensor = _find_sensor(data, "test_sensor")
    assert sensor is not None


def test_find_sensor_missing_returns_none():
    data = pyyaml.safe_load(_YAML_SINGLE)
    assert _find_sensor(data, "no_such_id") is None


# ---------------------------------------------------------------------------
# reload_bayesian_integration
# ---------------------------------------------------------------------------

def test_reload_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("bayesian_studio.engine.config_writer.requests.post", return_value=mock_resp) as mock_post:
        with patch.dict("os.environ", {"SUPERVISOR_TOKEN": "test-token"}):
            assert reload_bayesian_integration() is True
    called_url = mock_post.call_args[0][0]
    assert "homeassistant/reload_all" in called_url


def test_reload_failure_http_error():
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    with patch("bayesian_studio.engine.config_writer.requests.post", return_value=mock_resp):
        with patch.dict("os.environ", {"SUPERVISOR_TOKEN": "test-token"}):
            assert reload_bayesian_integration() is False


def test_reload_failure_exception():
    with patch("bayesian_studio.engine.config_writer.requests.post", side_effect=Exception("timeout")):
        with patch.dict("os.environ", {"SUPERVISOR_TOKEN": "test-token"}):
            assert reload_bayesian_integration() is False


def test_reload_no_token():
    with patch.dict("os.environ", {}, clear=True):
        # Ensure SUPERVISOR_TOKEN is absent
        import os
        os.environ.pop("SUPERVISOR_TOKEN", None)
        assert reload_bayesian_integration() is False


# ---------------------------------------------------------------------------
# generate_yaml_snippet
# ---------------------------------------------------------------------------

def test_generate_snippet_is_valid_yaml():
    import copy
    working = {"prior": 0.6, "threshold": 0.7, "observations": copy.deepcopy(_OBS_ORIG)}
    snippet = generate_yaml_snippet(working)
    parsed = pyyaml.safe_load(snippet)
    assert parsed["platform"] == "bayesian"
    assert parsed["prior"] == pytest.approx(0.6)
    assert parsed["probability_threshold"] == pytest.approx(0.7)
    assert len(parsed["observations"]) == 2


def test_generate_snippet_contains_all_obs_fields():
    import copy
    working = {"prior": 0.5, "threshold": 0.5, "observations": copy.deepcopy(_OBS_ORIG)}
    snippet = generate_yaml_snippet(working)
    assert "prob_given_true" in snippet
    assert "prob_given_false" in snippet
    assert "binary_sensor.motion" in snippet


# ---------------------------------------------------------------------------
# compute_change_summary — add/remove observations
# ---------------------------------------------------------------------------

def test_change_summary_new_observation():
    import copy
    extra_obs = {"platform": "state", "entity_id": "binary_sensor.door",
                 "to_state": "on", "prob_given_true": 0.8, "prob_given_false": 0.1}
    w = {"prior": 0.5, "threshold": 0.5, "observations": copy.deepcopy(_OBS_ORIG) + [extra_obs]}
    changes = compute_change_summary(w, _OBS_ORIG, 0.5, 0.5)
    new_changes = [c for c in changes if "NEW" in c["field"]]
    assert len(new_changes) == 1
    assert new_changes[0]["old"] is None
    assert "binary_sensor.door" in str(new_changes[0]["new"])


def test_change_summary_removed_observation():
    import copy
    w = {"prior": 0.5, "threshold": 0.5, "observations": copy.deepcopy(_OBS_ORIG[:1])}
    changes = compute_change_summary(w, _OBS_ORIG, 0.5, 0.5)
    removed = [c for c in changes if "REMOVED" in c["field"]]
    assert len(removed) == 1
    assert removed[0]["new"] is None
    assert "sensor.temp" in str(removed[0]["old"])


# ---------------------------------------------------------------------------
# save_yaml_config — add/remove observations
# ---------------------------------------------------------------------------

def test_save_yaml_adds_observation(tmp_path):
    f = tmp_path / "bayesian.yaml"
    f.write_text(_YAML_SINGLE)

    import copy
    new_obs = {"platform": "state", "entity_id": "binary_sensor.door",
               "to_state": "open", "prob_given_true": 0.7, "prob_given_false": 0.05}
    working = {"prior": 0.5, "threshold": 0.5,
               "observations": copy.deepcopy(_OBS_ORIG) + [new_obs]}

    save_yaml_config(str(f), "test_sensor", working)

    result = pyyaml.safe_load(f.read_text())
    obs = result[0]["observations"]
    assert len(obs) == 3
    assert obs[2]["entity_id"] == "binary_sensor.door"
    assert obs[2]["to_state"] == "open"


def test_save_yaml_removes_observation(tmp_path):
    f = tmp_path / "bayesian.yaml"
    f.write_text(_YAML_SINGLE)

    import copy
    working = {"prior": 0.5, "threshold": 0.5,
               "observations": copy.deepcopy(_OBS_ORIG[:1])}  # keep only first

    save_yaml_config(str(f), "test_sensor", working)

    result = pyyaml.safe_load(f.read_text())
    obs = result[0]["observations"]
    assert len(obs) == 1
    assert obs[0]["entity_id"] == "binary_sensor.motion"


def test_save_yaml_add_then_remove_roundtrip(tmp_path):
    """Add an obs, save, remove it, save again — end state = original."""
    f = tmp_path / "bayesian.yaml"
    f.write_text(_YAML_SINGLE)

    import copy
    extra = {"platform": "state", "entity_id": "binary_sensor.window",
             "to_state": "open", "prob_given_true": 0.6, "prob_given_false": 0.05}

    # Add
    working = {"prior": 0.5, "threshold": 0.5,
               "observations": copy.deepcopy(_OBS_ORIG) + [extra]}
    save_yaml_config(str(f), "test_sensor", working)
    assert len(pyyaml.safe_load(f.read_text())[0]["observations"]) == 3

    # Remove
    working2 = {"prior": 0.5, "threshold": 0.5,
                "observations": copy.deepcopy(_OBS_ORIG)}
    save_yaml_config(str(f), "test_sensor", working2)
    result = pyyaml.safe_load(f.read_text())[0]["observations"]
    assert len(result) == 2
    assert result[0]["entity_id"] == "binary_sensor.motion"
