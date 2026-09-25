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
  lint|tests|preview|desktop-launchers|negative|iso|qemu|all) ;;
  *)
    printf 'usage: %s [lint|tests|preview|desktop-launchers|negative|iso|qemu|all]\n' "$0" >&2
    exit 2
    ;;
esac

log() { printf '[ci-hosted] %s\n' "$*"; }

mkdir -p "$ROOT/.ci-cache/pip"
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$ROOT/.ci-cache/pip}"

install_test_deps() {
  if [ "${BEAMO_GATE_CHILD:-0}" = "1" ]; then return; fi
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends \
    xvfb \
    xauth libxtst6 \
    python3-tk dosfstools mtools \
    python3-gi gir1.2-gtk-3.0 librsvg2-common python3-pyatspi at-spi2-core dbus-x11 orca speech-dispatcher speech-dispatcher-espeak-ng pulseaudio \
    python3-pip \
    python3-setuptools \
    python3-qrcode \
    git \
    ca-certificates
  python3 -m pip install --break-system-packages -q 'pytest==9.0.3' 'cryptography==50.0.1'
}

install_lint_deps() {
  if [ "${BEAMO_GATE_CHILD:-0}" = "1" ]; then return; fi
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends \
    ca-certificates \
    python3 \
    python3-pip \
    python3-setuptools \
    git \
    shellcheck
  python3 -m pip install --break-system-packages -q 'ruff==0.9.2' 'mypy==2.1.0'
}

install_preview_deps() {
  if [ "${BEAMO_GATE_CHILD:-0}" = "1" ]; then return; fi
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends python3 python3-tk python3-qrcode python3-pytest nodejs git
}

install_desktop_meta() {
  # python3+git are required before ci_evidence can wrap ci-desktop.sh.
  if [ "${BEAMO_GATE_CHILD:-0}" = "1" ]; then return; fi
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends ca-certificates python3 git
}

install_qemu_deps() {
  if [ "${BEAMO_GATE_CHILD:-0}" = "1" ]; then return; fi
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends \
    qemu-system-x86 \
    qemu-utils \
    ovmf \
    genisoimage xorriso mtools syslinux syslinux-common \
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
    dosfstools \
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
  python3 -m compileall -q src/beamo_wipe dev.py scripts/build_desktop.py
  python3 -m ruff check dev.py scripts/build_desktop.py developer_tests
  python3 -m ruff format --check dev.py scripts/build_desktop.py developer_tests
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
  export BEAMO_ISOLATED_X11_TEST=1
  # Dedicated clean Xvfb + session for Orca. Not nested inside the suite
  # xvfb-run. Bookworm Orca 43 exceeds the in-suite 300s child wait when the
  # parent AT-SPI bus is already polluted; a timeout bump is forbidden.
  log "orca on a dedicated Xvfb 1600x1000 @ 72 DPI"
  dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" \
    env BEAMO_TEST_ORCA_CHILD=1 python3 -m pytest \
      tests/test_accessible_runtime.py::test_orca_announces_every_result
  export BEAMO_HOSTED_ORCA_SEPARATE=1
  log "pytest under Xvfb 1600x1000 @ 72 DPI"
  # Live-image tests that need lb config artifacts skip themselves when
  # packaging/live/config/{bootstrap,binary} are absent. Source assertions
  # for HTTPS mirrors and nox11autologin always run.
  dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest \
    --deselect=tests/test_accessible_runtime.py::test_orca_announces_every_result \
    --junitxml="${BEAMO_GATE_JUNIT:-$ROOT/dist/evidence/tests.xml}"
}

run_preview() {
  log "preview verification (fake disks, no browser)"
  BEAMO_WIPE_NO_OPEN=1 ./preview --web
  test -f web-preview/index.html
  # The generated page embeds its JavaScript. Parse every supported language;
  # HTML existence alone can pass even when the click-through cannot run.
  command -v node >/dev/null || {
    printf 'Node.js is required for preview JavaScript validation\n' >&2
    return 1
  }
  python3 -m pytest -q tests/test_gallery_script_syntax_pass5.py
  BEAMO_WIPE_NO_OPEN=1 ./preview --console < /dev/null
  BEAMO_WIPE_NO_OPEN=1 ./preview --helper
}

run_desktop() {
  log "desktop launchers (Go race/vet/fuzz + pinned Windows compile; fake firmware)"
  ./scripts/ci-desktop.sh
}

run_negative() {
  log "negative test: broken boot-media safety must be rejected"
  # Run the mutant from a private import root. A hosted or shared-checkout
  # negative gate must never expose a fail-open safety.py to other processes.
  negative_dir="$(mktemp -d "${TMPDIR:-/tmp}/beamo-wipe-negative.XXXXXX")"
  trap 'rm -rf -- "$negative_dir"' EXIT HUP INT TERM
  cp -R src/beamo_wipe "$negative_dir/beamo_wipe"
  # pyproject.toml adds src to the front of pytest's import path. Override
  # that setting here so the private mutant, not the pristine tree, is tested.
  printf '[pytest]\n' > "$negative_dir/pytest.ini"
  # NOTE: heredoc body stays at column 0 — Python rejects indented
  # top-level statements (IndentationError), which would fail the gate
  # before the patch is even applied.
  python3 - "$negative_dir/beamo_wipe/safety.py" <<'PY'
import pathlib
import sys
p = pathlib.Path(sys.argv[1])
t = p.read_text()
orig = 'def assert_boot_excluded(discovery: DiscoveryResult) -> None:\n    if discovery.boot_identified is not True or discovery.boot is None:\n        raise SafetyError(_copy.IDENTIFY_ERROR)'
broken = 'def assert_boot_excluded(discovery: DiscoveryResult) -> None:\n    if False:  # BROKEN for negative test\n        raise SafetyError(_copy.IDENTIFY_ERROR)'
if orig not in t:
    raise SystemExit("pattern not found for negative test")
p.write_text(t.replace(orig, broken))
print("patched safety.py: assert_boot_excluded now fail-open")
PY
  # This fake inventory has a boot object and a selectable target but marks
  # boot identity uncertain. With the guard removed, every later check passes.
  # Require the specific missing-exception failure so an import error or crash
  # cannot impersonate successful mutation coverage.
  negative_code=0
  negative_output="$(BEAMO_WIPE_DRY_RUN=1 PYTHONPATH="$negative_dir:$PYTHONPATH" python3 -m pytest -c "$negative_dir/pytest.ini" tests/test_boot_exclusion_fails_closed.py::test_boot_guard_rejects_false_identity_with_otherwise_selectable_target -q 2>&1)" || negative_code=$?
  printf '%s\n' "$negative_output"
  rm -rf -- "$negative_dir"
  trap - EXIT HUP INT TERM
  if [ "$negative_code" -ne 1 ]; then
    printf 'NEGATIVE TEST FAILED: broken safety did not produce the expected test failure (exit %s)\n' "$negative_code" >&2
    exit 1
  fi
  case "$negative_output" in
    *"DID NOT RAISE"*) ;;
    *) printf 'NEGATIVE TEST FAILED: expected missing SafetyError proof\n' >&2; exit 1 ;;
  esac
  log "broken private safety copy correctly rejected; verifying source passes"
  BEAMO_WIPE_DRY_RUN=1 python3 -m pytest tests/test_boot_exclusion_fails_closed.py::test_boot_guard_rejects_false_identity_with_otherwise_selectable_target -q
  log "negative test PASS: safety gate blocks bypass"
}

inspect_iso() {
  local iso version size magic
  version="${BEAMO_WIPE_VERSION:-0.2.9}"
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
  if [ -L "$ROOT/qemu-evidence" ]; then
    echo "QEMU evidence directory is a symlink" >&2
    return 1
  fi
  install -d -m 0700 "$ROOT/qemu-evidence"
  # A leftover regular file also contaminates the gate's hashed inventory.
  # Require an empty, no-follow output directory before either run mode.
  python3 - "$ROOT/qemu-evidence" <<'PY'
import os
import sys

directory_fd = os.open(sys.argv[1], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
try:
    if os.listdir(directory_fd):
        raise SystemExit("stale QEMU evidence; use a fresh build workspace")
finally:
    os.close(directory_fd)
PY
  if [ "${SKIP_QEMU:-false}" = "true" ]; then
    log "QEMU step skipped via SKIP_QEMU=true"
    # An older skip marker must not redirect this write through a symlink or
    # impersonate a fresh gate result. Open a new file in the checked directory.
    python3 - "$ROOT/qemu-evidence" <<'PY'
import os
import sys

directory_fd = os.open(sys.argv[1], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
try:
    marker_fd = os.open(
        "SKIPPED.txt", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600, dir_fd=directory_fd,
    )
    with os.fdopen(marker_fd, "w", encoding="ascii") as marker:
        marker.write("skipped via SKIP_QEMU=true\n")
        marker.flush()
        os.fsync(marker.fileno())
    if os.listdir(directory_fd) != ["SKIPPED.txt"]:
        raise SystemExit("QEMU evidence output changed during skip")
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
PY
    return 0
  fi
  log "controlled QEMU verification (disposable qcow2, TCG where KVM absent)"
  ./scripts/build-usb-image.sh
  local qemu_code=0
  BEAMO_WIPE_VERSION="${BEAMO_WIPE_VERSION:-0.2.9}" ./scripts/qemu-verify.sh || qemu_code=$?
  # Copy private temporary evidence into the ignored workspace directory for
  # the explicit post-QEMU publisher. Verification-only builds discard it.
  if [ -L "$ROOT/qemu-evidence/PATH" ] || [ ! -f "$ROOT/qemu-evidence/PATH" ]; then
    echo "QEMU evidence path is unsafe" >&2
    return 1
  fi
  evidence_source="$(python3 - "$ROOT/qemu-evidence" <<'PY'
import os
import stat
import sys

directory_fd = os.open(sys.argv[1], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
try:
    receipt_fd = os.open(
        "PATH", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
        dir_fd=directory_fd,
    )
    with os.fdopen(receipt_fd, "rb") as receipt:
        metadata = os.fstat(receipt.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise SystemExit("unsafe QEMU evidence path receipt")
        raw = receipt.read(4097)
    if len(raw) > 4096 or not raw.endswith(b"\n") or b"\n" in raw[:-1]:
        raise SystemExit("invalid QEMU evidence path receipt")
    path = os.fsdecode(raw[:-1])
    if not os.path.isabs(path):
        raise SystemExit("invalid QEMU evidence directory path")
    print(path)
finally:
    os.close(directory_fd)
PY
)"
  if [ -z "$evidence_source" ] || [ ! -d "$evidence_source" ]; then
    echo "QEMU evidence directory was not reported" >&2
    exit 1
  fi
  # GNU cp follows an existing destination file link, even with -r. Evidence
  # is a flat set of private logs; copy each new regular file by directory fd
  # so a planted output cannot redirect bytes outside qemu-evidence.
  python3 - "$evidence_source" "$ROOT/qemu-evidence" <<'PY'
import os
import shutil
import stat
import sys

flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
source_fd = os.open(sys.argv[1], flags)
try:
    output_fd = os.open(sys.argv[2], flags)
    try:
        def identity(metadata):
            return (
                metadata.st_dev, metadata.st_ino, metadata.st_size,
                metadata.st_mtime_ns, metadata.st_ctime_ns,
            )

        source_names = sorted(os.listdir(source_fd))
        source_states = {}
        output_states = {}
        for name in source_names:
            source_file_fd = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=source_fd,
            )
            with os.fdopen(source_file_fd, "rb") as source_file:
                before = os.fstat(source_file.fileno())
                if not stat.S_ISREG(before.st_mode):
                    raise RuntimeError(f"unsafe QEMU evidence source: {name}")
                output_file_fd = os.open(
                    name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600, dir_fd=output_fd,
                )
                with os.fdopen(output_file_fd, "wb") as output_file:
                    shutil.copyfileobj(source_file, output_file)
                    output_file.flush()
                    os.fsync(output_file.fileno())
                    output_after = os.fstat(output_file.fileno())
                after = os.fstat(source_file.fileno())
                named_source = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
                if (identity(before) != identity(after)
                        or identity(before) != identity(named_source)):
                    raise RuntimeError(f"QEMU evidence changed during copy: {name}")
                named_output = os.stat(name, dir_fd=output_fd, follow_symlinks=False)
                if (not stat.S_ISREG(named_output.st_mode)
                        or identity(output_after) != identity(named_output)
                        or output_after.st_size != before.st_size):
                    raise RuntimeError(f"QEMU evidence changed during copy: {name}")
                source_states[name] = identity(before)
                output_states[name] = identity(output_after)
        if sorted(os.listdir(source_fd)) != source_names:
            raise RuntimeError("QEMU evidence changed during copy")
        if sorted(os.listdir(output_fd)) != sorted(["PATH", *source_names]):
            raise RuntimeError("QEMU evidence output changed during copy")
        for name in source_names:
            source_now = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
            output_now = os.stat(name, dir_fd=output_fd, follow_symlinks=False)
            if (identity(source_now) != source_states[name]
                    or not stat.S_ISREG(source_now.st_mode)
                    or identity(output_now) != output_states[name]
                    or not stat.S_ISREG(output_now.st_mode)):
                raise RuntimeError(f"QEMU evidence changed during copy: {name}")
        for directory, fd in ((sys.argv[1], source_fd), (sys.argv[2], output_fd)):
            opened = os.fstat(fd)
            current = os.stat(directory, follow_symlinks=False)
            if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                raise RuntimeError("QEMU evidence directory changed during copy")
        os.fsync(output_fd)
    finally:
        os.close(output_fd)
finally:
    os.close(source_fd)
PY
  log "QEMU evidence copied to qemu-evidence/"
  return "$qemu_code"
}

record_gate() {
  local gate="$1" action="$2"
  if [ "${BEAMO_GATE_CHILD:-0}" = "1" ]; then
    "$action"
  else
    python3 -m beamo_wipe.ci_evidence "$gate"
  fi
}

case "$PHASE" in
  lint)
    install_lint_deps
    record_gate lint run_lint
    ;;
  tests)
    install_test_deps
    record_gate tests run_pytest
    ;;
  preview)
    install_preview_deps
    record_gate preview run_preview
    ;;
  desktop-launchers)
    install_desktop_meta
    record_gate desktop-launchers run_desktop
    ;;
  negative)
    install_test_deps
    record_gate negative run_negative
    ;;
  iso)
    record_gate iso run_iso
    ;;
  qemu)
    install_qemu_deps
    record_gate qemu run_qemu
    ;;
  all)
    install_lint_deps
    record_gate lint run_lint
    install_test_deps
    record_gate tests run_pytest
    record_gate preview run_preview
    record_gate desktop-launchers run_desktop
    record_gate negative run_negative
    record_gate iso run_iso
    install_qemu_deps
    record_gate qemu run_qemu
    ;;
esac

log "PASS phase=$PHASE"
