#!/usr/bin/env bash
# Deploy Python source changes directly to the running add-on container.
# Streamlit detects the changed files and reloads automatically (~2s).
# Use for Python-only changes. For requirements/rootfs changes, push to
# GitHub and rebuild via HA instead.
set -euo pipefail

CONTAINER="addon_133771a6_bayesian_studio"
SRC="$(cd "$(dirname "$0")" && pwd)/bayesian-studio/bayesian_studio"

if ! docker inspect "$CONTAINER" &>/dev/null; then
    echo "Container $CONTAINER not found — is the add-on running?" >&2
    exit 1
fi

echo "Deploying to $CONTAINER…"
tar -C "$SRC" \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    -cf - . \
  | docker exec -i "$CONTAINER" tar -C /app/bayesian_studio -xf -

echo "Done — Streamlit will reload in ~2s"
