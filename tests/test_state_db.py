"""Tests for bayesian_studio.engine.state_db — ported from backfill."""
import pytest

from bayesian_studio.engine.database import get_engine, get_read_connection
from bayesian_studio.engine.state_db import get_attr_at, get_state_at, load_state_timelines
from tests.conftest import insert_states


def _make_engine(config_dir, states_db):
    return get_engine(config_dir)


class TestGetStateAt:
    def test_returns_none_for_empty_timeline(self):
        tl = {"ts": [], "state": [], "attrs": []}
        assert get_state_at(tl, 1000.0) is None

    def test_returns_none_for_none_timeline(self):
        assert get_state_at(None, 1000.0) is None

    def test_returns_state_at_exact_timestamp(self):
        tl = {"ts": [1000.0], "state": ["on"], "attrs": [None]}
        assert get_state_at(tl, 1000.0) == "on"

    def test_forward_fills_before_next_event(self):
        tl = {"ts": [1000.0, 2000.0], "state": ["on", "off"], "attrs": [None, None]}
        assert get_state_at(tl, 1500.0) == "on"

    def test_returns_none_before_first_event(self):
        tl = {"ts": [1000.0], "state": ["on"], "attrs": [None]}
        assert get_state_at(tl, 999.0) is None

    def test_returns_last_state_after_final_event(self):
        tl = {"ts": [1000.0, 2000.0], "state": ["on", "off"], "attrs": [None, None]}
        assert get_state_at(tl, 9999.0) == "off"


class TestGetAttrAt:
    def test_returns_none_for_empty_timeline(self):
        tl = {"ts": [], "state": [], "attrs": []}
        assert get_attr_at(tl, 1000.0, "brightness") is None

    def test_returns_attribute_value(self):
        import json
        tl = {"ts": [1000.0], "state": ["on"], "attrs": [json.dumps({"brightness": 128})]}
        assert get_attr_at(tl, 1000.0, "brightness") == 128

    def test_returns_none_for_missing_key(self):
        import json
        tl = {"ts": [1000.0], "state": ["on"], "attrs": [json.dumps({"other": 1})]}
        assert get_attr_at(tl, 1000.0, "brightness") is None

    def test_returns_none_for_invalid_json(self):
        tl = {"ts": [1000.0], "state": ["on"], "attrs": ["not-json"]}
        assert get_attr_at(tl, 1000.0, "brightness") is None


class TestLoadStateTimelines:
    def test_returns_empty_for_unknown_entity(self, config_dir, states_db):
        engine = _make_engine(config_dir, states_db)
        with get_read_connection(engine) as conn:
            result = load_state_timelines(
                ["binary_sensor.unknown"], 0.0, 9999.0, False, conn
            )
        assert result == {}

    def test_loads_known_entity(self, config_dir, states_db):
        insert_states(states_db, "sensor.foo", [(1000.0, "on"), (2000.0, "off")])
        engine = _make_engine(config_dir, states_db)
        with get_read_connection(engine) as conn:
            result = load_state_timelines(["sensor.foo"], 0.0, 9999.0, False, conn)
        assert "sensor.foo" in result
        assert result["sensor.foo"]["state"] == ["on", "off"]

    def test_timestamps_sorted_ascending(self, config_dir, states_db):
        insert_states(states_db, "sensor.foo", [(2000.0, "off"), (1000.0, "on")])
        engine = _make_engine(config_dir, states_db)
        with get_read_connection(engine) as conn:
            result = load_state_timelines(["sensor.foo"], 0.0, 9999.0, False, conn)
        ts = result["sensor.foo"]["ts"]
        assert ts == sorted(ts)

    def test_1day_lookback_seeds_forward_fill(self, config_dir, states_db):
        # Row at ts=500 is before start_ts=900 but within 1-day lookback
        insert_states(states_db, "sensor.foo", [(500.0, "on")])
        engine = _make_engine(config_dir, states_db)
        with get_read_connection(engine) as conn:
            result = load_state_timelines(["sensor.foo"], 900.0, 9999.0, False, conn)
        # Should be included due to lookback
        assert "sensor.foo" in result
        assert 500.0 in result["sensor.foo"]["ts"]

    def test_attrs_none_when_load_attrs_false(self, config_dir, states_db):
        insert_states(states_db, "sensor.foo", [(1000.0, "on")])
        engine = _make_engine(config_dir, states_db)
        with get_read_connection(engine) as conn:
            result = load_state_timelines(["sensor.foo"], 0.0, 9999.0, False, conn)
        assert all(a is None for a in result["sensor.foo"]["attrs"])

    def test_multiple_entities_loaded(self, config_dir, states_db):
        insert_states(states_db, "sensor.a", [(1000.0, "on")])
        insert_states(states_db, "sensor.b", [(1000.0, "off")])
        engine = _make_engine(config_dir, states_db)
        with get_read_connection(engine) as conn:
            result = load_state_timelines(
                ["sensor.a", "sensor.b"], 0.0, 9999.0, False, conn
            )
        assert "sensor.a" in result and "sensor.b" in result
