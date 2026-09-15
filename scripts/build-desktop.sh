#!/usr/bin/env bash
# Compatibility entry point; shared portable implementation owns build flags.
set -euo pipefail
ROOT="$(CDPATH='' cd -- "$(dirname "$0")/.." && pwd)"
exec python3 "$ROOT/scripts/build_desktop.py" "$@"
