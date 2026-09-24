#!/bin/sh
# Build a bootable x86_64 ISO that auto-starts Beamo Wipe.
# Requires Docker. Does not wipe any host disk.
set -eu

ROOT="$(CDPATH='' cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VERSION="${BEAMO_WIPE_VERSION:-0.2.9}"
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
same_regular_inode() {
  python3 - "$1" "$2" <<'PYINODE'
import os
import stat
import sys

try:
    first = os.stat(sys.argv[1], follow_symlinks=False)
    second = os.stat(sys.argv[2], follow_symlinks=False)
except OSError:
    raise SystemExit(1)
if not stat.S_ISREG(first.st_mode) or not stat.S_ISREG(second.st_mode):
    raise SystemExit(1)
raise SystemExit(0 if (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino) else 1)
PYINODE
}
require_prior_bundle_paths() {
  for name in $BUNDLE_FILES; do
    if [ -e "$OUT_DIR/$name" ] && [ ! -f "$OUT_DIR/$name" ] && [ ! -L "$OUT_DIR/$name" ]; then
      echo "Unsafe prior ISO bundle path: $OUT_DIR/$name" >&2
      return 1
    fi
  done
}
cleanup() {
  rc=$?
  if [ "$bundle_in_progress" -gt 0 ] && [ -n "$BACKUP_DIR" ]; then
    rollback_safe=1
    if [ "$bundle_in_progress" -eq 2 ]; then
      # The staged ISO remains as an inode receipt for the published hardlink.
      # Manifest sidecars are written in dist by the generator, so a pathname
      # present there after failure cannot be proven to belong to this build.
      if [ -e "$OUT_DIR/$ISO_NAME" ] || [ -L "$OUT_DIR/$ISO_NAME" ]; then
        if ! same_regular_inode "$OUT_DIR/$ISO_NAME" "$BUILD_OUT/$ISO_NAME"; then
          rollback_safe=0
        fi
      fi
      for name in $BUNDLE_FILES; do
        [ "$name" = "$ISO_NAME" ] && continue
        if [ -e "$OUT_DIR/$name" ] || [ -L "$OUT_DIR/$name" ]; then
          rollback_safe=0
        fi
      done
    fi
    if [ "$rollback_safe" -eq 0 ]; then
      echo "Could not safely roll back the ISO bundle; prior files are retained in $BACKUP_DIR" >&2
    fi
    for name in $BUNDLE_FILES; do
      if [ "$rollback_safe" -eq 1 ]; then
        if [ "$bundle_in_progress" -eq 2 ] && [ "$name" = "$ISO_NAME" ] &&
           same_regular_inode "$OUT_DIR/$name" "$BUILD_OUT/$ISO_NAME"; then
          rm -f -- "$OUT_DIR/$name"
        fi
        if [ -e "$BACKUP_DIR/$name" ] || [ -L "$BACKUP_DIR/$name" ]; then
          # Do not replace a path another process created during rollback.
          if [ ! -e "$OUT_DIR/$name" ] && [ ! -L "$OUT_DIR/$name" ]; then
            mv -- "$BACKUP_DIR/$name" "$OUT_DIR/$name" || true
          fi
        fi
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
python3 "$ROOT/scripts/stage_wrapper_sources.py" --prepare "$LIVE"

# Stage only Git-tracked wrapper files. Ignored/untracked executable bytes can
# never enter the ISO, while an explicit ALLOW_DIRTY local build can still test
# modifications to already tracked files.
python3 "$ROOT/scripts/stage_wrapper_sources.py" "$ROOT" "$STAGE_PY"
# Bytecode is a local runtime artifact, not reviewed source. The stager skips it.
# A local build compiles launchers; hosted CI supplies the exact tested pair.
if [ ! -f "$ROOT/dist/desktop/desktop-build.json" ]; then
  "$ROOT/scripts/build-desktop.sh"
fi
python3 - "$ROOT" "$WRAPPER_VERSION" <<'PYDESKTOP'
import pathlib,subprocess,sys
root=pathlib.Path(sys.argv[1]);out=root/'dist/desktop'
sys.path.insert(0,str(root/'scripts'))
from build_desktop import verify_desktop_bundle
source=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True).strip())
try:
    verify_desktop_bundle(root,out,source,sys.argv[2],dirty)
except RuntimeError as exc:
    raise SystemExit(str(exc)) from exc
PYDESKTOP
PYTHONPATH="$ROOT/src" python3 "$ROOT/scripts/stage_live_assets.py" "$ROOT" "$LIVE"

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

if [ ! -f "$BUILD_OUT/$ISO_NAME" ] || [ -L "$BUILD_OUT/$ISO_NAME" ]; then
  echo "live-build finished but staged $ISO_NAME was not written." >&2
  exit 1
fi
require_prior_bundle_paths
BACKUP_DIR="$(mktemp -d "$OUT_DIR/.bundle-backup.XXXXXX")"
bundle_in_progress=1
for name in $BUNDLE_FILES; do
  if [ -e "$OUT_DIR/$name" ] || [ -L "$OUT_DIR/$name" ]; then
    mv -- "$OUT_DIR/$name" "$BACKUP_DIR/$name"
    if [ ! -f "$BACKUP_DIR/$name" ] && [ ! -L "$BACKUP_DIR/$name" ]; then
      echo "Unsafe prior ISO bundle path changed during backup: $OUT_DIR/$name" >&2
      exit 1
    fi
  fi
done
bundle_in_progress=2
# os.link fails if the destination exists, including a directory or symlink.
# `ln source destination` can instead create a file inside a directory that
# another process put at the destination between backup and publication.
python3 -c 'import os, sys; os.link(sys.argv[1], sys.argv[2], follow_symlinks=False)' \
  "$BUILD_OUT/$ISO_NAME" "$OUT_DIR/$ISO_NAME"
echo "Wrote $OUT_DIR/$ISO_NAME"
ls -lh "$OUT_DIR/$ISO_NAME"
# Generate provenance manifest (fails closed on dirty/placeholder/missing
# checksum). This pre-QEMU manifest verifies artifact integrity only. The
# hosted gate finalizes release evidence after QEMU passes; the publisher
# rejects this preliminary manifest. ALLOW_DIRTY relaxes only source cleanliness.
echo "Generating release manifest..."
BEAMO_BUILD_PROVENANCE_ONLY=1 BEAMO_WIPE_VERSION="$VERSION" ./scripts/generate-release-manifest.sh "dist/beamo-wipe-${VERSION}-amd64.manifest.json"
echo "Manifest: dist/beamo-wipe-${VERSION}-amd64.manifest.json"
for _f in "dist/beamo-wipe-${VERSION}-amd64.manifest.json" "dist/beamo-wipe-${VERSION}-amd64.manifest.json.sha256" "dist/beamo-wipe-${VERSION}-amd64.iso.sha256" "dist/SHA256SUMS"; do
  if [ ! -f "$_f" ]; then
    echo "ERROR: missing provenance file $_f" >&2
    exit 1
  fi
done
# A replacement between manifest verification and finalization must not be
# reported as this build's ISO or cause its previous bundle to be discarded.
if ! same_regular_inode "$OUT_DIR/$ISO_NAME" "$BUILD_OUT/$ISO_NAME"; then
  echo "ERROR: published ISO was replaced before bundle finalization" >&2
  exit 1
fi
bundle_in_progress=0
for name in $BUNDLE_FILES; do
  if ! rm -f -- "$BACKUP_DIR/$name"; then
    echo "Could not remove prior ISO bundle backup: $BACKUP_DIR/$name" >&2
  fi
done
ls -lh "dist/beamo-wipe-${VERSION}-amd64.manifest.json" "dist/beamo-wipe-${VERSION}-amd64.manifest.json.sha256" "dist/beamo-wipe-${VERSION}-amd64.iso.sha256" "dist/SHA256SUMS"
