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
require_output_directory() {
  if [ -L "$OUT_DIR" ] || { [ -e "$OUT_DIR" ] && [ ! -d "$OUT_DIR" ]; }; then
    echo 'A regular output directory is required.' >&2
    exit 2
  fi
}
require_output_directory
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
    # An old link is not an owned build output. Moving it to the backup and
    # later discarding that backup would silently remove the user's link.
    if [ -L "$OUT_DIR/$name" ] || { [ -e "$OUT_DIR/$name" ] && [ ! -f "$OUT_DIR/$name" ]; }; then
      echo "Unsafe prior ISO bundle path: $OUT_DIR/$name" >&2
      return 1
    fi
  done
}
verify_prior_bundle() {
  # A regular file at an output name is not proof that this builder owns it.
  # Check the complete prior bundle before replacing it, and check the moved
  # backup again so a same-user replacement during the long build is retained.
  python3 - "$1" "$VERSION" "${2:-$1}" <<'PYPRIOR'
import hashlib
import json
import os
import pathlib
import re
import stat
import sys

directory = pathlib.Path(sys.argv[1])
version = sys.argv[2]
reference_directory = pathlib.Path(sys.argv[3])
iso = f"beamo-wipe-{version}-amd64.iso"
manifest = f"beamo-wipe-{version}-amd64.manifest.json"
names = (iso, manifest, manifest + ".sha256", iso + ".sha256", "SHA256SUMS")


def read_regular(name, limit=None, base=directory):
    path = base / name
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError("non-regular bundle entry")
        if limit is None:
            digest = hashlib.sha256()
            size = 0
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
            result = (digest.hexdigest(), size)
        else:
            result = stream.read(limit + 1)
            if len(result) > limit:
                raise ValueError("oversized bundle entry")
    current = os.lstat(path)
    if not stat.S_ISREG(current.st_mode) or (
        opened.st_dev, opened.st_ino, opened.st_size
    ) != (current.st_dev, current.st_ino, current.st_size):
        raise ValueError("bundle entry changed while checking")
    return result


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate manifest key")
        result[key] = value
    return result


try:
    present = [name for name in names if (directory / name).exists() or (directory / name).is_symlink()]
    if not present:
        raise SystemExit(0)
    if present == ["SHA256SUMS"]:
        # SHA256SUMS is shared across versions. A newer build may replace a
        # verified checksum list for an older complete bundle; its own two
        # sidecars continue to preserve both old checksums. This also works
        # after the list moves to backup while old artifacts stay in dist.
        lines = read_regular("SHA256SUMS", 1024).decode("ascii").splitlines(keepends=True)
        if len(lines) != 2:
            raise ValueError("invalid previous-version checksum list")
        first = re.fullmatch(
            r"([0-9a-f]{64})  (beamo-wipe-([0-9]+\.[0-9]+\.[0-9]+)-amd64\.iso)\n",
            lines[0],
        )
        if first is None or tuple(map(int, first[3].split("."))) >= tuple(map(int, version.split("."))):
            raise ValueError("invalid previous-version ISO entry")
        old_iso, old_version, old_iso_sha = first[2], first[3], first[1]
        old_manifest = f"beamo-wipe-{old_version}-amd64.manifest.json"
        second = re.fullmatch(r"([0-9a-f]{64})  " + re.escape(old_manifest) + r"\n", lines[1])
        if second is None:
            raise ValueError("invalid previous-version manifest entry")
        old_manifest_sha = second[1]
        actual_iso_sha, old_size = read_regular(old_iso, base=reference_directory)
        old_raw = read_regular(old_manifest, 16 * 1024 * 1024, base=reference_directory)
        old_data = json.loads(old_raw.decode("utf-8"), object_pairs_hook=unique_fields)
        if not isinstance(old_data, dict):
            raise ValueError("invalid previous-version manifest")
        old_internal_sha = old_data.pop("_manifest_sha256", None)
        old_canonical = json.dumps(old_data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        if old_internal_sha != hashlib.sha256(old_canonical.encode("utf-8")).hexdigest():
            raise ValueError("previous-version manifest digest mismatch")
        old_artifact = old_data.get("artifact")
        if (
            not isinstance(old_artifact, dict)
            or old_data.get("beamo_wipe_version") != old_version
            or old_artifact.get("iso_name") != old_iso
            or old_artifact.get("iso_sha256") != old_iso_sha
            or type(old_artifact.get("iso_size_bytes")) is not int
            or old_artifact["iso_size_bytes"] != old_size
            or old_size <= 0
            or actual_iso_sha != old_iso_sha
            or hashlib.sha256(old_raw).hexdigest() != old_manifest_sha
        ):
            raise ValueError("previous-version bundle checksum mismatch")
        if read_regular(old_iso + ".sha256", 512, base=reference_directory) != lines[0].encode("ascii"):
            raise ValueError("previous-version ISO sidecar mismatch")
        if read_regular(old_manifest + ".sha256", 512, base=reference_directory) != lines[1].encode("ascii"):
            raise ValueError("previous-version manifest sidecar mismatch")
        raise SystemExit(0)
    if len(present) != len(names):
        raise ValueError("incomplete prior bundle")
    iso_sha, iso_size = read_regular(iso)
    if iso_size <= 0:
        raise ValueError("empty prior ISO")
    raw = read_regular(manifest, 16 * 1024 * 1024)

    data = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_fields)
    if not isinstance(data, dict):
        raise ValueError("invalid prior manifest")
    recorded = data.pop("_manifest_sha256", None)
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    if recorded != hashlib.sha256(canonical.encode("utf-8")).hexdigest():
        raise ValueError("prior manifest digest mismatch")
    artifact = data.get("artifact")
    if data.get("schema_version") != 2 or data.get("beamo_wipe_version") != version or not isinstance(artifact, dict):
        raise ValueError("prior manifest identity mismatch")
    if (artifact.get("iso_name") != iso or artifact.get("iso_path") != iso or
        artifact.get("iso_sha256_sidecar") != iso + ".sha256" or
        artifact.get("iso_sha256") != iso_sha or
        type(artifact.get("iso_size_bytes")) is not int or
        artifact["iso_size_bytes"] != iso_size):
        raise ValueError("prior ISO identity mismatch")
    manifest_sha = hashlib.sha256(raw).hexdigest()
    if read_regular(iso + ".sha256", 512) != f"{iso_sha}  {iso}\n".encode("ascii"):
        raise ValueError("prior ISO checksum mismatch")
    if read_regular(manifest + ".sha256", 512) != f"{manifest_sha}  {manifest}\n".encode("ascii"):
        raise ValueError("prior manifest checksum mismatch")
    expected_sums = f"{iso_sha}  {iso}\n{manifest_sha}  {manifest}\n".encode("ascii")
    if read_regular("SHA256SUMS", 1024) != expected_sums:
        raise ValueError("prior checksum list mismatch")
except (OSError, ValueError, UnicodeError, TypeError, KeyError) as exc:
    raise SystemExit(f"Unverified prior ISO bundle in {directory}; move it aside before rebuilding ({exc})")
PYPRIOR
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
require_prior_bundle_paths
verify_prior_bundle "$OUT_DIR"
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
# Bind the private container copy to the inputs that passed staging. The
# checkout can change while Docker's rsync reads it, then return to the
# original bytes before the later release-manifest check.
LIVE_INPUTS_SHA="$(PYTHONPATH="$ROOT/src" python3 - <<'PYLIVEINPUTS'
import hashlib
import json
from beamo_wipe.release_manifest import live_build_inputs

inventory = live_build_inputs()
raw = json.dumps(inventory, sort_keys=True, separators=(',', ':')).encode('ascii')
print(hashlib.sha256(raw).hexdigest())
PYLIVEINPUTS
)"

# Docker builds can run for a long time. Recheck before allocating or moving
# output in case the checkout's dist directory changed while it was running.
require_output_directory
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
  -e BEAMO_WIPE_LIVE_INPUTS_SHA="$LIVE_INPUTS_SHA" \
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

require_output_directory

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
    if [ -L "$BACKUP_DIR/$name" ] || [ ! -f "$BACKUP_DIR/$name" ]; then
      echo "Unsafe prior ISO bundle path changed during backup: $OUT_DIR/$name" >&2
      exit 1
    fi
  fi
done
verify_prior_bundle "$BACKUP_DIR" "$OUT_DIR"
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
  if [ ! -f "$_f" ] || [ -L "$_f" ]; then
    echo "ERROR: missing or linked provenance file $_f" >&2
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
