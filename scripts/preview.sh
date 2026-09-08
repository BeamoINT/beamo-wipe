#!/bin/sh
# Preview Beamo Wipe on this computer. Fake disks. Nothing is erased.
set -eu
ROOT="$(CDPATH='' cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export BEAMO_WIPE_DRY_RUN=1
export BEAMO_WIPE_DEMO=1
PYTHON_BIN="${BEAMO_WIPE_PREVIEW_PYTHON:-python3}"
# Older python.org macOS bundles can abort on window close with Tk 8.6.11.
# Prefer an installed modern Tk for the desktop preview only. The live Linux
# launcher and all wipe-environment checks are unchanged.
if [ "$(uname -s)" = Darwin ] && [ -z "${BEAMO_WIPE_PREVIEW_PYTHON:-}" ]; then
  for candidate in python3.14 python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c '
import os
import tkinter
root = tkinter.Tk()
root.withdraw()
version = tuple(map(int, root.tk.call("package", "provide", "Tk").split(".")))
# Probe the loaded Tk, not Tcl (their patch versions can differ). Exit this
# disposable probe without the old Aqua Tk teardown that we are avoiding.
os._exit(0 if version >= (8, 6, 13) else 1)
' >/dev/null 2>&1; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
fi
exec "$PYTHON_BIN" -m beamo_wipe --preview "$@"
