#!/usr/bin/env bash
# Per-boot services for Cursor Cloud Agent VMs.
# Starts nested dockerd (fuse-overlayfs) and Xvfb :99 at 72 DPI for Tk tests.
# Idempotent: skips anything already running. Does not run nwipe or build the ISO.
# Do not bind Xvfb to :1 — that display is computer-use / VNC at 96 DPI.
set -euo pipefail

LOG_DIR="${TMPDIR:-/tmp}/beamo-wipe-env"
mkdir -p "$LOG_DIR"

docker_ready() {
  if docker info >/dev/null 2>&1; then
    return 0
  fi
  sudo docker info >/dev/null 2>&1
}

start_dockerd() {
  if docker_ready; then
    return 0
  fi
  if command -v service >/dev/null 2>&1 && sudo service docker start >/dev/null 2>&1; then
    :
  else
    # Nested Cloud VMs often have no systemd; run dockerd directly.
    # Log under /tmp — /var/log/dockerd.log is not writable for this user.
    sudo dockerd >>"$LOG_DIR/dockerd.log" 2>&1 &
  fi
  for _ in $(seq 1 30); do
    if docker_ready; then
      return 0
    fi
    sleep 1
  done
  echo "Docker daemon did not become ready. ISO builds will not work until it does." >&2
  echo "See $LOG_DIR/dockerd.log" >&2
  return 1
}

start_xvfb() {
  if [ -S /tmp/.X11-unix/X99 ]; then
    return 0
  fi
  if pgrep -x Xvfb >/dev/null 2>&1 && DISPLAY=:99 xdpyinfo >/dev/null 2>&1; then
    return 0
  fi
  Xvfb :99 -screen 0 1600x1000x24 -dpi 72 >>"$LOG_DIR/xvfb-99.log" 2>&1 &
  for _ in $(seq 1 20); do
    if DISPLAY=:99 xdpyinfo >/dev/null 2>&1 || [ -S /tmp/.X11-unix/X99 ]; then
      return 0
    fi
    sleep 0.25
  done
  echo "Xvfb :99 did not start (72 DPI Tk tests need it)." >&2
  echo "See $LOG_DIR/xvfb-99.log" >&2
  return 1
}

# Nested Cloud VMs often own /dev/kvm as root:rdma. Group membership from
# install.sh only applies on a new session; chmod lets QEMU -enable-kvm work now.
if [ -e /dev/kvm ] && [ ! -w /dev/kvm ]; then
  sudo chmod a+rw /dev/kvm || true
fi

# Nested Docker/ISO is optional. Xvfb :99 is required for Tk pytest.
start_dockerd || true
start_xvfb
echo "Beamo Wipe Cloud start complete (Xvfb :99 @ 72 DPI; dockerd optional)."
