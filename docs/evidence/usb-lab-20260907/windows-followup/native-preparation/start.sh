#!/bin/bash
set -Eeuo pipefail
exec > /lab/windows11-native/start.log 2>&1
cd /lab/windows11-native
[[ -f verified-assembly.json ]]
[[ $(systemctl show usb-win11 --property=MainPID --value) == 0 ]]
cp /usr/share/OVMF/OVMF_VARS_4M.ms.fd vars.fd
mkdir -m 700 tpm
systemd-run --unit=usb-win11-native-tpm /usr/bin/swtpm socket --tpmstate dir=/lab/windows11-native/tpm --ctrl type=unixio,path=/lab/windows11-native/tpm/socket --tpm2 --log file=/lab/windows11-native/tpm.log --terminate
for i in {1..20}; do [[ -S tpm/socket ]] && break; sleep .2; done
[[ -S tpm/socket ]]
exec qemu-system-x86_64 -machine q35,smm=on,accel=tcg -global driver=cfi.pflash01,property=secure,value=on -cpu max,svm=off,vmx=off -smp 2 -m 6144 -nic none -display none -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.ms.fd -drive if=pflash,format=raw,file=/lab/windows11-native/vars.fd -drive if=none,id=os,format=raw,file=/lab/windows11-native/guest.raw -device ide-hd,drive=os,bus=ide.0,bootindex=2 -drive if=none,id=install,format=raw,readonly=on,file=/lab/windows-11/evaluation.iso -device ide-cd,drive=install,bus=ide.1,bootindex=1 -chardev socket,id=chrtpm,path=/lab/windows11-native/tpm/socket -tpmdev emulator,id=tpm0,chardev=chrtpm -device tpm-tis,tpmdev=tpm0 -device qemu-xhci,id=xhci -device usb-ehci,id=ehci -qmp unix:/lab/windows11-native/qmp,server=on,wait=off -serial unix:/lab/windows11-native/probe,server=on,wait=off -serial file:/lab/windows11-native/diagnostics.jsonl -drive if=none,id=seed,format=raw,readonly=on,file=/lab/windows11-native/seed/seed.raw -device usb-storage,id=seed,drive=seed,bus=ehci.0,port=6,serial=PROBESEED,removable=on
