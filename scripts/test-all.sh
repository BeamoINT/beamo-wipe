#!/bin/sh
# Local Python gate (fake lsblk; never nwipe a real disk).
# Hosted x86_64 pytest + ISO build: ./scripts/ci-cloud.sh  (Google Cloud Build).
set -eu
ROOT="$(CDPATH='' cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export BEAMO_WIPE_DRY_RUN="${BEAMO_WIPE_DRY_RUN:-1}"
exec python3 -m pytest "$@"
