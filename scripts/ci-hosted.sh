#!/usr/bin/env bash
# Hosted gate for Google Cloud Build (project beamo-wipe).
# This is the project's CI: lint, fake-disk tests, preview, negative test,
# amd64 ISO build, and controlled QEMU verification.
# Never execs nwipe on a real disk. Never deploys.
set -euo pipefail

ROOT="$(CDPATH='' cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export BEAMO_WIPE_DRY_RUN="${BEAMO_WIPE_DRY_RUN:-1}"
export DEBIAN_FRONTEND=noninteractive

PHASE="${1:-all}"
case "$PHASE" in
  lint|tests|preview|negative|iso|qemu|all) ;;
  *)
    printf 'usage: %s [lint|tests|preview|negative|iso|all|qemu]\n' "$0" >&2
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
    git \
    ca-certificates
  python3 -m pip install --break-system-packages -q 'pytest==9.0.3'
}

install_lint_deps() {
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends \
    ca-certificates \
    python3 \
    python3-pip \
    python3-setuptools \
    shellcheck
  python3 -m pip install --break-system-packages -q 'ruff==0.9.2' 'mypy==2.1.0'
}

install_preview_deps() {
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends python3 python3-tk
}

install_qemu_deps() {
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends \
    qemu-system-x86 \
    qemu-utils \
    ovmf \
    genisoimage \
    debsecan \
    file \
    sudo \
    python3 \
    python3-pytest \
    git \
    procps \
    util-linux \
    kmod \
    hdparm \
    build-essential \
    automake \
    autoconf \
    pkg-config \
    libncurses-dev \
    libparted-dev \
    libconfig-dev \
    ca-certificates
}

run_lint() {
  log "blocking syntax, shell and security lint"
  python3 -m compileall -q src/beamo_wipe
  shellcheck preview scripts/*.sh packaging/live/inside-docker.sh \
    packaging/live/config/hooks/normal/0500-build-nwipe.hook.chroot
  python3 -m ruff check --select S102,S103,S104,S105,S106,S107,S113,S307,S501,S506,S508,S602,S604,S605,S606,S608,S609,S610,S611,S612 src/beamo_wipe
  python3 -m ruff check --select S102,S103,S104,S107,S113,S307,S501,S506,S508,S602,S604,S605,S606,S608,S609,S610,S611,S612 tests
  log "advisory full lint and type report"
  python3 -m ruff check src/beamo_wipe tests || true
  python3 -m mypy --ignore-missing-imports src/beamo_wipe || true
  if grep -R --include="*.py" -n "TODO" src/beamo_wipe | grep -v "TODO:"; then
    log "warning: untracked TODO found; use 'TODO(#issue):' form"
  fi
}

run_pytest() {
  log "pytest under Xvfb 1600x1000 @ 72 DPI"
  # Two live-image tests need lb config (bootstrap/binary) from the ISO
  # build; skip them when those artifacts are absent.
  PYTEST_ARGS=()
  if [ ! -f packaging/live/config/bootstrap ] || [ ! -f packaging/live/config/binary ]; then
    log "skipping two live-image tests that need 'lb config' artifacts"
    PYTEST_ARGS=(-k "not test_iso_build_uses_https_debian_mirrors and not test_live_config_xinit_cannot_hijack_kiosk")
  fi
  xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest "${PYTEST_ARGS[@]}"
}

run_preview() {
  log "preview verification (fake disks, no browser)"
  BEAMO_WIPE_NO_OPEN=1 ./preview --web
  test -f web-preview/index.html
  BEAMO_WIPE_NO_OPEN=1 ./preview --console < /dev/null
  BEAMO_WIPE_NO_OPEN=1 ./preview --helper
}

run_negative() {
  log "negative test: broken boot-media safety must be rejected"
  safety_backup="$(mktemp /tmp/beamo-wipe-safety.XXXXXX)"
  cp src/beamo_wipe/safety.py "$safety_backup"
  restore_safety() {
    cp "$safety_backup" src/beamo_wipe/safety.py
    rm -f -- "$safety_backup"
  }
  trap restore_safety EXIT HUP INT TERM
  # NOTE: heredoc body stays at column 0 — Python rejects indented
  # top-level statements (IndentationError), which would fail the gate
  # before the patch is even applied.
  python3 - <<'PY'
import pathlib
p = pathlib.Path("src/beamo_wipe/safety.py")
t = p.read_text()
orig = 'def assert_boot_excluded(discovery: DiscoveryResult) -> None:\n    if not discovery.boot_identified or discovery.boot is None:\n        raise SafetyError(IDENTIFY_ERROR)'
broken = 'def assert_boot_excluded(discovery: DiscoveryResult) -> None:\n    if False:  # BROKEN for negative test\n        raise SafetyError(IDENTIFY_ERROR)'
if orig not in t:
    raise SystemExit("pattern not found for negative test")
p.write_text(t.replace(orig, broken))
print("patched safety.py: assert_boot_excluded now fail-open")
PY
  # This e2e test expects SafetyError when boot is uncertain, so it must
  # FAIL while broken. Capture the exit without a pipe (a pipe would
  # report tee/head's status and mask a passing-while-broken gate).
  negative_code=0
  BEAMO_WIPE_DRY_RUN=1 python3 -m pytest tests/test_boot_exclusion_fails_closed.py::test_e2e_no_nwipe_process_created_on_uncertainty -q || negative_code=$?
  restore_safety
  trap - EXIT HUP INT TERM
  if [ "$negative_code" -eq 0 ]; then
    printf 'NEGATIVE TEST FAILED: broken safety was NOT caught\n' >&2
    exit 1
  fi
  log "broken safety correctly rejected; verifying clean tree passes"
  BEAMO_WIPE_DRY_RUN=1 python3 -m pytest tests/test_boot_exclusion_fails_closed.py::test_e2e_no_nwipe_process_created_on_uncertainty -q
  log "negative test PASS: safety gate blocks bypass"
}

inspect_iso() {
  local iso version size magic
  version="${BEAMO_WIPE_VERSION:-0.2.1}"
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
  if [ "${SKIP_ISO:-false}" = "true" ]; then
    log "ISO step skipped via SKIP_ISO=true"
    return 0
  fi
  log "build amd64 live ISO (privileged Docker; no host disks wiped)"
  ./scripts/build-iso.sh
  inspect_iso
}

run_qemu() {
  install -d -m 0700 "$ROOT/qemu-evidence"
  if [ "${SKIP_QEMU:-false}" = "true" ]; then
    log "QEMU step skipped via SKIP_QEMU=true"
    echo "skipped via SKIP_QEMU=true" > "$ROOT/qemu-evidence/SKIPPED.txt"
    return 0
  fi
  log "controlled QEMU verification (disposable qcow2, TCG where KVM absent)"
  BEAMO_WIPE_VERSION="${BEAMO_WIPE_VERSION:-0.2.1}" ./scripts/qemu-verify.sh
  # Copy private temporary evidence into the ignored workspace directory for
  # the explicit post-QEMU publisher. Verification-only builds discard it.
  evidence_source="$(cat "$ROOT/qemu-evidence/PATH" 2>/dev/null || true)"
  if [ -z "$evidence_source" ] || [ ! -d "$evidence_source" ]; then
    echo "QEMU evidence directory was not reported" >&2
    exit 1
  fi
  cp -r "$evidence_source/." "$ROOT/qemu-evidence/"
  log "QEMU evidence copied to qemu-evidence/"
}

case "$PHASE" in
  lint)
    install_lint_deps
    run_lint
    ;;
  tests)
    install_test_deps
    run_pytest
    ;;
  preview)
    install_preview_deps
    run_preview
    ;;
  negative)
    install_test_deps
    run_negative
    ;;
  iso)
    run_iso
    ;;
  qemu)
    install_qemu_deps
    run_qemu
    ;;
  all)
    install_lint_deps
    run_lint
    install_test_deps
    run_pytest
    run_preview
    run_negative
    run_iso
    install_qemu_deps
    run_qemu
    ;;
esac

log "PASS phase=$PHASE"
