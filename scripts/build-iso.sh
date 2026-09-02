#!/bin/sh
# Build a bootable x86_64 ISO that auto-starts Beamo Wipe.
# Requires Docker. Does not wipe any host disk.
set -eu

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VERSION="${BEAMO_WIPE_VERSION:-0.1.1}"
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

if ! docker info >/tmp/beamo-docker-info.log 2>&1; then
  echo "Docker is installed but not running, or this user cannot talk to the daemon." >&2
  echo "--- docker info output ---" >&2
  cat /tmp/beamo-docker-info.log >&2 || true
  echo "Next: start Docker Desktop, check 'docker context ls' and permissions, then retry." >&2
  echo "Log: /tmp/beamo-docker-info.log" >&2
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

if [ ! -x "$LIVE/config/includes.chroot/usr/local/bin/beamo-wipe" ]; then
  echo "ERROR: includes.chroot/usr/local/bin/beamo-wipe missing or not executable" >&2
  echo "Next: check packaging/live/config/includes.chroot layout" >&2
  exit 1
fi
chmod +x "$LIVE/config/includes.chroot/usr/local/bin/beamo-wipe"
# Fail closed if hooks missing - do not silently continue with incomplete build.
if ! ls "$LIVE/config/hooks/normal/"*.hook.chroot >/dev/null 2>&1; then
  echo "ERROR: no hook scripts found in $LIVE/config/hooks/normal/" >&2
  exit 1
fi
chmod +x "$LIVE/config/hooks/normal/"*.hook.chroot

mkdir -p "$OUT_DIR"

echo "Running Debian live-build in Docker (linux/amd64)."
echo "The chroot is built on the container filesystem (not a macOS bind mount),"
echo "because debootstrap needs mknod. This can take a while…"

# Bind mounts on Docker Desktop for Mac are nodev/noexec — debootstrap
# cannot mknod there. Copy the tree onto the container disk, build, copy ISO out.
docker run --rm --privileged --platform linux/amd64 \
  -e BEAMO_WIPE_VERSION="$VERSION" \
  -e BEAMO_WIPE_ISO_NAME="$ISO_NAME" \
  -v "$ROOT":/src:ro \
  -v "$OUT_DIR":/out \
  debian:bookworm \
  bash /src/packaging/live/inside-docker.sh

if [ ! -f "$OUT_DIR/$ISO_NAME" ]; then
  echo "live-build finished but $OUT_DIR/$ISO_NAME was not written." >&2
  exit 1
fi
echo "Wrote $OUT_DIR/$ISO_NAME"
ls -lh "$OUT_DIR/$ISO_NAME"
# Generate provenance manifest (fails closed on dirty/placeholder/missing checksum)
# In CI, git is clean; locally, allow dirty with ALLOW_DIRTY=1 but still verify.
if [ "${SKIP_MANIFEST:-0}" != "1" ]; then
  echo "Generating release manifest..."
  BEAMO_WIPE_VERSION="$VERSION" ./scripts/generate-release-manifest.sh "dist/beamo-wipe-${VERSION}-amd64.manifest.json"
  echo "Manifest: dist/beamo-wipe-${VERSION}-amd64.manifest.json"
  ls -lh "dist/beamo-wipe-${VERSION}-amd64.manifest.json" "dist/beamo-wipe-${VERSION}-amd64.manifest.json.sha256" "dist/beamo-wipe-${VERSION}-amd64.iso.sha256" 2>&1 | head -n 20
fi
