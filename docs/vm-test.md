# VM integration test notes

Use **throwaway virtual disks only**.

Do not treat this Apple silicon Mac as the ISO/QEMU gate. Docker `linux/amd64`
and `qemu-system-x86_64` here are TCG. The hosted ISO build is Google Cloud
Build: `./scripts/ci-cloud.sh` (project `beamo-wipe`). Interactive QEMU wipe
below still needs an **x86_64 Linux VM** with KVM via `gcloud`/`aws`; copy
hashes out and delete the VM. Pytest and `./preview` stay local.

## Demo (no ISO)

```bash
python3 -m pytest
./preview
./preview --web
```

Keyboard-only can finish `./preview --console`.

## ISO in QEMU (x86_64)

Build:

```bash
./scripts/build-iso.sh
```

Two disks: the ISO (live) and a 10G target.

```bash
qemu-img create -f qcow2 /tmp/beamo-wipe-target.qcow2 10G
qemu-system-x86_64 -m 2048 \
  -cdrom dist/beamo-wipe-0.1.0-amd64.iso \
  -drive file=/tmp/beamo-wipe-target.qcow2,if=virtio,format=qcow2 \
  -boot order=d
```

Checklist:

- [ ] ISO boots UEFI (`-bios OVMF_CODE.fd` when the firmware file exists).
- [ ] ISO boots legacy BIOS (default SeaBIOS).
- [ ] Wizard is the first and only UI (no desktop, no raw nwipe).
- [ ] Keyboard-only can complete the flow.
- [ ] The 10G disk appears with size + serial (QEMU may show a short serial).
- [ ] The live disc is not selectable.
- [ ] Wrong confirm token keeps Continue disabled.
- [ ] Everyday wipe on the 10G disk completes; success screen.
- [ ] Killing nwipe (or `--fail-demo` in demo) shows failure, not success.
- [ ] `helper/index.html` opens in a browser and is obviously not a wiper.

## Hardware lab (optional, owner disks only)

Label the target “DISPOSABLE”. One Intel/AMD UEFI PC with a SATA HDD. One NVMe
SSD if you want to note SSD limits in a report. Do not claim Apple Silicon.
