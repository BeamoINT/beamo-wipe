#!/bin/sh
# Preview Beamo Wipe on this computer. Fake disks. Nothing is erased.
set -eu
ROOT="$(CDPATH='' cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export BEAMO_WIPE_DRY_RUN=1
export BEAMO_WIPE_DEMO=1
exec python3 -m beamo_wipe --preview "$@"
