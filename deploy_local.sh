#!/bin/sh
# Sync local source to /addons/local/bayesian_studio and rebuild.
# Usage: ./deploy_local.sh
set -e

SRC="$(dirname "$0")/bayesian-studio"
DEST="/addons/local/bayesian_studio"
SLUG="local_bayesian_studio"

echo "Syncing $SRC -> $DEST"
rsync -a --delete \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '*.egg-info' \
  "$SRC/" "$DEST/"

echo "Reloading store..."
curl -sf -X POST -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
  http://supervisor/store/reload > /dev/null

echo "Building $SLUG (update if version changed, else rebuild)..."
BUILD_RESP=$(curl -s -X POST -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
  http://supervisor/addons/$SLUG/rebuild)
if echo "$BUILD_RESP" | grep -q "use Update instead"; then
  curl -sf -X POST -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
    http://supervisor/addons/$SLUG/update > /dev/null
else
  echo "$BUILD_RESP" | grep -q '"result":"ok"' || { echo "Build failed: $BUILD_RESP" >&2; exit 1; }
fi

echo "Waiting for started..."
for i in $(seq 1 36); do
  state=$(curl -sf -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
    http://supervisor/addons/$SLUG/info \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['state'])")
  echo "  [$i] $state"
  if [ "$state" = "started" ]; then
    ver=$(curl -sf -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
      http://supervisor/addons/$SLUG/info \
      | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['version'])")
    echo "Done — running v$ver"
    exit 0
  fi
  sleep 5
done

echo "Timed out waiting for add-on to start" >&2
exit 1
