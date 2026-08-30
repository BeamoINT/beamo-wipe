#!/usr/bin/env bash
# Hosted gate for Google Cloud Build (project beamo-wipe).
# Never execs nwipe on a real disk. Never deploys.
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export BEAMO_WIPE_DRY_RUN="${BEAMO_WIPE_DRY_RUN:-1}"
export DEBIAN_FRONTEND=noninteractive

PHASE="${1:-all}"
case "$PHASE" in
  tests|iso|all) ;;
  *)
    printf 'usage: %s [tests|iso|all]\n' "$0" >&2
    exit 2
    ;;
esac

log() { printf '[ci-hosted] %s\n' "$*"; }

install_test_deps() {
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends \
    xvfb \
    xauth \
    python3-tk \
    python3-pip \
    python3-setuptools \
    ca-certificates
  python3 -m pip install --break-system-packages -q 'pytest>=8'
}

run_pytest() {
  log "pytest under Xvfb 1600x1000 @ 72 DPI"
  xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest
}

inspect_iso() {
  local iso version size magic
  version="${BEAMO_WIPE_VERSION:-0.1.0}"
  iso="$ROOT/dist/beamo-wipe-${version}-amd64.iso"
  [ -f "$iso" ] || {
    printf 'ISO missing: %s\n' "$iso" >&2
    exit 1
  }
  size=$(wc -c <"$iso")
  if [ "$size" -lt 83886080 ]; then
    printf 'ISO too small: %s bytes\n' "$size" >&2
    exit 1
  fi
  # ISO 9660 primary volume descriptor starts at sector 16 (offset 32768).
  magic=$(dd if="$iso" bs=1 skip=32769 count=5 2>/dev/null || true)
  if [ "$magic" != "CD001" ]; then
    printf 'not ISO 9660 (PVD magic %s)\n' "$magic" >&2
    exit 1
  fi
  log "ISO ok path=$iso bytes=$size pvd=CD001"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$iso"
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$iso"
  fi
}

run_iso() {
  log "build amd64 live ISO (privileged Docker; no host disks wiped)"
  ./scripts/build-iso.sh
  inspect_iso
}

case "$PHASE" in
  tests)
    install_test_deps
    run_pytest
    ;;
  iso)
    run_iso
    ;;
  all)
    install_test_deps
    run_pytest
    run_iso
    ;;
esac

log "PASS phase=$PHASE"
