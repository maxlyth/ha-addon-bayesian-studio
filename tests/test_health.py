"""Tests for bayesian_studio.health — calibration health metrics."""
import pytest

from bayesian_studio.health import (
    fire_frequency_from_timeline,
    observation_activity,
    observation_coverage,
)


# ---------------------------------------------------------------------------
# observation_coverage
# ---------------------------------------------------------------------------


def test_coverage_no_entity_id():
    """Template observations have no entity_id — coverage is 0."""
    obs = {"platform": "template", "value_template": "{{ true }}"}
    assert observation_coverage(obs, {}, 0.0, 100.0) == 0.0


def test_coverage_entity_missing_from_timelines():
    obs = {"platform": "state", "entity_id": "sensor.a"}
    tl = {"sensor.b": {"ts": [0.0], "state": ["on"], "attrs": [None]}}
    assert observation_coverage(obs, tl, 0.0, 100.0) == 0.0


def test_coverage_empty_timeline():
    obs = {"platform": "state", "entity_id": "sensor.a"}
    assert observation_coverage(obs, {"sensor.a": {"ts": [], "state": [], "attrs": []}}, 0.0, 100.0) == 0.0


def test_coverage_full_when_state_before_window():
    """State recorded before the window means the whole window is covered."""
    obs = {"platform": "state", "entity_id": "sensor.a"}
    timelines = {"sensor.a": {"ts": [-10.0, 50.0], "state": ["on", "off"], "attrs": [None, None]}}
    assert observation_coverage(obs, timelines, 0.0, 100.0) == pytest.approx(1.0)


def test_coverage_partial_starts_mid_window():
    """First state at t=40 in a [0,100] window → 60% coverage."""
    obs = {"platform": "state", "entity_id": "sensor.a"}
    timelines = {"sensor.a": {"ts": [40.0], "state": ["on"], "attrs": [None]}}
    assert observation_coverage(obs, timelines, 0.0, 100.0) == pytest.approx(0.6)


def test_coverage_state_after_window():
    """State only recorded after the window ends → 0%."""
    obs = {"platform": "state", "entity_id": "sensor.a"}
    timelines = {"sensor.a": {"ts": [150.0], "state": ["on"], "attrs": [None]}}
    assert observation_coverage(obs, timelines, 0.0, 100.0) == 0.0


# ---------------------------------------------------------------------------
# observation_activity
# ---------------------------------------------------------------------------


def test_activity_always_true():
    assert observation_activity([True, True, True]) == "always"


def test_activity_always_false():
    assert observation_activity([False, False, False]) == "never"


def test_activity_mixed():
    assert observation_activity([True, False, True]) is None


def test_activity_nones_are_filtered():
    """None values (missing data) don't count — remaining Trues → 'always'."""
    assert observation_activity([None, True, True]) == "always"


def test_activity_all_nones():
    """No usable data → cannot determine activity."""
    assert observation_activity([None, None, None]) is None


def test_activity_empty():
    assert observation_activity([]) is None


# ---------------------------------------------------------------------------
# fire_frequency_from_timeline
# ---------------------------------------------------------------------------


def _tl(*pairs):
    """Build a timeline dict from (ts, state) pairs."""
    ts_list = [p[0] for p in pairs]
    state_list = [p[1] for p in pairs]
    return {"ts": ts_list, "state": state_list, "attrs": [None] * len(ts_list)}


def test_fire_frequency_empty():
    assert fire_frequency_from_timeline({}, 0.0, 100.0) == 0.0


def test_fire_frequency_always_off():
    assert fire_frequency_from_timeline(_tl((0.0, "off"), (50.0, "off")), 0.0, 100.0) == pytest.approx(0.0)


def test_fire_frequency_always_on():
    assert fire_frequency_from_timeline(_tl((0.0, "on")), 0.0, 100.0) == pytest.approx(1.0)


def test_fire_frequency_half():
    assert fire_frequency_from_timeline(_tl((0.0, "on"), (50.0, "off")), 0.0, 100.0) == pytest.approx(0.5)


def test_fire_frequency_clamps_to_window():
    """State that starts before the window is clipped to window start."""
    assert fire_frequency_from_timeline(_tl((-50.0, "on"), (50.0, "off")), 0.0, 100.0) == pytest.approx(0.5)


def test_fire_frequency_multiple_segments():
    tl = _tl((0.0, "on"), (25.0, "off"), (75.0, "on"))
    # on: 0→25 (25s) + 75→100 (25s) = 50s / 100s = 0.5
    assert fire_frequency_from_timeline(tl, 0.0, 100.0) == pytest.approx(0.5)
