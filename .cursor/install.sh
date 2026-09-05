#!/usr/bin/env bash
# Idempotent Linux x86_64 bootstrap for Cursor Cloud Agent VMs.
# Prepares pytest, Tk/Xvfb preview, and QEMU packages.
# Nested Docker / fuse-overlayfs / ISO tooling is optional: a fuse3 conffile
# prompt (Cursor's agent-store-fuse already writes /etc/fuse.conf) must not
# abort the snapshot rebuild. Does not build the live ISO, does not start
# daemons, and never runs nwipe on a disk. Apple Silicon / macOS are out of scope.
set -euo pipefail

ROOT="$(CDPATH='' cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ "$(uname -s)" != "Linux" ] || [ "$(uname -m)" != "x86_64" ]; then
  echo "install.sh supports Linux x86_64 Cloud VMs only (got $(uname -s) $(uname -m))." >&2
  exit 1
fi

if ! command -v sudo >/dev/null 2>&1; then
  echo "sudo is required to install packages." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
export DEBCONF_NONINTERACTIVE_SEEN=true
export NEEDRESTART_MODE=l

# Keep existing conffiles (Cursor install-agent-store-fuse ships /etc/fuse.conf).
# Without this, dpkg hits "end of file on stdin at conffile prompt" and exits 100.
APT_DPKG_OPTS=(
  -o Dpkg::Options::=--force-confdef
  -o Dpkg::Options::=--force-confold
)

pkg_installed() {
  dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q 'install ok installed'
}

apt_install_required() {
  sudo apt-get install -y --no-install-recommends "${APT_DPKG_OPTS[@]}" "$@"
}

# Nested Docker packages. Never abort the snapshot: warn and continue.
apt_install_optional() {
  local pkg="$1"
  local why="$2"
  if pkg_installed "$pkg"; then
    return 0
  fi
  if sudo apt-get install -y --no-install-recommends "${APT_DPKG_OPTS[@]}" "$pkg"; then
    return 0
  fi
  echo "WARN: $pkg did not configure ($why). Nested Docker/ISO is optional; continuing." >&2
  sudo DEBIAN_FRONTEND=noninteractive dpkg --force-confdef --force-confold --configure -a \
    >/dev/null 2>&1 || true
  if pkg_installed "$pkg"; then
    echo "WARN: $pkg configured on retry." >&2
  fi
  return 0
}

REQUIRED_PKGS=(
  ca-certificates
  curl
  git
  make
  python3
  python3-pip
  python3-venv
  python3-tk
  python3-gi
  gir1.2-gtk-3.0 librsvg2-common
  python3-pyatspi
  at-spi2-core
  dbus-x11
  orca
  speech-dispatcher
  speech-dispatcher-espeak-ng
  pulseaudio
  xvfb
  xauth
  fonts-dejavu-core
  iptables
  qemu-system-x86
  qemu-utils
  ovmf
)

need_apt=0
for pkg in "${REQUIRED_PKGS[@]}"; do
  if ! pkg_installed "$pkg"; then
    need_apt=1
    break
  fi
done

need_optional=0
if ! pkg_installed fuse-overlayfs; then
  need_optional=1
fi
if ! command -v docker >/dev/null 2>&1; then
  need_optional=1
fi

if [ "$need_apt" -eq 1 ] || [ "$need_optional" -eq 1 ]; then
  sudo apt-get update
fi

if [ "$need_apt" -eq 1 ]; then
  apt_install_required "${REQUIRED_PKGS[@]}"
fi

# Separate transaction from python/tk/qemu. Snapshot-builder VMs often already
# have /etc/fuse.conf; fuse3 then prompts and used to fail the whole install.
apt_install_optional fuse-overlayfs "fuse3 conffile prompt or missing /dev/fuse"

if ! command -v docker >/dev/null 2>&1; then
  apt_install_optional docker.io "nested Docker is optional for ISO builds"
fi

# Only pin fuse-overlayfs when the package actually configured. Writing this
# driver while fuse3 is half-installed makes dockerd refuse to start.
if pkg_installed fuse-overlayfs; then
  sudo python3 - <<'PY'
import json
from pathlib import Path

path = Path("/etc/docker/daemon.json")
data = {}
if path.exists():
    text = path.read_text(encoding="utf-8").strip()
    if text:
        data = json.loads(text)
if not isinstance(data, dict):
    data = {}
data["storage-driver"] = "fuse-overlayfs"
features = data.get("features")
if not isinstance(features, dict):
    features = {}
features["containerd-snapshotter"] = False
data["features"] = features
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY
else
  echo "WARN: fuse-overlayfs not installed; leaving /etc/docker/daemon.json unchanged." >&2
fi

if [ -x /usr/sbin/iptables-legacy ]; then
  sudo update-alternatives --set iptables /usr/sbin/iptables-legacy >/dev/null 2>&1 || true
  sudo update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy >/dev/null 2>&1 || true
fi

if getent group docker >/dev/null 2>&1; then
  sudo usermod -aG docker "$(id -un)" || true
fi
if getent group kvm >/dev/null 2>&1; then
  sudo usermod -aG kvm "$(id -un)" || true
fi
if getent group rdma >/dev/null 2>&1; then
  sudo usermod -aG rdma "$(id -un)" || true
fi

# Match GitHub Actions / pyproject optional extra: pytest only. No nwipe install.
if python3 -c 'import pytest' >/dev/null 2>&1; then
  :
else
  python3 -m pip install --user --break-system-packages 'pytest>=8'
fi

echo "Beamo Wipe Cloud install complete."
echo "Daemons are started by .cursor/start.sh (dockerd optional + Xvfb :99 at 72 DPI)."
echo "ISO build is optional and not run here: ./scripts/build-iso.sh after Docker is up."
echo "Smoke: bash .cursor/check.sh"
