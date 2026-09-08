#!/bin/bash
set -Eeuo pipefail
exec > /lab/windows-11/start.log 2>&1
cd /lab/windows-11
# Download completed successfully; this exact hash was independently checked.
grep -q '^a61adeab895ef5a4db436e0a7011c92a2ff17bb0357f58b13bbc4062e535e7b9 ' /tmp/windows11-sha256-complete.txt
[[ $(stat -c %s evaluation.iso) == 7092807680 ]]
cp /tmp/windows11-sha256-complete.txt evaluation.sha256
cp /tmp/windows11-wiminfo.txt wiminfo.txt
python3 /tmp/prepare-win11-seed.py
qemu-img create -f qcow2 guest.qcow2 80G
cp /usr/share/OVMF/OVMF_VARS_4M.ms.fd vars.fd
mkdir -m 700 tpm
systemd-run --unit=usb-win11-tpm /usr/bin/swtpm socket --tpmstate dir=/lab/windows-11/tpm --ctrl type=unixio,path=/lab/windows-11/tpm/socket --tpm2 --log file=/lab/windows-11/tpm.log --terminate
for i in {1..20}; do [[ -S tpm/socket ]] && break; sleep .2; done
[[ -S tpm/socket ]]
exec qemu-system-x86_64 -machine q35,smm=on,accel=tcg -global driver=cfi.pflash01,property=secure,value=on -cpu max,svm=off,vmx=off -smp 2 -m 6144 -nic none -display none -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.ms.fd -drive if=pflash,format=raw,file=/lab/windows-11/vars.fd -drive if=none,id=os,format=qcow2,file=/lab/windows-11/guest.qcow2 -device ide-hd,drive=os,bus=ide.0,bootindex=2 -drive if=none,id=install,format=raw,readonly=on,file=/lab/windows-11/evaluation.iso -device ide-cd,drive=install,bus=ide.1,bootindex=1 -chardev socket,id=chrtpm,path=/lab/windows-11/tpm/socket -tpmdev emulator,id=tpm0,chardev=chrtpm -device tpm-tis,tpmdev=tpm0 -device qemu-xhci,id=xhci -device usb-ehci,id=ehci -qmp unix:/lab/windows-11/qmp,server=on,wait=off -serial unix:/lab/windows-11/probe,server=on,wait=off -serial file:/lab/windows-11/diagnostics.jsonl -drive if=none,id=seed,format=raw,readonly=on,file=/lab/windows-11/seed/seed.raw -device usb-storage,id=seed,drive=seed,bus=ehci.0,port=6,serial=PROBESEED,removable=on
