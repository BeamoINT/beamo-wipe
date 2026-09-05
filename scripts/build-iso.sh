#!/bin/sh
# Build a bootable x86_64 ISO that auto-starts Beamo Wipe.
# Requires Docker. Does not wipe any host disk.
set -eu

ROOT="$(CDPATH='' cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VERSION="${BEAMO_WIPE_VERSION:-0.2.2}"
case "$VERSION" in
  ''|*[!0-9.]*|.*|*..*|*.) echo "Invalid BEAMO_WIPE_VERSION" >&2; exit 2 ;;
esac
if [ "$(printf '%s' "$VERSION" | awk -F. '{print NF}')" -ne 3 ]; then
  echo "Invalid BEAMO_WIPE_VERSION" >&2
  exit 2
fi
OUT_DIR="$ROOT/dist"
ISO_NAME="beamo-wipe-${VERSION}-amd64.iso"
LIVE="$ROOT/packaging/live"

missing=""
for tool in docker awk git python3 sha256sum; do
  command -v "$tool" >/dev/null 2>&1 || missing="$missing $tool"
done
if [ -n "$missing" ]; then
  echo "Missing required tools:$missing" >&2
  echo "Install Docker plus the listed provenance tools and re-run ./scripts/build-iso.sh" >&2
  exit 2
fi
WRAPPER_VERSION="$(PYTHONPATH="$ROOT/src" python3 -c 'import beamo_wipe; print(beamo_wipe.__version__)')"
if [ "$VERSION" != "$WRAPPER_VERSION" ]; then
  echo "BEAMO_WIPE_VERSION $VERSION does not match wrapper $WRAPPER_VERSION" >&2
  exit 2
fi

DOCKER_INFO="$(mktemp "${TMPDIR:-/tmp}/beamo-wipe-docker.XXXXXX")"
BUILD_OUT=""
BACKUP_DIR=""
bundle_in_progress=0
BUNDLE_FILES="$ISO_NAME beamo-wipe-${VERSION}-amd64.manifest.json beamo-wipe-${VERSION}-amd64.manifest.json.sha256 beamo-wipe-${VERSION}-amd64.iso.sha256 SHA256SUMS"
cleanup() {
  rc=$?
  if [ "$bundle_in_progress" -gt 0 ] && [ -n "$BACKUP_DIR" ]; then
    for name in $BUNDLE_FILES; do
      if [ "$bundle_in_progress" -eq 2 ]; then rm -f -- "$OUT_DIR/$name"; fi
      if [ -f "$BACKUP_DIR/$name" ]; then
        mv -- "$BACKUP_DIR/$name" "$OUT_DIR/$name" || true
      fi
    done
  fi
  rm -f -- "$DOCKER_INFO"
  if [ -n "$BUILD_OUT" ]; then rm -f -- "$BUILD_OUT/$ISO_NAME"; rmdir "$BUILD_OUT" 2>/dev/null || :; fi
  if [ -n "$BACKUP_DIR" ]; then rmdir "$BACKUP_DIR" 2>/dev/null || :; fi
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
if ! docker info >"$DOCKER_INFO" 2>&1; then
  echo "Docker is installed but not running, or this user cannot talk to the daemon." >&2
  echo "--- docker info output ---" >&2
  tail -n 40 "$DOCKER_INFO" >&2 || true
  echo "Next: start Docker Desktop, check 'docker context ls' and permissions, then retry." >&2
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

# Stage only Git-tracked wrapper files. Ignored/untracked executable bytes can
# never enter the ISO, while an explicit ALLOW_DIRTY local build can still test
# modifications to already tracked files.
git ls-files -- src/beamo_wipe | while IFS= read -r tracked; do
  rel="${tracked#src/beamo_wipe/}"
  mkdir -p "$STAGE_PY/$(dirname "$rel")"
  cp "$ROOT/$tracked" "$STAGE_PY/$rel"
done
# Bytecode is a local runtime artifact, not reviewed source. Never ship it.
find "$STAGE_PY" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
find "$STAGE_PY" -type d -name __pycache__ -empty -delete
# Record only bounded immutable build identity inside the live image.
PYTHONPATH="$ROOT/src" python3 - <<'PYIDENTITY'
import json, os, pathlib, re
from beamo_wipe.release_manifest import git_commit, git_dirty, live_build_inputs
build_id = os.environ.get("BUILD_ID", "local")
if not re.fullmatch(r"(?:[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}|local)", build_id):
    raise SystemExit("Invalid build identity")
identity = {"source_commit": git_commit(), "source_dirty": git_dirty()[0],
            "source_sha256": live_build_inputs()["src/beamo_wipe/"], "build_id": build_id}
path = pathlib.Path("packaging/live/config/includes.chroot/usr/share/beamo-wipe/build-identity.json")
path.write_text(json.dumps(identity, sort_keys=True) + "\n", encoding="ascii")
PYIDENTITY
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
unexpected_hook="$(find "$LIVE/config/hooks/normal" -maxdepth 1 -type f -name '*.hook.chroot' ! -name '0500-build-nwipe.hook.chroot' -print -quit)"
if [ -n "$unexpected_hook" ]; then
  echo "ERROR: unapproved live-build hook: $unexpected_hook" >&2
  exit 1
fi
chmod +x "$LIVE/config/hooks/normal/"*.hook.chroot

mkdir -p "$OUT_DIR"
BUILD_OUT="$(mktemp -d "$OUT_DIR/.build-output.XXXXXX")"

echo "Running Debian live-build in Docker (linux/amd64)."
echo "The chroot is built on the container filesystem (not a macOS bind mount),"
echo "because debootstrap needs mknod. This can take a while…"

# Bind mounts on Docker Desktop for Mac are nodev/noexec — debootstrap
# cannot mknod there. Copy the tree onto the container disk, build, copy ISO out.
docker_status=0
BUILD_IMAGE="debian:bookworm@sha256:6ebd97fa83deb272194a2cf015b3d26a4d538e9ad3a7a79d544c8af5b0a01443"
docker run --rm --privileged --platform linux/amd64 \
  -e BEAMO_WIPE_VERSION="$VERSION" \
  -e BEAMO_WIPE_ISO_NAME="$ISO_NAME" \
  -v "$ROOT":/src:ro \
  -v "$BUILD_OUT":/out \
  "$BUILD_IMAGE" \
  bash /src/packaging/live/inside-docker.sh || docker_status=$?
if [ "$docker_status" -ne 0 ]; then
  echo "ERROR: live-build container failed (exit $docker_status); no ISO was produced." >&2
  echo "Next: re-run with a clean Docker daemon, check disk space and network," >&2
  echo "then retry ./scripts/build-iso.sh. Staged files under packaging/live/config/includes.* are gitignored and safe to leave." >&2
  exit 1
fi

if [ ! -f "$BUILD_OUT/$ISO_NAME" ]; then
  echo "live-build finished but staged $ISO_NAME was not written." >&2
  exit 1
fi
BACKUP_DIR="$(mktemp -d "$OUT_DIR/.bundle-backup.XXXXXX")"
bundle_in_progress=1
for name in $BUNDLE_FILES; do
  if [ -f "$OUT_DIR/$name" ]; then
    mv -- "$OUT_DIR/$name" "$BACKUP_DIR/$name"
  fi
done
bundle_in_progress=2
mv -- "$BUILD_OUT/$ISO_NAME" "$OUT_DIR/$ISO_NAME"
echo "Wrote $OUT_DIR/$ISO_NAME"
ls -lh "$OUT_DIR/$ISO_NAME"
# Generate provenance manifest (fails closed on dirty/placeholder/missing
# checksum). There is deliberately no environment bypass: every ISO build is
# bound to verified provenance. Locally, ALLOW_DIRTY=1 relaxes only the clean
# tree requirement and still verifies every artifact checksum.
echo "Generating release manifest..."
BEAMO_WIPE_VERSION="$VERSION" ./scripts/generate-release-manifest.sh "dist/beamo-wipe-${VERSION}-amd64.manifest.json"
echo "Manifest: dist/beamo-wipe-${VERSION}-amd64.manifest.json"
for _f in "dist/beamo-wipe-${VERSION}-amd64.manifest.json" "dist/beamo-wipe-${VERSION}-amd64.manifest.json.sha256" "dist/beamo-wipe-${VERSION}-amd64.iso.sha256" "dist/SHA256SUMS"; do
  if [ ! -f "$_f" ]; then
    echo "ERROR: missing provenance file $_f" >&2
    exit 1
  fi
done
bundle_in_progress=0
for name in $BUNDLE_FILES; do rm -f -- "$BACKUP_DIR/$name"; done
ls -lh "dist/beamo-wipe-${VERSION}-amd64.manifest.json" "dist/beamo-wipe-${VERSION}-amd64.manifest.json.sha256" "dist/beamo-wipe-${VERSION}-amd64.iso.sha256" "dist/SHA256SUMS"
