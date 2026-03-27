"""Tests for bayesian_studio.engine.config_loader."""
import json
import os

import pytest

from bayesian_studio.engine.config_loader import (
    ConfigSource,
    get_bayesian_entity_ids,
    load_bayesian_config,
    load_location,
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
        json.dumps({"data": {"latitude": 51.5, "longitude": -0.1}})
    )
    (tmp_path / "configuration.yaml").write_text("homeassistant:\n  name: Test\n")
    return str(tmp_path)


class TestLoadLocation:
    def test_returns_lat_lon(self, config_dir):
        lat, lon = load_location(config_dir)
        assert lat == 51.5
        assert lon == -0.1


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
