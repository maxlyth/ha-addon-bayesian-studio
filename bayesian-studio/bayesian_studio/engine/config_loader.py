"""Bayesian sensor config resolution — YAML and UI config entries."""

import fnmatch
import json
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class ConfigSource:
    """Describes where a sensor's config was found."""
    kind: str          # "yaml" or "ui"
    file_path: Optional[str] = None   # set for YAML sensors; None for UI sensors


def load_location(config_dir: str) -> list[float]:
    """Load latitude/longitude from .storage/core.config."""
    path = os.path.join(config_dir, ".storage", "core.config")
    with open(path) as f:
        data = json.load(f)
    d = data.get("data", {})
    return [float(d.get("latitude", 0.0)), float(d.get("longitude", 0.0))]


def load_timezone(config_dir: str) -> str:
    """Return the IANA timezone string from HA config (e.g. 'Europe/London')."""
    path = os.path.join(config_dir, ".storage", "core.config")
    with open(path) as f:
        data = json.load(f)
    return data.get("data", {}).get("time_zone", "UTC")


def search_entity_ids(query: str, config_dir: str, limit: int = 50) -> list[str]:
    """Return entity IDs from the registry whose entity_id contains query as a substring.

    Case-insensitive. Returns up to `limit` results, sorted alphabetically.
    Returns [] if query is empty.
    """
    if not query:
        return []
    registry_path = os.path.join(config_dir, ".storage", "core.entity_registry")
    with open(registry_path) as f:
        registry = json.load(f)
    q = query.lower()
    matches = [
        e["entity_id"]
        for e in registry["data"]["entities"]
        if q in e["entity_id"].lower()
    ]
    return sorted(matches)[:limit]


def get_bayesian_entity_ids(pattern: str, config_dir: str) -> list[str]:
    """Expand a glob pattern against all Bayesian sensor entity_ids in the registry.

    Returns a list of matching entity_ids (platform == 'bayesian').
    For a non-glob pattern, returns [pattern] only if it is a known Bayesian entity.
    """
    registry_path = os.path.join(config_dir, ".storage", "core.entity_registry")
    with open(registry_path) as f:
        registry = json.load(f)
    bayesian_ids = [
        e["entity_id"]
        for e in registry["data"]["entities"]
        if e.get("platform") == "bayesian"
    ]
    if "*" in pattern or "?" in pattern or "[" in pattern:
        return sorted(eid for eid in bayesian_ids if fnmatch.fnmatch(eid, pattern))
    return [pattern] if pattern in bayesian_ids else []


def extract_observation_names(file_path: str, unique_id: str) -> list[str]:
    """Extract inline comments on the 'platform' key for each observation.

    These comments serve as friendly names in the Studio UI.
    Returns one string per observation; empty string where no comment exists.
    Returns [] if the sensor is not found.
    """
    from ruamel.yaml import YAML
    from bayesian_studio.engine.config_writer import find_sensor

    yaml = YAML()
    yaml.preserve_quotes = True
    try:
        with open(file_path) as f:
            data = yaml.load(f)
    except Exception:
        return []

    sensor = find_sensor(data, unique_id)
    if sensor is None:
        return []

    names = []
    for obs in sensor.get("observations", []):
        name = ""
        token_list = obs.ca.items.get("platform")
        if token_list and len(token_list) > 2 and token_list[2] is not None:
            raw = token_list[2].value.strip()
            if raw.startswith("#"):
                name = raw[1:].strip()
        names.append(name)
    return names


def load_bayesian_config(
    target_entity_id: str, config_dir: str
) -> tuple[dict, ConfigSource]:
    """Load Bayesian sensor config from UI config_entries or YAML files.

    Returns (config_dict, ConfigSource). Raises ValueError if not found.
    config_dict has keys: prior, probability_threshold, observations.
    """
    import yaml

    registry_path = os.path.join(config_dir, ".storage", "core.entity_registry")
    with open(registry_path) as f:
        registry = json.load(f)
    entry = next(
        (e for e in registry["data"]["entities"] if e["entity_id"] == target_entity_id),
        None,
    )
    if entry is None:
        raise ValueError(f"Entity {target_entity_id!r} not found in entity registry")

    config_entry_id = entry.get("config_entry_id")
    unique_id = entry.get("unique_id", "")

    # UI-defined: load from core.config_entries
    if config_entry_id:
        ce_path = os.path.join(config_dir, ".storage", "core.config_entries")
        with open(ce_path) as f:
            ce = json.load(f)
        cfg = next(
            (e for e in ce["data"]["entries"] if e["entry_id"] == config_entry_id),
            None,
        )
        if cfg is None:
            raise ValueError(
                f"Config entry {config_entry_id!r} not found for {target_entity_id!r}"
            )
        return cfg["data"], ConfigSource(kind="ui")

    # YAML-defined: strip "bayesian-" prefix and search YAML files
    yaml_unique_id = unique_id.removeprefix("bayesian-")
    scanned = []

    skip_dirs = {".", "venv", "node_modules", "__pycache__", "deps", ".storage"}
    for root, dirs, files in os.walk(config_dir):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
        for fname in files:
            if not (fname.endswith(".yaml") or fname.endswith(".yml")):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath) as f:
                    raw = f.read()
            except OSError:
                continue
            if "platform: bayesian" not in raw:
                continue
            scanned.append(fpath)
            try:
                data = yaml.safe_load(raw)
            except yaml.YAMLError:
                continue
            if data is None:
                continue
            candidates = []
            if isinstance(data, list):
                candidates = data
            elif isinstance(data, dict):
                for val in data.values():
                    if isinstance(val, list):
                        candidates.extend(val)
            for sensor in candidates:
                if not isinstance(sensor, dict):
                    continue
                if sensor.get("platform") != "bayesian":
                    continue
                if sensor.get("unique_id") == yaml_unique_id:
                    return sensor, ConfigSource(kind="yaml", file_path=fpath)

    raise ValueError(
        f"Bayesian config for {target_entity_id!r} (unique_id={yaml_unique_id!r}) "
        f"not found in {len(scanned)} YAML file(s). Scanned: {scanned}"
    )
