#!/usr/bin/env bash
# Idempotent Linux x86_64 bootstrap for Cursor Cloud Agent VMs.
# Prepares pytest, Tk/Xvfb preview, and Docker/QEMU ISO tooling.
# Does not build the live ISO, does not start daemons, and never runs nwipe
# on a disk. Apple Silicon / macOS paths are out of scope.
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
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

PKGS=(
  ca-certificates
  curl
  git
  make
  python3
  python3-pip
  python3-venv
  python3-tk
  xvfb
  xauth
  fonts-dejavu-core
  fuse-overlayfs
  iptables
  qemu-system-x86
  qemu-utils
  ovmf
)

need_apt=0
for pkg in "${PKGS[@]}"; do
  if ! dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q 'install ok installed'; then
    need_apt=1
    break
  fi
done

if ! command -v docker >/dev/null 2>&1; then
  need_apt=1
  PKGS+=(docker.io)
fi

if [ "$need_apt" -eq 1 ]; then
  sudo apt-get update
  sudo apt-get install -y --no-install-recommends "${PKGS[@]}"
fi

# Nested Docker: overlayfs often fails; fuse-overlayfs is the documented driver.
# Merge into any existing daemon.json so we do not drop other keys.
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
if python3 -m pip install --user 'pytest>=8' >/dev/null 2>&1; then
  :
else
  python3 -m pip install --user --break-system-packages 'pytest>=8'
fi

echo "Beamo Wipe Cloud install complete."
echo "Daemons are started by .cursor/start.sh (dockerd + Xvfb :99 at 72 DPI)."
echo "ISO build is optional and not run here: ./scripts/build-iso.sh after Docker is up."
echo "Smoke: bash .cursor/check.sh"
