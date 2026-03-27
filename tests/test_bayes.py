"""Tests for bayesian_studio.engine.bayes — ported + TDD slices."""
import math

import pytest

from bayesian_studio.engine.bayes import (
    compute_bayesian_probability,
    compute_probability_trace,
    evaluate_observation,
)
from bayesian_studio.engine.jinja_env import build_jinja2_env


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _timeline(*pairs):
    """Build a timeline dict from (ts, state) pairs."""
    ts_list, state_list = zip(*pairs) if pairs else ([], [])
    return {"ts": list(ts_list), "state": list(state_list), "attrs": [None] * len(ts_list)}


# ---------------------------------------------------------------------------
# compute_bayesian_probability — ported from backfill
# ---------------------------------------------------------------------------

class TestComputeBayesianProbability:
    def test_single_active_observation_increases_probability(self):
        obs = [{"prob_given_true": 0.9, "prob_given_false": 0.1}]
        result = compute_bayesian_probability(0.5, obs, [True])
        assert result > 0.5

    def test_single_inactive_observation_decreases_probability(self):
        obs = [{"prob_given_true": 0.9, "prob_given_false": 0.1}]
        result = compute_bayesian_probability(0.5, obs, [False])
        assert result < 0.5

    def test_none_result_skips_observation(self):
        obs = [{"prob_given_true": 0.9, "prob_given_false": 0.1}]
        result = compute_bayesian_probability(0.5, obs, [None])
        assert result == pytest.approx(0.5, abs=1e-4)

    def test_multiple_observations_compound(self):
        obs = [
            {"prob_given_true": 0.9, "prob_given_false": 0.1},
            {"prob_given_true": 0.8, "prob_given_false": 0.2},
        ]
        result = compute_bayesian_probability(0.5, obs, [True, True])
        assert result > 0.9

    def test_result_clamped_to_min(self):
        obs = [{"prob_given_true": 0.001, "prob_given_false": 0.999}]
        result = compute_bayesian_probability(0.001, obs, [False])
        assert result >= 0.0001

    def test_result_clamped_to_max(self):
        obs = [{"prob_given_true": 0.999, "prob_given_false": 0.001}]
        result = compute_bayesian_probability(0.999, obs, [True])
        assert result <= 0.9999

    def test_zero_denominator_skipped(self):
        obs = [{"prob_given_true": 0.0, "prob_given_false": 0.0}]
        result = compute_bayesian_probability(0.5, obs, [True])
        assert result == pytest.approx(0.5, abs=1e-4)

    def test_result_rounded_to_6dp(self):
        obs = [{"prob_given_true": 0.7, "prob_given_false": 0.3}]
        result = compute_bayesian_probability(0.5, obs, [True])
        assert result == round(result, 6)


# ---------------------------------------------------------------------------
# evaluate_observation — ported from backfill
# ---------------------------------------------------------------------------

class TestEvaluateObservation:
    def test_state_platform_active(self):
        obs = {"platform": "state", "entity_id": "sensor.foo", "to_state": "on"}
        tl = _timeline((1000.0, "on"))
        ctx = {"ts": 1000.0}
        result = evaluate_observation(obs, {"sensor.foo": tl}, {}, 0, ctx)
        assert result is True

    def test_state_platform_inactive(self):
        obs = {"platform": "state", "entity_id": "sensor.foo", "to_state": "on"}
        tl = _timeline((1000.0, "off"))
        ctx = {"ts": 1000.0}
        result = evaluate_observation(obs, {"sensor.foo": tl}, {}, 0, ctx)
        assert result is False

    def test_state_platform_no_history_returns_none(self):
        obs = {"platform": "state", "entity_id": "sensor.missing", "to_state": "on"}
        ctx = {"ts": 1000.0}
        result = evaluate_observation(obs, {}, {}, 0, ctx)
        assert result is None

    def test_numeric_state_within_range(self):
        obs = {"platform": "numeric_state", "entity_id": "sensor.lux", "above": 10, "below": 100}
        tl = _timeline((1000.0, "50"))
        ctx = {"ts": 1000.0}
        result = evaluate_observation(obs, {"sensor.lux": tl}, {}, 0, ctx)
        assert result is True

    def test_numeric_state_below_range(self):
        obs = {"platform": "numeric_state", "entity_id": "sensor.lux", "above": 10, "below": 100}
        tl = _timeline((1000.0, "5"))
        ctx = {"ts": 1000.0}
        result = evaluate_observation(obs, {"sensor.lux": tl}, {}, 0, ctx)
        assert result is False

    def test_numeric_state_boundary_is_exclusive(self):
        obs = {"platform": "numeric_state", "entity_id": "sensor.lux", "above": 10, "below": 100}
        tl = _timeline((1000.0, "10"))  # equal to above → not active (strict >)
        ctx = {"ts": 1000.0}
        result = evaluate_observation(obs, {"sensor.lux": tl}, {}, 0, ctx)
        assert result is False

    def test_numeric_state_unparseable_returns_none(self):
        obs = {"platform": "numeric_state", "entity_id": "sensor.lux", "above": 0}
        tl = _timeline((1000.0, "unavailable"))
        ctx = {"ts": 1000.0}
        result = evaluate_observation(obs, {"sensor.lux": tl}, {}, 0, ctx)
        assert result is None

    def test_template_platform_active(self):
        obs = {"platform": "template", "value_template": "{{ true }}"}
        tl = _timeline((1000.0, "on"))
        timelines = {"sensor.foo": tl}
        env, ctx = build_jinja2_env(timelines, 0.0, 0.0)
        tpl = env.from_string("{{ true }}")
        ctx["ts"] = 1000.0
        result = evaluate_observation(obs, timelines, {0: tpl}, 0, ctx)
        assert result is True

    def test_template_platform_missing_template_returns_false(self):
        obs = {"platform": "template", "value_template": "{{ true }}"}
        ctx = {"ts": 1000.0}
        result = evaluate_observation(obs, {}, {}, 0, ctx)
        assert result is False

    def test_unknown_platform_returns_none(self):
        obs = {"platform": "future_platform"}
        ctx = {"ts": 1000.0}
        result = evaluate_observation(obs, {}, {}, 0, ctx)
        assert result is None


# ---------------------------------------------------------------------------
# compute_probability_trace — TDD (new function)
# ---------------------------------------------------------------------------

class TestComputeProbabilityTrace:
    def _simple_obs(self):
        return [{"platform": "state", "entity_id": "sensor.foo",
                 "to_state": "on", "prob_given_true": 0.9, "prob_given_false": 0.1}]

    def test_returns_expected_keys(self):
        tl = _timeline((1000.0, "on"))
        result = compute_probability_trace(
            self._simple_obs(), 0.5, 0.5,
            {"sensor.foo": tl}, 900.0, 1100.0, 0.0, 0.0,
        )
        assert set(result.keys()) == {
            "rows", "event_timestamps", "warnings",
            "computation_seconds", "template_errors",
        }

    def test_row_keys(self):
        tl = _timeline((1000.0, "on"))
        result = compute_probability_trace(
            self._simple_obs(), 0.5, 0.5,
            {"sensor.foo": tl}, 900.0, 1100.0, 0.0, 0.0,
        )
        assert len(result["rows"]) >= 1
        row = result["rows"][0]
        assert "ts" in row and "probability" in row and "state" in row

    def test_probability_matches_manual_bayes(self):
        tl = _timeline((1000.0, "on"))
        result = compute_probability_trace(
            self._simple_obs(), 0.5, 0.5,
            {"sensor.foo": tl}, 900.0, 1100.0, 0.0, 0.0,
        )
        row = result["rows"][0]
        # Manual Bayes: p=0.5, p_t=0.9, p_f=0.1 → (0.5*0.9)/(0.5*0.9+0.5*0.1) = 0.9
        assert row["probability"] == pytest.approx(0.9, abs=1e-4)

    def test_state_on_when_above_threshold(self):
        tl = _timeline((1000.0, "on"))
        result = compute_probability_trace(
            self._simple_obs(), 0.5, 0.85,
            {"sensor.foo": tl}, 900.0, 1100.0, 0.0, 0.0,
        )
        assert result["rows"][0]["state"] == "on"

    def test_state_off_when_below_threshold(self):
        tl = _timeline((1000.0, "off"))
        result = compute_probability_trace(
            self._simple_obs(), 0.5, 0.85,
            {"sensor.foo": tl}, 900.0, 1100.0, 0.0, 0.0,
        )
        assert result["rows"][0]["state"] == "off"

    def test_missing_entity_warning(self):
        result = compute_probability_trace(
            self._simple_obs(), 0.5, 0.5,
            {}, 900.0, 1100.0, 0.0, 0.0,
        )
        types = [w["type"] for w in result["warnings"]]
        assert "missing_entity_history" in types

    def test_always_active_warning(self):
        # Two events, observation always on
        tl = _timeline((1000.0, "on"), (1010.0, "on"))
        result = compute_probability_trace(
            self._simple_obs(), 0.5, 0.5,
            {"sensor.foo": tl}, 900.0, 1100.0, 0.0, 0.0,
        )
        types = [w["type"] for w in result["warnings"]]
        assert "always_active" in types

    def test_computation_seconds_is_float(self):
        tl = _timeline((1000.0, "on"))
        result = compute_probability_trace(
            self._simple_obs(), 0.5, 0.5,
            {"sensor.foo": tl}, 900.0, 1100.0, 0.0, 0.0,
        )
        assert isinstance(result["computation_seconds"], float)

    def test_fallback_single_row_when_no_events_in_window(self):
        # Timeline only has events outside the window
        tl = _timeline((500.0, "on"))
        result = compute_probability_trace(
            self._simple_obs(), 0.5, 0.5,
            {"sensor.foo": tl}, 900.0, 1100.0, 0.0, 0.0,
        )
        # Should produce at least one row (fallback to start_ts)
        assert len(result["rows"]) >= 1
