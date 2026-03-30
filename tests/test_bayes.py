"""Tests for bayesian_studio.engine.bayes — ported + TDD slices."""
import math

import pytest

from bayesian_studio.engine.bayes import (
    compute_bayesian_probability,
    compute_probability_trace,
    evaluate_observation,
    extract_template_entity_ids_for_obs,
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


# ---------------------------------------------------------------------------
# extract_template_entity_ids_for_obs
# ---------------------------------------------------------------------------

class TestExtractTemplateEntityIdsForObs:
    def test_single_states_call(self):
        obs = {"platform": "template", "value_template": "{{ states('sensor.foo') == 'on' }}"}
        assert extract_template_entity_ids_for_obs(obs) == ["sensor.foo"]

    def test_multiple_entities_deduped_in_order(self):
        obs = {
            "platform": "template",
            "value_template": "{{ states('sensor.a') and states('sensor.b') and states('sensor.a') }}",
        }
        result = extract_template_entity_ids_for_obs(obs)
        assert result == ["sensor.a", "sensor.b"]

    def test_state_attr_extracted(self):
        obs = {"platform": "template", "value_template": "{{ state_attr('climate.living', 'temperature') > 20 }}"}
        assert extract_template_entity_ids_for_obs(obs) == ["climate.living"]

    def test_non_template_returns_empty(self):
        assert extract_template_entity_ids_for_obs({"platform": "state", "entity_id": "sensor.x"}) == []

    def test_no_platform_returns_empty(self):
        assert extract_template_entity_ids_for_obs({}) == []

    def test_empty_template_returns_empty(self):
        assert extract_template_entity_ids_for_obs({"platform": "template", "value_template": ""}) == []

    def test_mixed_states_and_state_attr(self):
        obs = {
            "platform": "template",
            "value_template": "{{ states('sensor.a') and state_attr('sensor.b', 'unit') }}",
        }
        result = extract_template_entity_ids_for_obs(obs)
        assert "sensor.a" in result
        assert "sensor.b" in result

    def test_is_state_extracted(self):
        obs = {"platform": "template", "value_template": "{{ is_state('binary_sensor.door', 'on') }}"}
        assert extract_template_entity_ids_for_obs(obs) == ["binary_sensor.door"]

    def test_is_state_attr_extracted(self):
        obs = {"platform": "template", "value_template": "{{ is_state_attr('climate.hall', 'hvac_mode', 'heat') }}"}
        assert extract_template_entity_ids_for_obs(obs) == ["climate.hall"]

    def test_has_value_extracted(self):
        obs = {"platform": "template", "value_template": "{{ has_value('sensor.lux') }}"}
        assert extract_template_entity_ids_for_obs(obs) == ["sensor.lux"]

    def test_dotted_states_extracted(self):
        obs = {"platform": "template", "value_template": "{{ states.device_tracker.max == 'home' }}"}
        assert extract_template_entity_ids_for_obs(obs) == ["device_tracker.max"]

    def test_mixed_dotted_and_function_calls(self):
        obs = {
            "platform": "template",
            "value_template": "{{ states.device_tracker.max == 'home' and is_state('sensor.foo', 'on') }}",
        }
        result = extract_template_entity_ids_for_obs(obs)
        assert "sensor.foo" in result
        assert "device_tracker.max" in result


# ---------------------------------------------------------------------------
# build_jinja2_env — HA template extensions
# ---------------------------------------------------------------------------


class TestBuildJinja2EnvTemplateExtensions:
    def _make_env(self, timelines=None):
        env, ctx = build_jinja2_env(timelines or {}, 0.0, 0.0)
        ctx["ts"] = 1000.0
        return env, ctx

    def test_states_callable(self):
        tl = _timeline((1000.0, "on"))
        env, ctx = self._make_env({"sensor.foo": tl})
        result = env.from_string("{{ states('sensor.foo') }}").render()
        assert result == "on"

    def test_states_dotted_access(self):
        tl = _timeline((1000.0, "home"))
        env, ctx = self._make_env({"device_tracker.max": tl})
        result = env.from_string("{{ states.device_tracker.max }}").render()
        assert result == "home"

    def test_states_dotted_unknown_entity(self):
        env, ctx = self._make_env()
        result = env.from_string("{{ states.device_tracker.missing }}").render()
        assert result == "unknown"

    def test_is_state_true(self):
        tl = _timeline((1000.0, "on"))
        env, ctx = self._make_env({"binary_sensor.door": tl})
        result = env.from_string("{{ is_state('binary_sensor.door', 'on') }}").render()
        assert result.strip().lower() in ("true",)

    def test_is_state_false(self):
        tl = _timeline((1000.0, "off"))
        env, ctx = self._make_env({"binary_sensor.door": tl})
        result = env.from_string("{{ is_state('binary_sensor.door', 'on') }}").render()
        assert result.strip().lower() in ("false",)

    def test_is_state_unknown_entity(self):
        env, ctx = self._make_env()
        result = env.from_string("{{ is_state('sensor.missing', 'on') }}").render()
        assert result.strip().lower() in ("false",)

    def test_is_state_attr_true(self):
        tl = _timeline((1000.0, "heat"))
        tl["attrs"] = ['{"hvac_mode": "heat"}']
        env, ctx = self._make_env({"climate.hall": tl})
        result = env.from_string("{{ is_state_attr('climate.hall', 'hvac_mode', 'heat') }}").render()
        assert result.strip().lower() in ("true",)

    def test_is_state_attr_false(self):
        tl = _timeline((1000.0, "heat"))
        tl["attrs"] = ['{"hvac_mode": "cool"}']
        env, ctx = self._make_env({"climate.hall": tl})
        result = env.from_string("{{ is_state_attr('climate.hall', 'hvac_mode', 'heat') }}").render()
        assert result.strip().lower() in ("false",)

    def test_has_value_true(self):
        tl = _timeline((1000.0, "42"))
        env, ctx = self._make_env({"sensor.lux": tl})
        result = env.from_string("{{ has_value('sensor.lux') }}").render()
        assert result.strip().lower() in ("true",)

    def test_has_value_false_missing(self):
        env, ctx = self._make_env()
        result = env.from_string("{{ has_value('sensor.missing') }}").render()
        assert result.strip().lower() in ("false",)

    def test_has_value_false_unavailable(self):
        tl = _timeline((1000.0, "unavailable"))
        env, ctx = self._make_env({"sensor.lux": tl})
        result = env.from_string("{{ has_value('sensor.lux') }}").render()
        assert result.strip().lower() in ("false",)

    def test_has_value_false_unknown(self):
        tl = _timeline((1000.0, "unknown"))
        env, ctx = self._make_env({"sensor.lux": tl})
        result = env.from_string("{{ has_value('sensor.lux') }}").render()
        assert result.strip().lower() in ("false",)

    def test_template_with_is_state_evaluates_correctly(self):
        """Full template evaluation via compute_probability_trace."""
        obs = [{"platform": "template",
                "value_template": "{{ is_state('binary_sensor.door', 'on') }}",
                "prob_given_true": 0.9, "prob_given_false": 0.1}]
        tl = _timeline((1000.0, "on"))
        result = compute_probability_trace(
            obs, 0.5, 0.5,
            {"binary_sensor.door": tl}, 900.0, 1100.0, 0.0, 0.0,
        )
        row = next(r for r in result["rows"] if r["ts"] >= 1000.0)
        assert row["probability"] == pytest.approx(0.9, abs=1e-4)

    def test_template_with_dotted_states_evaluates_correctly(self):
        """Full template evaluation using dotted states access."""
        obs = [{"platform": "template",
                "value_template": "{{ states.device_tracker.max == 'home' }}",
                "prob_given_true": 0.9, "prob_given_false": 0.1}]
        tl = _timeline((1000.0, "home"))
        result = compute_probability_trace(
            obs, 0.5, 0.5,
            {"device_tracker.max": tl}, 900.0, 1100.0, 0.0, 0.0,
        )
        row = next(r for r in result["rows"] if r["ts"] >= 1000.0)
        assert row["probability"] == pytest.approx(0.9, abs=1e-4)


# ---------------------------------------------------------------------------
# build_jinja2_env — time/date functions
# ---------------------------------------------------------------------------


class TestBuildJinja2EnvTimeFunctions:
    def _make_env(self, timelines=None, tz=None):
        env, ctx = build_jinja2_env(timelines or {}, 0.0, 0.0, tz=tz)
        return env, ctx

    def test_utcnow_returns_utc(self):
        env, ctx = self._make_env()
        ctx["ts"] = 1704070200.0  # 2024-01-01 00:30 UTC
        result = env.from_string("{{ utcnow().hour }}").render()
        assert int(result) == 0

    def test_utcnow_always_utc_even_with_local_tz(self):
        from zoneinfo import ZoneInfo
        env, ctx = self._make_env(tz=ZoneInfo("Australia/Sydney"))
        ctx["ts"] = 1704070200.0
        result = env.from_string("{{ utcnow().tzname() }}").render()
        assert result == "UTC"

    def test_today_at_basic(self):
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Europe/London")
        env, ctx = self._make_env(tz=tz)
        ctx["ts"] = 1704070200.0  # 2024-01-01 00:30 UTC = 00:30 GMT
        result = env.from_string("{{ today_at('22:00').hour }}").render()
        assert int(result) == 22

    def test_today_at_comparison(self):
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Europe/London")
        env, ctx = self._make_env(tz=tz)
        ctx["ts"] = 1704070200.0  # 00:30 local
        result = env.from_string("{{ now() < today_at('06:00') }}").render()
        assert result.strip().lower() == "true"

    def test_as_timestamp_from_datetime(self):
        env, ctx = self._make_env()
        ctx["ts"] = 1704070200.0
        result = env.from_string("{{ as_timestamp(now()) }}").render()
        assert float(result) == pytest.approx(1704070200.0, abs=1)

    def test_as_timestamp_from_string(self):
        env, ctx = self._make_env()
        ctx["ts"] = 0.0
        result = env.from_string("{{ as_timestamp('2024-01-01T00:00:00+00:00') }}").render()
        assert float(result) == pytest.approx(1704067200.0, abs=1)

    def test_as_timestamp_invalid_returns_default(self):
        env, ctx = self._make_env()
        ctx["ts"] = 0.0
        result = env.from_string("{{ as_timestamp('not-a-date', 0) }}").render()
        assert result == "0"

    def test_as_datetime_from_timestamp(self):
        env, ctx = self._make_env()
        ctx["ts"] = 0.0
        result = env.from_string("{{ as_datetime(1704067200).year }}").render()
        assert int(result) == 2024

    def test_as_datetime_from_string(self):
        env, ctx = self._make_env()
        ctx["ts"] = 0.0
        result = env.from_string("{{ as_datetime('2024-06-15T12:00:00').month }}").render()
        assert int(result) == 6

    def test_as_local(self):
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Australia/Sydney")
        env, ctx = self._make_env(tz=tz)
        ctx["ts"] = 0.0
        # Convert a UTC datetime to local
        result = env.from_string("{{ as_local(utcnow()).tzinfo.key }}").render()
        assert result == "Australia/Sydney"

    def test_timedelta_arithmetic(self):
        env, ctx = self._make_env()
        ctx["ts"] = 1704070200.0
        result = env.from_string("{{ (now() + timedelta(hours=1)).hour }}").render()
        assert int(result) == 1  # 00:30 + 1h = 01:30

    def test_strptime(self):
        env, ctx = self._make_env()
        ctx["ts"] = 0.0
        result = env.from_string("{{ strptime('2024-03-15', '%Y-%m-%d').month }}").render()
        assert int(result) == 3

    def test_strptime_default_on_failure(self):
        env, ctx = self._make_env()
        ctx["ts"] = 0.0
        result = env.from_string("{{ strptime('bad', '%Y-%m-%d', 'fallback') }}").render()
        assert result == "fallback"


# ---------------------------------------------------------------------------
# build_jinja2_env — type conversion & utility functions
# ---------------------------------------------------------------------------


class TestBuildJinja2EnvUtilityFunctions:
    def _make_env(self, timelines=None):
        env, ctx = build_jinja2_env(timelines or {}, 0.0, 0.0)
        ctx["ts"] = 1000.0
        return env, ctx

    def test_float_function(self):
        env, ctx = self._make_env()
        result = env.from_string("{{ float('3.14') }}").render()
        assert float(result) == pytest.approx(3.14)

    def test_float_filter(self):
        tl = _timeline((1000.0, "42.5"))
        env, ctx = self._make_env({"sensor.temp": tl})
        result = env.from_string("{{ states('sensor.temp') | float }}").render()
        assert float(result) == pytest.approx(42.5)

    def test_float_default_on_failure(self):
        env, ctx = self._make_env()
        result = env.from_string("{{ float('bad', 0) }}").render()
        assert result == "0"

    def test_float_filter_default(self):
        tl = _timeline((1000.0, "unavailable"))
        env, ctx = self._make_env({"sensor.temp": tl})
        result = env.from_string("{{ states('sensor.temp') | float(0) }}").render()
        assert result == "0"

    def test_int_function(self):
        env, ctx = self._make_env()
        result = env.from_string("{{ int('42') }}").render()
        assert result == "42"

    def test_int_truncates_decimal(self):
        env, ctx = self._make_env()
        result = env.from_string("{{ int('3.7') }}").render()
        assert result == "3"

    def test_int_filter(self):
        tl = _timeline((1000.0, "99"))
        env, ctx = self._make_env({"sensor.count": tl})
        result = env.from_string("{{ states('sensor.count') | int }}").render()
        assert result == "99"

    def test_int_default_on_failure(self):
        env, ctx = self._make_env()
        result = env.from_string("{{ int('bad', 0) }}").render()
        assert result == "0"

    def test_bool_true_values(self):
        env, ctx = self._make_env()
        for val in ("true", "yes", "on", "enable", "1"):
            result = env.from_string(f"{{% if bool('{val}') %}}yes{{% endif %}}").render()
            assert result == "yes", f"bool('{val}') should be True"

    def test_bool_false_values(self):
        env, ctx = self._make_env()
        for val in ("false", "no", "off", "disable", "0"):
            result = env.from_string(f"{{% if not bool('{val}') %}}no{{% endif %}}").render()
            assert result == "no", f"bool('{val}') should be False"

    def test_bool_default_on_failure(self):
        env, ctx = self._make_env()
        result = env.from_string("{{ bool('maybe', false) }}").render()
        assert result.strip().lower() == "false"

    def test_is_number_true(self):
        env, ctx = self._make_env()
        result = env.from_string("{{ is_number('42.5') }}").render()
        assert result.strip().lower() == "true"

    def test_is_number_false(self):
        env, ctx = self._make_env()
        result = env.from_string("{{ is_number('hello') }}").render()
        assert result.strip().lower() == "false"

    def test_is_number_filter(self):
        tl = _timeline((1000.0, "3.14"))
        env, ctx = self._make_env({"sensor.val": tl})
        result = env.from_string("{{ states('sensor.val') | is_number }}").render()
        assert result.strip().lower() == "true"

    def test_is_number_inf_is_false(self):
        env, ctx = self._make_env()
        result = env.from_string("{{ is_number('inf') }}").render()
        assert result.strip().lower() == "false"

    def test_iif_true(self):
        env, ctx = self._make_env()
        result = env.from_string("{{ iif(true, 'yes', 'no') }}").render()
        assert result == "yes"

    def test_iif_false(self):
        env, ctx = self._make_env()
        result = env.from_string("{{ iif(false, 'yes', 'no') }}").render()
        assert result == "no"

    def test_iif_with_expression(self):
        tl = _timeline((1000.0, "on"))
        env, ctx = self._make_env({"sensor.foo": tl})
        result = env.from_string("{{ iif(is_state('sensor.foo', 'on'), 'active', 'idle') }}").render()
        assert result == "active"

    def test_float_filter_in_comparison(self):
        """Common pattern: states('sensor.x') | float > threshold."""
        obs = [{"platform": "template",
                "value_template": "{{ states('sensor.lux') | float(0) > 100 }}",
                "prob_given_true": 0.9, "prob_given_false": 0.1}]
        tl = _timeline((1000.0, "250"))
        result = compute_probability_trace(
            obs, 0.5, 0.5,
            {"sensor.lux": tl}, 900.0, 1100.0, 0.0, 0.0,
        )
        row = next(r for r in result["rows"] if r["ts"] >= 1000.0)
        assert row["probability"] == pytest.approx(0.9, abs=1e-4)

    def test_today_at_night_condition(self):
        """Common pattern: now() > today_at('22:00') or now() < today_at('06:00')."""
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Europe/London")
        obs = [{"platform": "template",
                "value_template": "{{ now().hour >= 22 or now().hour < 6 }}",
                "prob_given_true": 0.9, "prob_given_false": 0.1}]
        # ts at 23:30 local
        tl = _timeline((1711927800.0, "on"))  # placeholder
        result = compute_probability_trace(
            obs, 0.5, 0.5,
            {"sensor.dummy": tl}, 1711927700.0, 1711927900.0, 0.0, 0.0,
            tz=tz,
        )
        # 1711927800 = 2024-04-01 00:30 UTC = 01:30 BST → hour < 6 → true
        assert result["rows"][0]["probability"] == pytest.approx(0.9, abs=1e-4)


# ---------------------------------------------------------------------------
# build_jinja2_env — now() timezone
# ---------------------------------------------------------------------------


class TestBuildJinja2EnvTimezone:
    def test_now_returns_utc_by_default(self):
        env, ctx = build_jinja2_env({}, 0.0, 0.0)
        ctx["ts"] = 0.0
        tpl = env.from_string("{{ now().tzname() }}")
        result = tpl.render()
        assert result == "UTC"

    def test_now_returns_local_tz_when_provided(self):
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Europe/London")
        env, ctx = build_jinja2_env({}, 0.0, 0.0, tz=tz)
        ctx["ts"] = 0.0
        tpl = env.from_string("{{ now().tzinfo.key }}")
        result = tpl.render()
        assert result == "Europe/London"

    def test_now_hour_uses_local_tz(self):
        """now().hour differs between UTC and a UTC+10 timezone at midnight UTC."""
        from zoneinfo import ZoneInfo
        import time as _time
        # Use a fixed timestamp: 2024-01-01 00:30 UTC = 2024-01-01 10:30 in UTC+10
        ts = 1704070200.0  # 2024-01-01 00:30:00 UTC
        tz_utc10 = ZoneInfo("Australia/Sydney")
        env, ctx = build_jinja2_env({}, 0.0, 0.0, tz=tz_utc10)
        ctx["ts"] = ts
        tpl = env.from_string("{{ now().hour }}")
        result = tpl.render()
        assert int(result) >= 10  # Sydney is UTC+10 or +11
