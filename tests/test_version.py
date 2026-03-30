"""Ensure the version string is consistent across all files that declare it."""
import json
import os
import re
from pathlib import Path

import pytest
import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
ADDON_DIR = ROOT / "bayesian-studio"
ADDON_SLUG = os.environ.get("ADDON_SLUG", "local_bayesian_studio")


def _config_version() -> str:
    with open(ADDON_DIR / "config.yaml") as f:
        return yaml.safe_load(f)["version"]


def _dockerfile_version() -> str:
    text = (ADDON_DIR / "Dockerfile").read_text()
    m = re.search(r"ARG\s+VERSION=(\S+)", text)
    assert m, "ARG VERSION not found in Dockerfile"
    return m.group(1)


def _pyproject_version() -> str:
    text = (ROOT / "pyproject.toml").read_text()
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert m, "version not found in pyproject.toml"
    return m.group(1)


def test_all_versions_match():
    """config.yaml, Dockerfile ARG VERSION, and pyproject.toml must agree."""
    config_v = _config_version()
    docker_v = _dockerfile_version()
    pyproject_v = _pyproject_version()
    assert config_v == docker_v, (
        f"config.yaml ({config_v}) != Dockerfile ({docker_v})"
    )
    assert config_v == pyproject_v, (
        f"config.yaml ({config_v}) != pyproject.toml ({pyproject_v})"
    )


# ---------------------------------------------------------------------------
# Integration: verify the running add-on matches the source version
# ---------------------------------------------------------------------------

def _supervisor_get(path: str) -> dict:
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    resp = requests.get(
        f"http://supervisor{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["data"]


@pytest.mark.integration
def test_deployed_version_matches_source():
    """The running add-on version (from Supervisor) must match config.yaml."""
    info = _supervisor_get(f"/addons/{ADDON_SLUG}/info")
    deployed = info["version"]
    expected = _config_version()
    assert deployed == expected, (
        f"Deployed add-on reports v{deployed} but source config.yaml says v{expected}. "
        f"Push to GitHub and update the add-on, or reinstall as a local add-on."
    )
