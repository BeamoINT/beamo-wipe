#!/bin/bash
set -Eeuo pipefail
exec > /var/log/usb-sim-setup.log 2>&1
export DEBIAN_FRONTEND=noninteractive
printf 'deb https://deb.debian.org/debian bookworm-backports main\n' > /etc/apt/sources.list.d/usb-lab-backports.list
apt-get update -qq
apt-get install -y -qq --no-install-recommends docker.io git curl ca-certificates python3 python3-pytest python3-pil python3-tk ovmf xorriso genisoimage squashfs-tools dosfstools mtools syslinux syslinux-common e2fsprogs grub-efi-amd64-bin grub-common debsecan file sudo procps util-linux kmod hdparm build-essential automake autoconf pkg-config libncurses-dev libparted-dev libconfig-dev
apt-get install -y -qq -t bookworm-backports qemu-system-x86 qemu-utils
qemu-system-x86_64 --version
systemctl enable --now docker
mkdir -p /lab
printf 'SETUP_READY\n'
