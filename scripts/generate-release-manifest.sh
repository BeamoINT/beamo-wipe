#!/bin/sh
# Generate machine-readable release manifest. Fails closed on dirty/placeholder.
set -eu
ROOT="$(CDPATH='' cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VERSION="${BEAMO_WIPE_VERSION:-0.2.2}"
DEST="${1:-dist/beamo-wipe-${VERSION}-amd64.manifest.json}"
EXPECTED_DEST="dist/beamo-wipe-${VERSION}-amd64.manifest.json"
case "$VERSION" in
  ''|*[!0-9.]*|.*|*..*|*.) echo "ERROR: invalid BEAMO_WIPE_VERSION" >&2; exit 2 ;;
esac
if [ "$(printf '%s' "$VERSION" | awk -F. '{print NF}')" -ne 3 ] || [ "$DEST" != "$EXPECTED_DEST" ]; then
  echo "ERROR: invalid version or out-of-tree manifest destination" >&2
  exit 2
fi

# Fail on uncommitted state unless explicitly allowed for local dev
if [ "${ALLOW_DIRTY:-0}" != "1" ]; then
  if [ -n "$(git status --porcelain)" ]; then
    echo "ERROR: uncommitted source state (git status --porcelain not empty)" >&2
    echo "Commit the audited paths, or set ALLOW_DIRTY=1 for a local non-release build" >&2
    exit 2
  fi
fi

# Generate via Python. Values cross the shell->Python boundary through the
# environment, never through source interpolation: the heredoc is quoted so
# a crafted BEAMO_WIPE_VERSION cannot break out into Python exec.
BEAMO_WIPE_MANIFEST_VERSION="$VERSION" BEAMO_WIPE_MANIFEST_DEST="$DEST" python3 - <<'PY'
import os, pathlib, sys
sys.path.insert(0, "src")
from beamo_wipe.release_manifest import generate_manifest, write_manifest
strict = os.environ.get("ALLOW_DIRTY") != "1"
manifest = generate_manifest(version=os.environ["BEAMO_WIPE_MANIFEST_VERSION"], strict=strict)
dest = pathlib.Path(os.environ["BEAMO_WIPE_MANIFEST_DEST"])
out = write_manifest(manifest, dest)
# Always verify: with ALLOW_DIRTY only the dirty-state check is skipped, every
# other structural check (checksum, placeholders, nwipe pin, ISO checksum)
# still runs so a dirty-tree manifest cannot pass as clean provenance.
from beamo_wipe.release_manifest import verify_manifest
verify_manifest(out, allow_dirty=not strict)
print(f"Verified {out} (strict={strict})")
import hashlib
print(f"Manifest SHA256: {hashlib.sha256(out.read_bytes()).hexdigest()}")
sidecar = pathlib.Path(str(out) + ".sha256")
print(f"Sidecar written: {sidecar.name}")
PY

echo "Manifest written: $DEST (verifying checksums below)"
ls -lh "$DEST" "${DEST}.sha256"
# Verify checksum publication (from dist/ directory so sidecar's bare filename resolves).
# No `| head` on verify lines: under set -eu without pipefail the pipeline's
# status would be head's, and a mismatch would still print success and exit 0.
( cd "$(dirname "$DEST")" && sha256sum -c "$(basename "${DEST}.sha256")" )
# Also ensure ISO sidecar exists and verifies
ISO="dist/beamo-wipe-${VERSION}-amd64.iso"
if [ -f "$ISO" ]; then
  if [ ! -f "${ISO}.sha256" ]; then
    sha256sum "$ISO" > "${ISO}.sha256"
  fi
  ( cd "$(dirname "$ISO")" && sha256sum -c "$(basename "${ISO}.sha256")" )
  # Update SHA256SUMS for consumer (no masking: a generation failure must
  # fail the script under set -eu, not hide behind head/true and corrupt
  # SHA256SUMS with stderr; the next line verifies it).
  ( cd dist && sha256sum "beamo-wipe-${VERSION}-amd64.iso" "beamo-wipe-${VERSION}-amd64.manifest.json" > SHA256SUMS )
  ( cd dist && sha256sum -c SHA256SUMS )
  echo "Consumer: sha256sum -c beamo-wipe-${VERSION}-amd64.iso.sha256 (from dist/)"
  echo "Consumer: sha256sum -c SHA256SUMS (from dist/)"
else
  # Fail closed: a manifest that links to an ISO that was not produced must
  # never exit 0 (normally unreachable — iso_info already fails above — but
  # must stay fail-closed if generation semantics ever change).
  echo "ERROR: ISO $ISO not found but the manifest links to it; refusing to publish" >&2
  exit 2
fi
