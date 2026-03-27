"""Calibration health metrics for Bayesian sensors."""
from __future__ import annotations


def observation_coverage(
    obs: dict, timelines: dict, start_ts: float, end_ts: float
) -> float:
    """Return fraction [0, 1] of the window where the observation entity has known state."""
    entity_id = obs.get("entity_id")
    if not entity_id:
        return 0.0
    tl = timelines.get(entity_id, {})
    ts_list = tl.get("ts", []) if isinstance(tl, dict) else []
    if not ts_list:
        return 0.0
    first_ts = ts_list[0]
    if first_ts >= end_ts:
        return 0.0
    window = end_ts - start_ts
    if window <= 0:
        return 0.0
    covered_from = max(first_ts, start_ts)
    return (end_ts - covered_from) / window


def observation_activity(results_series: list) -> str | None:
    """Return 'always', 'never', or None from a series of True/False/None evaluation results."""
    filtered = [r for r in results_series if r is not None]
    if not filtered:
        return None
    if all(r is True for r in filtered):
        return "always"
    if all(r is False for r in filtered):
        return "never"
    return None


def fire_frequency_from_timeline(
    timeline: dict, start_ts: float, end_ts: float
) -> float:
    """Return time-weighted fraction of the window where state is 'on'."""
    if not timeline or end_ts <= start_ts:
        return 0.0
    ts_list = timeline.get("ts", []) if isinstance(timeline, dict) else []
    state_list = timeline.get("state", []) if isinstance(timeline, dict) else []
    if not ts_list:
        return 0.0
    on_time = 0.0
    window = end_ts - start_ts
    for i, ts in enumerate(ts_list):
        seg_start = max(ts, start_ts)
        seg_end = min(ts_list[i + 1] if i + 1 < len(ts_list) else end_ts, end_ts)
        if seg_end > seg_start and state_list[i] == "on":
            on_time += seg_end - seg_start
    return on_time / window
