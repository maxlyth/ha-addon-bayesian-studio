"""Round-trip YAML write-back for Bayesian sensor configs + HA integration reload."""
import io
import os
from typing import Any

import requests
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap


def compute_change_summary(
    working: dict,
    orig_obs: list,
    orig_prior: float,
    orig_threshold: float,
) -> list[dict]:
    """Return a list of changed fields with old/new values.

    Each item: {"field": str, "old": Any, "new": Any}
    Returns empty list if nothing changed.
    """
    changes = []
    if working["prior"] != orig_prior:
        changes.append({"field": "prior", "old": orig_prior, "new": working["prior"]})
    if working["threshold"] != orig_threshold:
        changes.append({
            "field": "probability_threshold",
            "old": orig_threshold,
            "new": working["threshold"],
        })
    n_w = len(working["observations"])
    n_o = len(orig_obs)
    for i in range(max(n_w, n_o)):
        if i < n_w and i < n_o:
            w_obs = working["observations"][i]
            o_obs = orig_obs[i]
            eid = w_obs.get("entity_id", f"obs[{i}]")
            for key in ("prob_given_true", "prob_given_false", "to_state", "above", "below", "value_template"):
                old_val = o_obs.get(key)
                new_val = w_obs.get(key)
                if old_val != new_val:
                    changes.append({
                        "field": f"observations[{i}].{key} ({eid})",
                        "old": old_val,
                        "new": new_val,
                    })
        elif i < n_w:
            w_obs = working["observations"][i]
            eid = w_obs.get("entity_id", w_obs.get("value_template", f"obs[{i}]")[:40])
            changes.append({"field": f"observations[{i}] NEW", "old": None, "new": eid})
        else:
            o_obs = orig_obs[i]
            eid = o_obs.get("entity_id", o_obs.get("value_template", f"obs[{i}]")[:40])
            changes.append({"field": f"observations[{i}] REMOVED", "old": eid, "new": None})

    orig_names = working.get("_orig_obs_names") or []
    curr_names = working.get("_obs_names") or []
    for i, (old_name, new_name) in enumerate(zip(orig_names, curr_names)):
        if old_name != new_name:
            obs = working["observations"][i] if i < len(working["observations"]) else {}
            eid = obs.get("entity_id", f"obs[{i}]")
            changes.append({
                "field": f"observations[{i}] name ({eid})",
                "old": old_name or None,
                "new": new_name or None,
            })

    return changes


def save_yaml_config(file_path: str, unique_id: str, working: dict) -> None:
    """Write tuned values back to the YAML file, preserving comments and formatting.

    Uses ruamel.yaml round-trip mode so inline comments and key order are kept.
    Raises ValueError if the sensor with the given unique_id is not found.
    """
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096  # prevent unwanted line-wrapping

    with open(file_path) as f:
        data = yaml.load(f)

    sensor = find_sensor(data, unique_id)
    if sensor is None:
        raise ValueError(
            f"Bayesian sensor with unique_id={unique_id!r} not found in {file_path}"
        )

    sensor["prior"] = round(float(working["prior"]), 6)
    sensor["probability_threshold"] = round(float(working["threshold"]), 6)

    yaml_obs_seq = sensor["observations"]
    n_yaml = len(yaml_obs_seq)

    # Remove trailing yaml obs that were deleted
    while len(yaml_obs_seq) > len(working["observations"]):
        yaml_obs_seq.pop()

    # Update existing + append new
    for idx, w_obs in enumerate(working["observations"]):
        if idx < n_yaml:
            y_obs = yaml_obs_seq[idx]
            for key in ("prob_given_true", "prob_given_false"):
                if key in y_obs or key in w_obs:
                    y_obs[key] = round(float(w_obs[key]), 6)
            for key in ("to_state", "above", "below", "value_template"):
                if key in w_obs:
                    y_obs[key] = w_obs[key]
        else:
            yaml_obs_seq.append(CommentedMap(w_obs))

    names = working.get("_obs_names")
    if names is not None:
        _apply_obs_names(yaml_obs_seq, names)

    with open(file_path, "w") as f:
        yaml.dump(data, f)


def _apply_obs_names(yaml_obs_seq: Any, names: list[str]) -> None:
    """Write observation friendly names as inline comments on the platform key."""
    from ruamel.yaml.tokens import CommentToken
    from ruamel.yaml.error import CommentMark

    for y_obs, name in zip(yaml_obs_seq, names):
        if name:
            ct = CommentToken(f"# {name}\n", CommentMark(0), None)
            if "platform" in y_obs.ca.items:
                y_obs.ca.items["platform"][2] = ct
            else:
                y_obs.ca.items["platform"] = [None, None, ct, None]
        else:
            if "platform" in y_obs.ca.items:
                items = y_obs.ca.items["platform"]
                if len(items) > 2:
                    items[2] = None


def find_sensor(data: Any, unique_id: str) -> Any:
    """Return the CommentedMap for the sensor matching unique_id, or None."""
    candidates: list = []
    if isinstance(data, list):
        candidates = data
    elif isinstance(data, dict):
        for val in data.values():
            if isinstance(val, list):
                candidates.extend(val)
    for item in candidates:
        if not isinstance(item, dict):
            continue
        if item.get("platform") == "bayesian" and item.get("unique_id") == unique_id:
            return item
    return None


def reload_bayesian_integration() -> bool:
    """POST to the HA Supervisor API to reload the bayesian integration.

    Returns True on success (2xx), False if the token is absent or the call fails.
    """
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        return False
    try:
        resp = requests.post(
            "http://supervisor/core/api/services/homeassistant/reload_all",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        return resp.status_code < 300
    except Exception:
        return False


def generate_yaml_snippet(working: dict) -> str:
    """Return a clean YAML string for the working config.

    Intended for UI-sourced sensors that cannot be written back directly.
    """
    yaml = YAML()
    yaml.default_flow_style = False
    config = {
        "platform": "bayesian",
        "prior": round(float(working["prior"]), 6),
        "probability_threshold": round(float(working["threshold"]), 6),
        "observations": [dict(obs) for obs in working["observations"]],
    }
    buf = io.StringIO()
    yaml.dump(config, buf)
    return buf.getvalue()
