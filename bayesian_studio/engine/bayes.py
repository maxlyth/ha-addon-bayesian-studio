"""Bayesian probability computation and observation evaluation."""

import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

from bayesian_studio.engine.jinja_env import build_jinja2_env, eval_template
from bayesian_studio.engine.state_db import get_state_at


def evaluate_observation(
    obs: dict,
    timelines: dict,
    compiled_templates: dict,
    idx: int,
    ctx: dict,
) -> Optional[bool]:
    """Evaluate one observation at ctx["ts"].

    Returns True if active, False if inactive, or None to skip
    (entity has no history — excluded from Bayes update).
    """
    platform = obs.get("platform")

    if platform == "state":
        eid = obs.get("entity_id")
        tl = timelines.get(eid)
        state = get_state_at(tl, ctx["ts"]) if tl else None
        if state is None:
            return None
        return state == obs.get("to_state")

    if platform == "numeric_state":
        eid = obs.get("entity_id")
        tl = timelines.get(eid)
        raw = get_state_at(tl, ctx["ts"]) if tl else None
        if raw is None:
            return None
        try:
            val = float(raw)
        except (ValueError, TypeError):
            return None
        above = float(obs["above"]) if "above" in obs else float("-inf")
        below = float(obs["below"]) if "below" in obs else float("inf")
        return val > above and val < below

    if platform == "template":
        tpl = compiled_templates.get(idx)
        if tpl is None:
            return False
        return eval_template(tpl, ctx)

    return None


def compute_bayesian_probability(
    prior: float, observations: list[dict], obs_results: list[Optional[bool]]
) -> float:
    """Iterative Bayes update over all observations.

    obs_results: list of True/False/None (None = skip this observation).
    Returns probability clamped to [0.0001, 0.9999], rounded to 6dp.
    """
    p = float(prior)
    for obs, active in zip(observations, obs_results):
        if active is None:
            continue
        p_t = float(obs["prob_given_true"])
        p_f = float(obs["prob_given_false"])
        if active:
            denom = p * p_t + (1 - p) * p_f
            num = p * p_t
        else:
            denom = p * (1 - p_t) + (1 - p) * (1 - p_f)
            num = p * (1 - p_t)
        if denom == 0:
            continue
        p = num / denom
    return max(0.0001, min(0.9999, round(p, 6)))


def _extract_template_entity_ids(observations: list[dict]) -> list[str]:
    """Extract entity IDs referenced in template observations via regex."""
    entity_ids = set()
    for obs in observations:
        if obs.get("platform") == "template":
            tpl = obs.get("value_template", "")
            found = re.findall(
                r"(?:states|state_attr)\(\s*['\"]([^'\"]+)['\"]", tpl
            )
            entity_ids.update(found)
    return list(entity_ids)


def compute_probability_trace(
    observations: list[dict],
    prior: float,
    probability_threshold: float,
    timelines: dict,
    start_ts: float,
    end_ts: float,
    lat: float,
    lon: float,
) -> dict:
    """Compute a Bayesian probability trace over the given time window.

    Unlike compute_backfill_rows (which produces DB-write rows), this returns
    a lightweight trace for interactive visualisation.

    Returns a dict with:
      rows               — list of {ts, probability, state, obs_results} dicts
      event_timestamps   — sorted list of Unix timestamps evaluated
      warnings           — list of warning dicts
      computation_seconds — wall-clock time
      template_errors    — list of (obs_index, error_str)
    """
    event_timestamps = sorted({
        ts for tl in timelines.values()
        for ts in tl["ts"]
        if start_ts <= ts < end_ts
    })
    if not event_timestamps:
        event_timestamps = [float(start_ts)]

    env, ctx = build_jinja2_env(timelines, lat, lon)

    compiled_templates: dict = {}
    template_errors: list = []
    for i, obs in enumerate(observations):
        if obs.get("platform") == "template":
            try:
                compiled_templates[i] = env.from_string(obs["value_template"])
            except Exception as exc:
                template_errors.append((i, str(exc)))

    t_start = time.time()
    rows: list[dict] = []
    obs_active_counts = [0] * len(observations)
    obs_eval_counts = [0] * len(observations)

    for ts in event_timestamps:
        ctx["ts"] = float(ts)
        obs_results = [
            evaluate_observation(obs, timelines, compiled_templates, i, ctx)
            for i, obs in enumerate(observations)
        ]
        prob = compute_bayesian_probability(prior, observations, obs_results)

        for i, r in enumerate(obs_results):
            if r is not None:
                obs_eval_counts[i] += 1
                if r is True:
                    obs_active_counts[i] += 1

        rows.append({
            "ts": float(ts),
            "probability": prob,
            "state": "on" if prob >= probability_threshold else "off",
            "obs_results": obs_results,
        })

    computation_seconds = round(time.time() - t_start, 3)

    # Build warnings
    warnings: list[dict] = []
    for i, obs in enumerate(observations):
        platform = obs.get("platform", "")
        eid = obs.get("entity_id", "")

        if platform == "template" and "now()" in obs.get("value_template", ""):
            warnings.append({
                "type": "template_time_dependent",
                "observation_index": i,
                "detail": "Template uses now() — time-of-day transitions between entity "
                          "state changes are not captured",
            })

        if platform in ("state", "numeric_state") and eid and eid not in timelines:
            warnings.append({
                "type": "missing_entity_history",
                "observation_index": i,
                "entity_id": eid,
                "detail": f"No state history found for {eid} in window",
            })

        n_events = len(event_timestamps)
        if n_events > 1 and obs_eval_counts[i] > 0:
            if obs_active_counts[i] == obs_eval_counts[i]:
                warnings.append({
                    "type": "always_active",
                    "observation_index": i,
                    "entity_id": eid,
                    "detail": f"Observation active for all {obs_eval_counts[i]} evaluated events",
                })
            elif obs_active_counts[i] == 0:
                warnings.append({
                    "type": "never_active",
                    "observation_index": i,
                    "entity_id": eid,
                    "detail": f"Observation never active across {obs_eval_counts[i]} evaluated events",
                })

    return {
        "rows": rows,
        "event_timestamps": event_timestamps,
        "warnings": warnings,
        "computation_seconds": computation_seconds,
        "template_errors": template_errors,
    }
