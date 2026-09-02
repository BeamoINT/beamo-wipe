#!/bin/sh
# Generate machine-readable release manifest. Fails closed on dirty/placeholder.
set -eu
ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VERSION="${BEAMO_WIPE_VERSION:-0.1.1}"
DEST="${1:-dist/beamo-wipe-${VERSION}-amd64.manifest.json}"

# Fail on uncommitted state unless explicitly allowed for local dev
if [ "${ALLOW_DIRTY:-0}" != "1" ]; then
  if [ -n "$(git status --porcelain)" ]; then
    echo "ERROR: uncommitted source state (git status --porcelain not empty)" >&2
    git status --short >&2 | head -n 20
    echo "Commit or stash, or set ALLOW_DIRTY=1 for local dev" >&2
    exit 2
  fi
fi

# Generate via Python
python3 - <<PY
import os, pathlib, sys
sys.path.insert(0, "src")
from beamo_wipe.release_manifest import generate_manifest, write_manifest
strict = os.environ.get("ALLOW_DIRTY") != "1"
manifest = generate_manifest(version="$VERSION", strict=strict)
dest = pathlib.Path("$DEST")
out = write_manifest(manifest, dest)
# Verify only when strict (dirty not allowed); local ALLOW_DIRTY skips dirty check
if strict:
    from beamo_wipe.release_manifest import verify_manifest
    verify_manifest(out)
    print(f"Verified {out} (strict)")
else:
    print(f"Wrote {out} (dirty allowed, skip strict verify)")
print(f"Manifest SHA256: {out.read_text().split()}")
import json, hashlib
sidecar = pathlib.Path(str(out) + ".sha256")
print(f"Sidecar {sidecar}: {sidecar.read_text().strip()}")
PY

echo "Manifest verified: $DEST"
ls -lh "$DEST" "${DEST}.sha256" 2>&1 | head -n 10
# Verify checksum publication (from dist/ directory so sidecar's bare filename resolves)
( cd "$(dirname "$DEST")" && sha256sum -c "$(basename "${DEST}.sha256")" 2>&1 | head )
# Also ensure ISO sidecar exists and verifies
ISO="dist/beamo-wipe-${VERSION}-amd64.iso"
if [ -f "$ISO" ]; then
  if [ ! -f "${ISO}.sha256" ]; then
    sha256sum "$ISO" > "${ISO}.sha256"
  fi
  ( cd "$(dirname "$ISO")" && sha256sum -c "$(basename "${ISO}.sha256")" 2>&1 | head )
  # Update SHA256SUMS for consumer
  ( cd dist && sha256sum "beamo-wipe-${VERSION}-amd64.iso" "beamo-wipe-${VERSION}-amd64.manifest.json" > SHA256SUMS 2>&1 | head || true )
  ( cd dist && sha256sum -c SHA256SUMS 2>&1 | head )
  echo "Consumer: sha256sum -c beamo-wipe-${VERSION}-amd64.iso.sha256 (from dist/)"
  echo "Consumer: sha256sum -c SHA256SUMS (from dist/)"
else
  echo "WARN: ISO $ISO not found; manifest still links to it but build should have produced it" >&2
fi
