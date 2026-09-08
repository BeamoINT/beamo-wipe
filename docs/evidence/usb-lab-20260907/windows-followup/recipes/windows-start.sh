#!/bin/bash
set -Eeuo pipefail
exec > /lab/windows-start.log 2>&1
mkdir -m 700 /lab/windows-2022
cd /lab/windows-2022
curl --fail --location --retry 2 --max-time 900 --dump-header download-headers.txt --output evaluation.vhd 'https://go.microsoft.com/fwlink/p/?clcid=0x409&country=us&culture=en-us&linkid=2195166'
sha256sum evaluation.vhd > evaluation.sha256
printf '588355586a3b99f1d47cee02f4861680a7e1bcb353582fbe7da11e2988e7562f  evaluation.vhd\n' | sha256sum -c -
qemu-img info --output=json evaluation.vhd > evaluation-info.json
python3 - <<'PY'
import json
x=json.load(open('evaluation-info.json'))
assert x['format']=='vpc' and 'backing-filename' not in x
PY
qemu-img create -f qcow2 -F vpc -b /lab/windows-2022/evaluation.vhd guest.qcow2
python3 /tmp/prepare-seed.py
exec qemu-system-x86_64 -machine q35,accel=tcg -cpu max,svm=off,vmx=off -smp 2 -m 4096 -nic none -display none -drive if=none,id=os,format=qcow2,file=/lab/windows-2022/guest.qcow2 -device ide-hd,drive=os,bus=ide.0 -device qemu-xhci,id=xhci -device usb-ehci,id=ehci -qmp unix:/lab/windows-2022/qmp,server=on,wait=off -serial unix:/lab/windows-2022/probe,server=on,wait=off -serial file:/lab/windows-2022/diagnostics.jsonl -drive if=none,id=seed,format=raw,readonly=on,file=/lab/seed/seed.raw -device usb-storage,id=seed,drive=seed,bus=ehci.0,port=6,serial=PROBESEED,removable=on
