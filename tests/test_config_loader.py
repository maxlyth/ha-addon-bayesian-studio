"""Tests for bayesian_studio.engine.config_loader."""
import json
import os

import pytest

from bayesian_studio.engine.config_loader import (
    ConfigSource,
    extract_observation_names,
    get_bayesian_entity_ids,
    load_bayesian_config,
    load_location,
    load_timezone,
    search_entity_ids,
)


def _make_registry(tmp_path, entities):
    storage = tmp_path / ".storage"
    storage.mkdir(exist_ok=True)
    (storage / "core.entity_registry").write_text(json.dumps({
        "data": {"entities": entities}
    }))


def _make_bayesian_yaml(tmp_path, sensors):
    yaml_content = ""
    for s in sensors:
        yaml_content += f"- platform: bayesian\n"
        yaml_content += f"  unique_id: {s['unique_id']}\n"
        yaml_content += f"  prior: {s.get('prior', 0.5)}\n"
        yaml_content += f"  probability_threshold: {s.get('probability_threshold', 0.6)}\n"
        yaml_content += f"  observations: []\n"
    (tmp_path / "bayesian.yaml").write_text(yaml_content)


@pytest.fixture
def bayesian_dir(tmp_path):
    """Config dir with one YAML Bayesian sensor and entity registry."""
    _make_registry(tmp_path, [
        {
            "entity_id": "binary_sensor.test_sensor",
            "platform": "bayesian",
            "unique_id": "bayesian-test_sensor",
            "config_entry_id": None,
        }
    ])
    _make_bayesian_yaml(tmp_path, [
        {"unique_id": "test_sensor", "prior": 0.5, "probability_threshold": 0.7}
    ])
    (tmp_path / ".storage" / "core.config").write_text(
        json.dumps({"data": {"latitude": 51.5, "longitude": -0.1, "time_zone": "Europe/London"}})
    )
    (tmp_path / "configuration.yaml").write_text("homeassistant:\n  name: Test\n")
    return str(tmp_path)


class TestLoadLocation:
    def test_returns_lat_lon(self, config_dir):
        lat, lon = load_location(config_dir)
        assert lat == 51.5
        assert lon == -0.1


class TestLoadTimezone:
    def test_returns_configured_timezone(self, bayesian_dir):
        tz = load_timezone(bayesian_dir)
        assert tz == "Europe/London"

    def test_defaults_to_utc_when_missing(self, config_dir):
        # config_dir fixture has time_zone set to "UTC"
        tz = load_timezone(config_dir)
        assert tz == "UTC"

    def test_defaults_to_utc_when_key_absent(self, tmp_path):
        storage = tmp_path / ".storage"
        storage.mkdir()
        (storage / "core.config").write_text(json.dumps({"data": {"latitude": 0.0}}))
        tz = load_timezone(str(tmp_path))
        assert tz == "UTC"


class TestGetBayesianEntityIds:
    def test_returns_matching_entity(self, bayesian_dir):
        ids = get_bayesian_entity_ids("binary_sensor.test_sensor", bayesian_dir)
        assert ids == ["binary_sensor.test_sensor"]

    def test_glob_pattern(self, bayesian_dir):
        ids = get_bayesian_entity_ids("binary_sensor.*", bayesian_dir)
        assert "binary_sensor.test_sensor" in ids

    def test_non_bayesian_entity_excluded(self, tmp_path):
        _make_registry(tmp_path, [
            {"entity_id": "sensor.other", "platform": "mqtt",
             "unique_id": "mqtt-other", "config_entry_id": None}
        ])
        (tmp_path / ".storage" / "core.config").write_text(
            json.dumps({"data": {"latitude": 0, "longitude": 0}})
        )
        ids = get_bayesian_entity_ids("sensor.*", str(tmp_path))
        assert ids == []

    def test_unknown_entity_returns_empty(self, bayesian_dir):
        ids = get_bayesian_entity_ids("binary_sensor.does_not_exist", bayesian_dir)
        assert ids == []


class TestLoadBayesianConfig:
    def test_returns_config_dict_and_source(self, bayesian_dir):
        config, source = load_bayesian_config("binary_sensor.test_sensor", bayesian_dir)
        assert "prior" in config
        assert isinstance(source, ConfigSource)

    def test_yaml_sensor_returns_yaml_source_kind(self, bayesian_dir):
        config, source = load_bayesian_config("binary_sensor.test_sensor", bayesian_dir)
        assert source.kind == "yaml"

    def test_yaml_source_has_file_path(self, bayesian_dir):
        config, source = load_bayesian_config("binary_sensor.test_sensor", bayesian_dir)
        assert source.file_path is not None
        assert source.file_path.endswith(".yaml")

    def test_yaml_source_file_path_exists(self, bayesian_dir):
        config, source = load_bayesian_config("binary_sensor.test_sensor", bayesian_dir)
        assert os.path.isfile(source.file_path)

    def test_raises_for_unknown_entity(self, bayesian_dir):
        with pytest.raises(ValueError, match="not found in entity registry"):
            load_bayesian_config("binary_sensor.nonexistent", bayesian_dir)


# ---------------------------------------------------------------------------
# search_entity_ids
# ---------------------------------------------------------------------------

def _make_rich_registry(tmp_path):
    storage = tmp_path / ".storage"
    storage.mkdir(exist_ok=True)
    entities = [
        {"entity_id": "binary_sensor.motion_hall", "platform": "bayesian"},
        {"entity_id": "binary_sensor.motion_kitchen", "platform": "binary_sensor"},
        {"entity_id": "sensor.temperature_living", "platform": "mqtt"},
        {"entity_id": "sensor.humidity_bedroom", "platform": "mqtt"},
        {"entity_id": "light.living_room", "platform": "zha"},
    ]
    (storage / "core.entity_registry").write_text(json.dumps({"data": {"entities": entities}}))
    return str(tmp_path)


class TestSearchEntityIds:
    def test_returns_matching_entities(self, tmp_path):
        cfg = _make_rich_registry(tmp_path)
        result = search_entity_ids("motion", cfg)
        assert "binary_sensor.motion_hall" in result
        assert "binary_sensor.motion_kitchen" in result

    def test_case_insensitive(self, tmp_path):
        cfg = _make_rich_registry(tmp_path)
        result = search_entity_ids("MOTION", cfg)
        assert len(result) == 2

    def test_empty_query_returns_empty(self, tmp_path):
        cfg = _make_rich_registry(tmp_path)
        assert search_entity_ids("", cfg) == []

    def test_no_match_returns_empty(self, tmp_path):
        cfg = _make_rich_registry(tmp_path)
        assert search_entity_ids("zzznomatch", cfg) == []

    def test_limit_respected(self, tmp_path):
        cfg = _make_rich_registry(tmp_path)
        result = search_entity_ids("sensor", cfg, limit=1)
        assert len(result) == 1

    def test_results_sorted(self, tmp_path):
        cfg = _make_rich_registry(tmp_path)
        result = search_entity_ids("sensor", cfg)
        assert result == sorted(result)

    def test_domain_prefix_match(self, tmp_path):
        cfg = _make_rich_registry(tmp_path)
        result = search_entity_ids("light.", cfg)
        assert result == ["light.living_room"]


# ---------------------------------------------------------------------------
# extract_observation_names
# ---------------------------------------------------------------------------

_YAML_WITH_COMMENTS = """\
- platform: bayesian
  unique_id: named_sensor
  prior: 0.5
  probability_threshold: 0.6
  observations:
    - platform: state  # Motion detected
      entity_id: binary_sensor.motion
      to_state: "on"
      prob_given_true: 0.9
      prob_given_false: 0.2
    - platform: numeric_state  # Humidity high
      entity_id: sensor.humidity
      above: 70
      prob_given_true: 0.8
      prob_given_false: 0.1
"""

_YAML_NO_COMMENTS = """\
- platform: bayesian
  unique_id: unnamed_sensor
  prior: 0.5
  probability_threshold: 0.6
  observations:
    - platform: state
      entity_id: binary_sensor.motion
      to_state: "on"
      prob_given_true: 0.9
      prob_given_false: 0.2
    - platform: numeric_state
      entity_id: sensor.humidity
      above: 70
      prob_given_true: 0.8
      prob_given_false: 0.1
"""

_YAML_MIXED_COMMENTS = """\
- platform: bayesian
  unique_id: mixed_sensor
  prior: 0.5
  probability_threshold: 0.6
  observations:
    - platform: state  # Has a name
      entity_id: binary_sensor.motion
      to_state: "on"
      prob_given_true: 0.9
      prob_given_false: 0.2
    - platform: numeric_state
      entity_id: sensor.humidity
      above: 70
      prob_given_true: 0.8
      prob_given_false: 0.1
"""


class TestExtractObservationNames:
    def test_extracts_names_from_comments(self, tmp_path):
        f = tmp_path / "bayesian.yaml"
        f.write_text(_YAML_WITH_COMMENTS)
        names = extract_observation_names(str(f), "named_sensor")
        assert names == ["Motion detected", "Humidity high"]

    def test_no_comments_returns_empty_strings(self, tmp_path):
        f = tmp_path / "bayesian.yaml"
        f.write_text(_YAML_NO_COMMENTS)
        names = extract_observation_names(str(f), "unnamed_sensor")
        assert names == ["", ""]

    def test_mixed_comments(self, tmp_path):
        f = tmp_path / "bayesian.yaml"
        f.write_text(_YAML_MIXED_COMMENTS)
        names = extract_observation_names(str(f), "mixed_sensor")
        assert names == ["Has a name", ""]

    def test_strips_hash_prefix_and_whitespace(self, tmp_path):
        yaml_content = (
            "- platform: bayesian\n"
            "  unique_id: strip_test\n"
            "  prior: 0.5\n"
            "  probability_threshold: 0.6\n"
            "  observations:\n"
            "    - platform: state  #   Spaces around  \n"
            "      entity_id: binary_sensor.x\n"
            "      prob_given_true: 0.9\n"
            "      prob_given_false: 0.2\n"
        )
        f = tmp_path / "bayesian.yaml"
        f.write_text(yaml_content)
        names = extract_observation_names(str(f), "strip_test")
        assert names == ["Spaces around"]

    def test_sensor_not_found_returns_empty_list(self, tmp_path):
        f = tmp_path / "bayesian.yaml"
        f.write_text(_YAML_WITH_COMMENTS)
        names = extract_observation_names(str(f), "nonexistent_sensor")
        assert names == []

    def test_file_not_found_returns_empty_list(self, tmp_path):
        names = extract_observation_names(str(tmp_path / "missing.yaml"), "any_sensor")
        assert names == []
