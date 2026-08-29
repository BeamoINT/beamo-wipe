#!/usr/bin/env bash
# Fast, safe smoke that the Cloud VM is ready for Beamo Wipe development.
# Runs pytest on fake lsblk JSON and preview with fake disks.
# Never execs nwipe on a real disk. Does not build or boot the live ISO.
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export BEAMO_WIPE_DRY_RUN=1
export BEAMO_WIPE_DEMO=1

fail=0
note() { printf '%s\n' "$*"; }
ok() { printf 'OK  %s\n' "$*"; }
warn() { printf 'WARN  %s\n' "$*"; }
bad() { printf 'FAIL  %s\n' "$*"; fail=1; }

note "Beamo Wipe Cloud check"
note "host: $(uname -s) $(uname -m)"

if [ "$(uname -s)" != "Linux" ] || [ "$(uname -m)" != "x86_64" ]; then
  bad "expected Linux x86_64"
fi

if python3 --version; then
  ok "python3 $(python3 --version | awk '{print $2}')"
else
  bad "python3 missing"
fi

if python3 -c "import tkinter; print(tkinter.TkVersion)"; then
  ok "tkinter"
else
  bad "python3-tk / tkinter missing"
fi

if python3 -m pytest --version >/dev/null; then
  ok "pytest $(python3 -m pytest --version | awk '{print $2}')"
else
  bad "pytest missing (install.sh should pip-install pytest>=8)"
fi

if [ -e /dev/kvm ]; then
  if [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
    ok "/dev/kvm present and writable (ISO QEMU can use KVM)"
  else
    warn "/dev/kvm exists but is not writable for $(id -un); use sudo for QEMU -enable-kvm (optional ISO path)"
  fi
else
  warn "/dev/kvm missing; pytest/preview still work, ISO QEMU will be TCG"
fi

docker_ok=0
if docker info >/dev/null 2>&1; then
  docker_ok=1
  ok "docker (current user)"
elif sudo docker info >/dev/null 2>&1; then
  docker_ok=1
  ok "docker via sudo (prefer this unless already in the docker group)"
else
  warn "Docker daemon not ready. ISO build is optional/manual: bash .cursor/start.sh, then ./scripts/build-iso.sh"
fi

if [ "$docker_ok" -eq 1 ]; then
  if [ -f /etc/docker/daemon.json ] && grep -q fuse-overlayfs /etc/docker/daemon.json; then
    ok "docker storage-driver fuse-overlayfs"
  else
    warn "/etc/docker/daemon.json does not mention fuse-overlayfs (nested overlay often fails)"
  fi
fi

# Two tests in tests/test_live_image.py read gitignored live-build outputs
# (config/bootstrap and config/binary) produced by lb config inside the ISO
# build. They fail on a fresh checkout; skip them unless those files exist.
pytest_k=()
if [ ! -f packaging/live/config/bootstrap ] || [ ! -f packaging/live/config/binary ]; then
  pytest_k=(-k "not test_iso_build_uses_https_debian_mirrors and not test_live_config_xinit_cannot_hijack_kiosk")
  warn "skipping two live-image tests that need lb config (optional ISO build)"
fi

# Tk layout tests are DPI-sensitive. Never use VNC DISPLAY=:1 (96 DPI).
note "pytest (fake lsblk; xvfb 72 DPI)"
if xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest "${pytest_k[@]}"; then
  ok "pytest"
else
  bad "pytest"
fi

note "preview --web (fake disks, no browser)"
if BEAMO_WIPE_NO_OPEN=1 ./preview --web >/tmp/beamo-wipe-preview-web.out; then
  gallery="$(tr -d '\r' </tmp/beamo-wipe-preview-web.out | tail -n 1)"
  if [ -f "$gallery" ]; then
    ok "preview --web wrote $gallery"
  else
    bad "preview --web exited 0 but did not write gallery HTML"
  fi
else
  bad "preview --web"
fi

note "preview --console (fake disks, stdin EOF — not a wipe)"
if ./preview --console </dev/null >/tmp/beamo-wipe-preview-console.out 2>/tmp/beamo-wipe-preview-console.err; then
  ok "preview --console exited 0 on EOF"
else
  # curses may return non-zero without a TTY; accept a printed splash instead.
  if grep -q "Beamo Wipe\|PREVIEW\|preview" /tmp/beamo-wipe-preview-console.out /tmp/beamo-wipe-preview-console.err 2>/dev/null; then
    warn "preview --console non-zero without a TTY (printed wizard copy; acceptable)"
  else
    bad "preview --console produced no wizard output"
  fi
fi

note "ISO: not built in this smoke (slow, nested live-build). Manual: ./scripts/build-iso.sh then docs/vm-test.md on a disposable qcow2."
note "nwipe is not invoked on any disk."

if [ "$fail" -ne 0 ]; then
  echo "Cloud check FAILED" >&2
  exit 1
fi
echo "Cloud check PASSED"
