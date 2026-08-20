#!/bin/bash
# Runs as root inside debian:bookworm. Invoked by scripts/build-iso.sh.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  live-build \
  xorriso \
  isolinux \
  syslinux-common \
  squashfs-tools \
  ca-certificates \
  git

cd /work/packaging/live

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
  --archive-areas "main contrib non-free-firmware" \
  --apt-recommends false \
  --firmware-binary true \
  --firmware-chroot true \
  --initsystem systemd \
  --bootappend-live "boot=live components hostname=beamo-wipe username=root noeject nopersistence noswap" \
  --mirror-bootstrap "http://deb.debian.org/debian/" \
  --mirror-chroot "http://deb.debian.org/debian/" \
  --mirror-binary "http://deb.debian.org/debian/"

# Keep our package list / includes; lb config should not delete them.
lb build
