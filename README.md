# Beamo Wipe

A guided front-end for **nwipe**. Beamo did not write the erasure engine.

Beamo Wipe is a bootable x86_64 live USB UI that walks a first-time BIOS user
through erasing a disk they own. You pay for a flashed stick, a boot-key card,
and this wizard. You do not pay for a secret wipe algorithm.

> **No warranty.** See [LICENSE](LICENSE) (GPL-3.0-or-later) and [NOTICE](NOTICE).
> Owner-operated sanitization before recycle or resale. Not a lab certificate.

## What this is not

- Not for **Apple Silicon** Macs, Chromebooks, Android, or RAID controllers.
- Not a wipe from inside Windows. The PC must boot this USB.
- Not DoD / NSA / NIST “certified.” Not a Blancco replacement.
- Not a new wipe engine. The only eraser is [nwipe](https://github.com/martijnvanbrummelen/nwipe) **v0.42**.
- Not plug-and-play. You will use the firmware boot menu (often F12, Esc, or F9).

Listing language we are allowed to use: [docs/claims.md](docs/claims.md).

## License

This wrapper is **GPL-3.0-or-later**. nwipe is **GPL-2.0**. We run nwipe as a
separate program. Source: this repository. There is **no warranty**.

## Build the ISO

You need Docker (amd64 image; on Apple silicon Docker emulates it).

```bash
./scripts/build-iso.sh
```

The ISO lands in `dist/beamo-wipe-0.1.0-amd64.iso`. If Docker or live-build
packages are missing, the script prints the missing pieces and exits non-zero.

`make iso` is the same command.

## Run the wizard in a VM

**Preview on your Mac/PC (fake disks, no wipe):**

```bash
python3 -m beamo_wipe --demo
```

**QEMU, after you have an ISO** (throws away a 10G virtual disk):

```bash
qemu-img create -f qcow2 /tmp/beamo-wipe-target.qcow2 10G
qemu-system-x86_64 -m 2048 -enable-kvm \
  -cdrom dist/beamo-wipe-0.1.0-amd64.iso \
  -drive file=/tmp/beamo-wipe-target.qcow2,if=virtio,format=qcow2 \
  -boot d
```

On macOS, drop `-enable-kvm` and use `-accel hvf` if available, or TCG.

UEFI:

```bash
qemu-system-x86_64 -m 2048 \
  -bios /usr/share/OVMF/OVMF_CODE.fd \
  -cdrom dist/beamo-wipe-0.1.0-amd64.iso \
  -drive file=/tmp/beamo-wipe-target.qcow2,if=virtio,format=qcow2
```

Full notes: [docs/vm-test.md](docs/vm-test.md).

Use **only disposable virtual disks**. Never point this at a developer machine’s
real Windows disk.

## Flash a USB for testing

```bash
# Linux (double-check the device name)
sudo dd if=dist/beamo-wipe-0.1.0-amd64.iso of=/dev/sdX bs=4M status=progress conv=fsync

# Or Raspberry Pi Imager / balenaEtcher: pick the ISO, pick the USB, flash.
```

The image is meant to fit in about 1 GB so a 16–32 GB dual A/C stick has room
for README and licenses on a leftover data partition.

## Unit tests

```bash
python3 -m pytest
# or
make test
# or
./scripts/test-all.sh
```

Tests use fake `lsblk` JSON. They never run nwipe on a real disk.

## How it works

1. Boot the live USB (UEFI or legacy BIOS, x86_64).
2. The wizard is the first screen. There is no desktop and no raw nwipe TUI.
3. Confirm you own the machine. Pick a disk by model, size, and serial.
4. The Beamo USB cannot be selected. If we cannot tell which disk is the USB,
   the app refuses to list disks.
5. Type-to-confirm, five-second delay, then nwipe runs non-interactively.
6. Success only if nwipe exits 0.

## Development

```bash
python3 -m beamo_wipe --demo           # Tk wizard, fake disks
python3 -m beamo_wipe --demo --console # keyboard screens
```

Default everyday method is nwipe `prng`, one round, verify last, no blank pass.
Details: [docs/ADVANCED.md](docs/ADVANCED.md).
