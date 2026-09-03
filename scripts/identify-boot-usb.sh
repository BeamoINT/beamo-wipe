#!/bin/sh
# Identify the live boot medium. Prints /dev/… or exits 2.
set -eu
ROOT="$(CDPATH='' cd -- "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m beamo_wipe.identify "$@"
