#!/bin/bash
# Build a separate installed Debian probe guest from the product ISO.
# Extraction + mkfs -d only: no loop mounts and no physical devices.
set -Eeuo pipefail
[[ $(uname -s) == Linux && $(uname -m) == x86_64 && ! -d /Users/HP ]]
[[ $# == 2 ]] || { echo 'usage: prepare_fixture.sh ISO NEW_OUTPUT_DIR' >&2; exit 2; }
SCRIPT=$(CDPATH='' cd -- "$(dirname "$0")" && pwd)
ISO=$(realpath -- "$1")
OUT=$2
python3 - "$1" "$OUT" "$SCRIPT" <<'PY'
import sys
sys.path.insert(0,sys.argv[3])
from lab import regular
from pathlib import Path
regular(sys.argv[1])
p=Path(sys.argv[2]).absolute()
if p.exists() or p.is_symlink() or any(x.is_symlink() for x in p.parents):
    raise SystemExit('Output must be a new directory without symlink parents')
p.mkdir(mode=0o700)
PY
OUT=$(realpath -- "$OUT")
xorriso -osirrox on -indev "$ISO" -extract / "$OUT/iso" > "$OUT/extract.log" 2>&1
unsquashfs -d "$OUT/tree" "$OUT/iso/live/filesystem.squashfs" > "$OUT/unsquash.log" 2>&1
TREE=$OUT/tree
rm -f "$TREE/etc/systemd/system/multi-user.target.wants/beamo-wipe-kiosk.service"
ln -sfn /dev/null "$TREE/etc/systemd/system/beamo-wipe-kiosk.service"
cp "$SCRIPT/guest.py" "$TREE/root/usblab-guest.py"
cat > "$TREE/etc/systemd/system/usblab-probe.service" <<'EOF'
[Unit]
Description=Disposable USB lab serial probe
After=systemd-udev-settle.service
Wants=systemd-udev-settle.service
[Service]
ExecStart=/usr/bin/python3 /root/usblab-guest.py
Restart=on-failure
RestartSec=2
[Install]
WantedBy=multi-user.target
EOF
ln -s ../usblab-probe.service "$TREE/etc/systemd/system/multi-user.target.wants/usblab-probe.service"
: > "$TREE/etc/fstab"
truncate -s 4G "$OUT/root.ext4"
mkfs.ext4 -q -F -d "$TREE" "$OUT/root.ext4"
python3 - "$TREE/boot" "$OUT" <<'PYBOOT'
import pathlib,shutil,sys
boot,out=map(pathlib.Path,sys.argv[1:])
for pattern,name in [('vmlinuz-*','kernel'),('initrd.img-*','initrd')]:
    files=[p for p in boot.glob(pattern) if p.is_file() and not p.is_symlink()]
    if len(files)!=1: raise SystemExit('Expected one kernel/initrd in installed fixture')
    shutil.copyfile(files[0],out/name)
PYBOOT
sha256sum "$OUT/kernel" "$OUT/initrd" "$OUT/root.ext4" > "$OUT/SHA256SUMS"
printf 'FIXTURE_READY\n'
