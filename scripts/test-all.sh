#!/bin/sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export BEAMO_WIPE_DRY_RUN="${BEAMO_WIPE_DRY_RUN:-1}"
exec python3 -m pytest "$@"
