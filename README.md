# Beamo Wipe

A guided USB for **nwipe**.

Beamo Wipe is a bootable x86_64 live USB UI that walks a first-time BIOS user
through erasing a disk they own. You pay for a flashed stick, a boot-key card,
and this wizard. You do not pay for a secret wipe algorithm.

> **No warranty.** See [LICENSE](LICENSE) (GPL-3.0-or-later) and [NOTICE](NOTICE).
> Owner-operated sanitization before recycle or resale. Not a lab certificate.

## See the UI on this computer

Nothing is erased. Fake disks only. This is the way to look at the screens
without building an ISO or booting a USB.

```bash
cd "/path/to/Beamo Wiper"   # this repo
./preview                   # real Tk window (same screens as the live USB)
./preview --web             # browser click-through of the same copy
./preview --helper          # boot-menu helper page (does not wipe)
./preview --empty           # no other disks
./preview --blocked         # cannot identify the USB
./preview --fail            # finished screen after a failed wipe
./preview --accessible      # Linux GTK view for Orca / AT-SPI
./preview --console         # keyboard screens in the terminal
./preview --plain-console   # sequential text prompts, without screen redraws
```

`make preview` and `make preview-web` are the same commands.

The native windows are the real app. The browser page is a click-through so you can
see the flow in Safari or Chrome without installing anything extra.

If `./preview` cannot open a window (no Tk), it falls back to `--console`.

On the live USB, press **F8** before erasure to open the screen-reader view
with Orca. Switching views clears all previous confirmations and checks disks
again. Use Tab and Shift+Tab to move, Space to activate controls, and the
standard Orca reading commands for text. See [screen-reader operation](docs/screen-reader.md).

Before erasure, **Check disks again** (F5, or `CHECK DISKS AGAIN` at a text
prompt) reads the inventory again and identifies the boot device again. It
clears the selected disk, ownership acknowledgement, typed confirmation,
method, and countdown. Complete the entire confirmation flow again. A failed
refresh leaves no stale target selectable. Refresh is unavailable once an
erase is starting or running.

**Other detected devices** is information only: each row explains why the
device cannot be selected. In the keyboard console, press O to read and scroll
these explanations. No excluded row offers an erase action or bypass.

Results use the same evidence-based explanation in the native interfaces and report
exports. “Erase completed; verification passed” requires validated completion
evidence for a method with read-back verification. Quick zero instead says
“Erase completed; verification was not performed.” Read-back checks exposed
storage only; it does not prove hidden copies were erased. Confirmed user
cancellation says “Stopped by you.” Failed verification, interruption, missing
evidence, and an unconfirmed stop remain distinct. Saved evidence can be checked
for its result without resuming erasure; missing or inconsistent evidence never
becomes success.

## What this is not

- Not for **Apple Silicon** Macs, Chromebooks, Android, or RAID controllers.
- Not a wipe from inside Windows. The PC must boot this USB.
- Not DoD / NSA / NIST “certified.” Not a Blancco replacement.
- Not a new wipe engine. The only eraser is [nwipe](https://github.com/martijnvanbrummelen/nwipe) **v0.42**.
- Not plug-and-play. You will use the firmware boot menu (often F12, Esc, or F9).

Listing language we are allowed to use: [docs/claims.md](docs/claims.md).
Controller and erase limits: [docs/storage-and-controller-limits.md](docs/storage-and-controller-limits.md)
(SSD wear-leveling, hidden areas, encryption, RAID, when vendor tools or destruction are required).

## License

This wrapper is **GPL-3.0-or-later**. nwipe is **GPL-2.0**. We run nwipe as a
separate program. Source: this repository. There is **no warranty**.

## Build the ISO

You need Docker (amd64 image; on Apple silicon Docker emulates it).

```bash
./scripts/build-iso.sh
```

The ISO lands in `dist/beamo-wipe-0.2.2-amd64.iso`. If Docker or live-build
packages are missing, the script prints the missing pieces and exits non-zero.

`make iso` is the same command.

## Run the wizard in a VM

**Preview on your Mac/PC (fake disks, no wipe):**

```bash
./preview
./preview --web
```

**QEMU, after you have an ISO** (throws away a 10G virtual disk):

```bash
qemu-img create -f qcow2 /tmp/beamo-wipe-target.qcow2 10G
qemu-system-x86_64 -m 2048 -enable-kvm \
  -cdrom dist/beamo-wipe-0.2.2-amd64.iso \
  -drive file=/tmp/beamo-wipe-target.qcow2,if=virtio,format=qcow2 \
  -boot d
```

On macOS, drop `-enable-kvm` and use `-accel hvf` if available, or TCG.

UEFI:

```bash
# OVMF 4M firmware does not load via -bios ("could not load PC BIOS"):
# attach code (readonly) plus a writable vars copy as pflash drives.
cp /usr/share/OVMF/OVMF_VARS.fd /tmp/beamo-ovmf-vars.fd
qemu-system-x86_64 -m 2048 \
  -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE.fd \
  -drive if=pflash,format=raw,file=/tmp/beamo-ovmf-vars.fd \
  -cdrom dist/beamo-wipe-0.2.2-amd64.iso \
  -drive file=/tmp/beamo-wipe-target.qcow2,if=virtio,format=qcow2
# No vars template (older OVMF_CODE.fd-only layout): -bios /usr/share/OVMF/OVMF_CODE.fd
```

Full notes: [docs/vm-test.md](docs/vm-test.md).

Use **only disposable virtual disks**. Never point this at a developer machine’s
real Windows disk.

## Flash a USB for testing

```bash
# Linux (double-check the device name)
sudo dd if=dist/beamo-wipe-0.2.2-amd64.iso of=/dev/sdX bs=4M status=progress conv=fsync

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

Hosted CI — lint, x86_64 pytest, preview, negative test, the amd64 ISO
build, and controlled QEMU verification — runs on Google Cloud Build
(`./scripts/ci-cloud.sh`, project `beamo-wipe`). GitHub Actions is not
used. Details: [docs/ci.md](docs/ci.md).

## How it works

1. Boot the live USB (UEFI or legacy BIOS, x86_64).
2. The wizard is the first screen. There is no desktop and no raw nwipe TUI.
3. Confirm you own the machine. Pick a disk by model, size, and serial.
4. The Beamo USB cannot be selected. If we cannot tell which disk is the USB,
   the app refuses to list disks.
5. Type-to-confirm, five-second delay, then nwipe runs non-interactively.
6. The final screen reports success, failure, or interruption. Success requires
   exit 0 and positive completion evidence for the selected target, with no
   failure markers. Everyday and Three overwrites include a separate read-back
   verification pass; Quick zero does not perform verification.
   Read-back checks exposed storage only and does not prove that hidden copies
   were erased. Additional overwrite passes do not fix SSD coverage limitations
   ([details](docs/storage-and-controller-limits.md#3-overwrite-limits--why-overwrite-alone-is-not-a-certificate)).
   Reports are not a formal certificate. If required assurance cannot be
   established, consult the drive maker's guidance for the exact model and
   firmware or use a qualified destruction service.

## Development

```bash
./preview                      # Tk wizard, fake disks
./preview --web                # browser click-through
python3 -m beamo_wipe --demo   # same as ./preview
```

Cursor Cloud Agents boot from `.cursor/environment.json` (`install.sh` / `start.sh`); `.cursor/check.sh` is the smoke.

Default everyday method is nwipe `prng`, one round, verify last, no blank pass.
Details: [docs/ADVANCED.md](docs/ADVANCED.md).

### macOS preview runtime

The desktop `./preview` launcher prefers an installed modern Python/Tk on macOS.
Python 3.10.0 with Tk 8.6.11 can abort when closing a native window. Python
3.14.7 with Tk 9.0.4 was verified to close cleanly. An explicit runtime can be
selected with `BEAMO_WIPE_PREVIEW_PYTHON=python3.14 ./preview`. This affects only
the fake-device desktop preview, not the live Linux launcher.

At method selection, **Storage limits (L)** opens the supported limits offline.
The warning includes inaccessible, remapped, over-provisioned, and controller-managed
flash areas and explains why additional overwrite passes do not fix those limits.
See [the full limits](docs/storage-and-controller-limits.md).

When a wipe cannot start, use the separately labeled [diagnostic report](docs/startup-diagnostics.md) path. Diagnostic reports are not erase evidence.

### Planning to save a report

Open **Need a report?** before choosing an erase target (also available at method
selection and in Advanced). Keep a separate supported FAT32 report USB unplugged
until the erase has stopped and Save report to USB is offered; then insert it
before choosing Save. Keep the boot USB and erase disk connected. Any unsaved
report is lost on live-session shutdown or power loss. The optional preference
records intent for this session. It does not save anything. If a report was requested
and no verified export completed, shutdown asks **Shut down without saving?**
with **Keep session open** as the safe default. See [shutdown protection](docs/report-shutdown.md).
See [the exact media, refresh and safe-removal requirements](docs/ADVANCED.md#logs).
