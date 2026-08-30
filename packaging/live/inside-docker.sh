#!/bin/bash
# Runs as root inside debian:bookworm. Invoked by scripts/build-iso.sh.
# Builds on the container's own disk so debootstrap can mknod.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
ISO_NAME="${BEAMO_WIPE_ISO_NAME:-beamo-wipe-0.1.1-amd64.iso}"

apt-get update
apt-get install -y \
  live-build \
  xorriso \
  isolinux \
  syslinux-common \
  squashfs-tools \
  ca-certificates \
  git \
  cpio \
  rsync \
  file \
  xz-utils \
  bzip2

mkdir -p /build
# Do not copy previous failed chroots or git objects; we need config + sources.
rsync -a \
  --exclude '.git/' \
  --exclude 'dist/' \
  --exclude 'packaging/live/chroot/' \
  --exclude 'packaging/live/cache/' \
  --exclude 'packaging/live/.build/' \
  --exclude 'packaging/live/.stage/' \
  --exclude 'packaging/live/binary/' \
  --exclude 'packaging/live/tmp/' \
  /src/ /build/

cd /build/packaging/live

lb clean --all || true

lb config \
  --mode debian \
  --distribution bookworm \
  --architectures amd64 \
  --binary-images iso-hybrid \
  --bootloaders syslinux,grub-efi \
  --debian-installer none \
  --memtest none \
  --win32-loader false \
  --iso-application "Beamo Wipe" \
  --iso-preparer "Beamo" \
  --iso-publisher "Beamo https://github.com/BeamoINT/beamo-wipe" \
  --iso-volume "BEAMO_WIPE" \
  --archive-areas "main" \
  --apt-recommends false \
  --firmware-binary false \
  --firmware-chroot false \
  --initsystem systemd \
  --bootappend-live "boot=live components hostname=beamo-wipe username=root noeject nopersistence noswap ip=frommedia nox11autologin" \
  --bootappend-live-failsafe "boot=live components hostname=beamo-wipe username=root noeject nopersistence noswap ip=frommedia nox11autologin memtest noapic noapm nodma nomce nolapic nosmp nosplash vga=788" \
  --mirror-bootstrap "https://deb.debian.org/debian/" \
  --mirror-chroot "https://deb.debian.org/debian/" \
  --mirror-binary "https://deb.debian.org/debian/" \
  --parent-mirror-bootstrap "https://deb.debian.org/debian/" \
  --parent-mirror-chroot "https://deb.debian.org/debian/" \
  --parent-mirror-binary "https://deb.debian.org/debian/" \
  --mirror-chroot-security "https://security.debian.org/" \
  --mirror-binary-security "https://security.debian.org/" \
  --parent-mirror-chroot-security "https://security.debian.org/" \
  --parent-mirror-binary-security "https://security.debian.org/"

lb build

found="$(find /build/packaging/live -maxdepth 2 -name '*.iso' -print | head -n 1)"
if [ -z "$found" ] || [ ! -f "$found" ]; then
  echo "live-build produced no ISO" >&2
  ls -la /build/packaging/live || true
  exit 1
fi
cp -v "$found" "/out/${ISO_NAME}"
ls -lh "/out/${ISO_NAME}"
