#!/bin/sh
# Build a bootable x86_64 ISO that auto-starts Beamo Wipe.
# Requires Docker. Does not wipe any host disk.
set -eu

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VERSION="${BEAMO_WIPE_VERSION:-0.1.0}"
OUT_DIR="$ROOT/dist"
ISO_NAME="beamo-wipe-${VERSION}-amd64.iso"
LIVE="$ROOT/packaging/live"

missing=""
command -v docker >/dev/null 2>&1 || missing="$missing docker"
if [ -n "$missing" ]; then
  echo "Missing required tools:$missing" >&2
  echo "Install Docker Desktop (or Docker Engine) and re-run ./scripts/build-iso.sh" >&2
  exit 2
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker is installed but not running, or this user cannot talk to the daemon." >&2
  exit 2
fi

echo "Staging live-build includes…"
STAGE_PY="$LIVE/config/includes.chroot/usr/lib/python3/dist-packages/beamo_wipe"
STAGE_SHARE="$LIVE/config/includes.chroot/usr/share/beamo-wipe"
STAGE_DOC="$LIVE/config/includes.chroot/usr/share/doc/beamo-wipe"
STAGE_BIN="$LIVE/config/includes.binary"
rm -rf "$STAGE_PY" "$STAGE_SHARE" "$STAGE_DOC"
mkdir -p "$STAGE_PY" "$STAGE_SHARE/helper" "$STAGE_DOC" "$STAGE_BIN" \
  "$LIVE/config/includes.chroot/usr/local/bin"

# Portable dir copy (macOS cp -R)
cp -R "$ROOT/src/beamo_wipe/." "$STAGE_PY/"
cp "$ROOT/helper/index.html" "$STAGE_SHARE/helper/index.html"
cp "$ROOT/helper/index.html" "$STAGE_BIN/START-HERE.html"
cp "$ROOT/NOTICE" "$STAGE_DOC/NOTICE"
cp "$ROOT/LICENSE" "$STAGE_DOC/LICENSE"
cp "$ROOT/THIRD_PARTY.md" "$STAGE_DOC/THIRD_PARTY.md"
cp "$ROOT/NOTICE" "$STAGE_BIN/NOTICE"
cp "$ROOT/LICENSE" "$STAGE_BIN/LICENSE"
printf '%s\n' "Source: https://github.com/BeamoINT/beamo-wipe" > "$STAGE_BIN/SOURCE.txt"
printf '%s\n' "Source: https://github.com/BeamoINT/beamo-wipe" > "$STAGE_DOC/SOURCE.txt"
cat > "$STAGE_BIN/README.txt" <<'EOF'
Beamo Wipe
This USB is a bootable nwipe front-end. It does not wipe from Windows.
Open START-HERE.html for boot-menu keys.
Engine: nwipe (GPL). Wrapper: GPL-3.0-or-later. NO WARRANTY.
https://github.com/BeamoINT/beamo-wipe
EOF

chmod +x "$LIVE/config/includes.chroot/usr/local/bin/beamo-wipe" \
  "$LIVE/config/hooks/normal/"*.hook.chroot 2>/dev/null || true

mkdir -p "$OUT_DIR"

echo "Running Debian live-build in Docker (linux/amd64). This can take a while…"
docker run --rm --privileged --platform linux/amd64 \
  -v "$ROOT":/work \
  -w /work/packaging/live \
  debian:bookworm \
  bash /work/packaging/live/inside-docker.sh

# live-build names the ISO live-image-amd64.hybrid.iso or similar
found="$(find "$LIVE" -maxdepth 1 -name '*.iso' -print | head -n 1)"
if [ -z "$found" ]; then
  found="$(find "$LIVE" -maxdepth 2 -name '*.hybrid.iso' -print | head -n 1)"
fi
if [ -z "$found" ] || [ ! -f "$found" ]; then
  echo "live-build finished but no ISO was found under packaging/live." >&2
  echo "Check the Docker log above." >&2
  exit 1
fi
cp "$found" "$OUT_DIR/$ISO_NAME"
echo "Wrote $OUT_DIR/$ISO_NAME"
ls -lh "$OUT_DIR/$ISO_NAME"
