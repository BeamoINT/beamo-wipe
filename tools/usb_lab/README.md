# Disposable USB simulation lab

This lab makes a guest OS load its real USB controller, storage, partition and
filesystem drivers. QEMU presents file-backed USB devices through EHCI or xHCI;
it does not rename a virtio/cloud disk to look like USB. The harness is reusable
inside this repository: its QMP/device layer is separate from the Linux and
Windows probes and the optional Beamo product checks.

## Scope and architecture

```
Private temporary Google Cloud x64 host (three-hour deletion limit)
  QEMU virtual PC / firmware
    EHCI or xHCI controller
      removable USB bulk storage, or USB Attached SCSI
        exclusively owned disposable image file
    real guest OS + serial-only test probe
  QMP controller -> insert / unplug / replacement / read faults
  assertions -> guest inventory + packet capture + independent host readback
```

No host block devices, USB passthrough, shared host folders, or guest networking
are needed for the Linux matrix. Product images are copied before use; the
emulated product device is writable, so an unchanged hash is meaningful. The
read-only mount inside the desktop probe protects against OS access-time writes.
Raw scratch I/O is bounded to a 64 MiB USBLAB fixture after validating USB
transport, size, path and unique serial. It is a device test, not a wipe engine.

A virtual device cannot reproduce connector quality, power loss electronics,
flash wear/remapping, vendor firmware defects, real timing, or every physical
UEFI trust store. It also cannot prove that a human understands the UI. Physical
acceptance remains separate. CPU emulation timings are not performance claims.

## Repeat a Beamo run

Use an isolated x86_64 Linux host with the dependencies in `host_setup.sh`.
Keep every output below disposable staging. Run with Python assertions enabled. TCG is the default; use `--accelerator kvm`
only on an authorized host that already exposes KVM.
The commands below neither create a release nor write to a physical disk.

```bash
# From a clean, correctly attributed Beamo checkout on the disposable host:
bash scripts/ci-desktop.sh
bash scripts/build-iso.sh
bash scripts/build-usb-image.sh

# Build a separate installed Debian fixture; leave the product image unchanged.
bash tools/usb_lab/prepare_fixture.sh \
  dist/beamo-wipe-0.2.6-amd64.iso /var/tmp/usb-fixture
python3 tools/usb_lab/lab.py \
  --fixture /var/tmp/usb-fixture \
  --product-image dist/beamo-wipe-0.2.6-amd64.img \
  --output /var/tmp/usb-results
```

Both output directories must be new. The fixture is a Debian root filesystem
extracted from the product ISO, with a test service added, booted without
`boot=live`. It is not independent distribution coverage. The optional product
check reads back the packaged executable hashes through the guest FAT filesystem
and executes the actual Linux launcher in read-only check mode. The default OVMF/UEFI fixture requires the specific missing-boot-entry fallback,
which proves that the launcher identified its original USB before reaching that
check. `--firmware bios` exercises the earlier legacy-firmware fallback. Neither
check claims an actual reboot handoff.

`receipt.json` distinguishes PASS/FAIL, identifies fixture/product bytes and
QEMU, and records individual cases. `qmp.jsonl`, the serial log and USB packet
captures preserve independent observations. Large product transfers are omitted
from packet captures. Small scratch-device captures can be opened with Wireshark.
A failed run retains its partial receipt and logs. The run-owned backing images
are removed only after the QEMU process exits. Preserve evidence before deleting
the cloud host; do not preserve bulky guest disks as the test receipt.

The existing `scripts/qemu-verify.sh` and canonical `scripts/ci-cloud.sh` remain
the boot, real nwipe erase, report-export and hosted acceptance gates. This matrix
adds hotplug/driver/fault coverage and does not replace them.

## Cloud lifecycle

The user must authorize cloud creation/costs and source transfer before a run.
The helper does not change organization policies or request hardware acceleration.
It creates a dedicated private network, outbound NAT, IAP-only SSH rule and a
VM without service-account credentials or a public address.

```bash
python3 tools/usb_lab/gcp_lab.py create \
  --name beamo-usb-your-run --state /private/tmp/your-usb-run.json
# Transfer the source/harness using your approved gcloud IAP/OS Login workflow.
# Use a disposable SSH key with a bounded expiry; preserve the source commit.
# ... run the matrix and copy results out ...
python3 tools/usb_lab/gcp_lab.py destroy --state /private/tmp/your-usb-run.json
```

Supply `--image` to select a different verified Debian host image; the default
is deliberately pinned. Retain the state file if provisioning fails. Destruction
checks recorded cloud resource identities and fails if a replacement is found.
An interrupted/uncertain creation or deletion may require manual reconciliation;
never erase the state to hide it. Verify and remove any OS Login key you added.
VM automatic deletion is a backstop, not a replacement for network teardown.

## Extending the matrix

`PROFILES` currently covers USB 2 BOT, USB 3 BOT and USB 3 UAS. Each is exercised
through insertion, real OS enumeration, write/readback, unplug and reconnection.
Additional cases cover write protection, duplicate identities, a specific-sector
read error, unplug during synchronous writes, stale identity after replacement,
and an untouched unrelated device. The guest probe refuses ambiguous identities;
that refusal is a harness safety test, not a claim about an application's own
identity handling.

Other applications can reuse `Lab`, `QMP`, the device profiles and receipt format
and supply their own guest actions and assertions. The optional Beamo action is
explicitly separate. Do not count a generic raw I/O test as a successful product
wipe, report export, permission prompt or restart.

`windows_probe.ps1` supplies a serial-only Windows adapter using native Get-Disk,
CIM, volume access and .NET I/O. Run it only in a licensed disposable guest, from
an administrator shell, with the emulated COM1 socket connected to the host.
The Windows OS must sit behind QEMU's USB controllers; a disk attached directly
to a Compute Engine Windows VM is not USB emulation. Keep Windows results and
Linux results distinct, and name the exact Windows edition tested.

With that probe running, execute the Windows matrix on its QEMU host:

```bash
python3 tools/usb_lab/windows_matrix.py \
  --qmp /var/tmp/windows/qmp --probe /var/tmp/windows/probe \
  --product-image dist/beamo-wipe-0.2.6-amd64.img \
  --output /var/tmp/windows-usb-results
```

The default run requests all three profiles. `--profiles usb2-bot usb3-bot`
can run independent bulk-storage checks after an all-profile run fails at UAS.
The receipt records `requested_profiles`; a PASS covers only that explicit scope.
Preserve the full failed run and report missing or failed profiles separately.
Do not present a narrowed run as complete Windows acceptance.

The caller owns the Windows VM lifecycle. This adapter detaches only the USB
fixtures it added; if detachment fails, it preserves their backing files for
inspection. Unlike the Linux read-only mount, Windows can update filesystem
metadata when it mounts writable media. The receipt therefore records image
hashes before/after, while the product assertion verifies packaged file bytes.
Do not confuse an OS metadata change with a launcher overwriting its USB.

Use `--firmware bios` only for an actual legacy-BIOS guest. It requires the
specific unsupported-automatic-restart message. That early fallback does not
prove the launcher's original-media identity check; the UEFI missing-entry
assertion does. Both modes verify the packaged file hashes through Windows.
An initial connection failure removes the run-owned empty scratch directory.

### Windows virtual PC recipe

Obtain a licensed evaluation image directly from Microsoft and record its URL,
filename, byte size and SHA-256. Inspect `qemu-img info --output=json` before use:
the base must be a regular owned file with no external backing chain. Keep the
base untouched and boot a new qcow2 overlay. Do not attach any host device.
Server 2025's evaluation VHDX uses UEFI; the tested Server 2022 VHD uses BIOS.
These editions are separate from Windows 10/11 acceptance.

This is the virtual hardware used for the Server 2025 attempt, on a dedicated
Linux host. Choose a new private directory and replace the example base path.
The commands assume the validated base format is VHDX:

```bash
mkdir -m 700 /var/tmp/windows-usb-run
qemu-img create -f qcow2 -F vhdx \
  -b /path/to/verified-evaluation.vhdx /var/tmp/windows-usb-run/guest.qcow2
cp /usr/share/OVMF/OVMF_VARS_4M.fd /var/tmp/windows-usb-run/vars.fd
qemu-system-x86_64 -machine q35,accel=tcg -cpu max -smp 1 -m 6144 \
  -nic none -display none \
  -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd \
  -drive if=pflash,format=raw,file=/var/tmp/windows-usb-run/vars.fd \
  -drive if=none,id=os,format=qcow2,file=/var/tmp/windows-usb-run/guest.qcow2 \
  -device ide-hd,drive=os,bus=ide.0 \
  -device qemu-xhci,id=xhci -device usb-ehci,id=ehci \
  -qmp unix:/var/tmp/windows-usb-run/qmp,server=on,wait=off \
  -serial unix:/var/tmp/windows-usb-run/probe,server=on,wait=off
```

For the BIOS Server 2022 fixture, use the verified VHD format `vpc`, omit both
pflash drives and use `-cpu max,svm=off,vmx=off -smp 2 -m 4096`. Record the
actual command, QEMU version and OS response with the evidence. Use QMP
`screendump`/keyboard events or a host-local display to complete setup. QMP
accepts one active client here; do not connect a competing screenshot client
while the matrix owns it.

Copy `windows_probe.ps1` into a new small FAT image with mtools, and attach that
image as a **read-only** USB storage device using the same QMP device model.
In an administrator console, verify its volume label and run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File D:\windows_probe.ps1
```

Replace `D:` with the observed probe volume. The process-scoped policy applies
only to this owned test harness. Wait for native inventory readiness before
starting the matrix. Once the probe is running, detach its seed USB device and
release its QMP block backend. Reserve direct root ports 1–4 on both `xhci.0`
and `ehci.0` for the matrix; remove setup input devices or put them on EHCI
ports 5 and 6. The lab assigns explicit root ports and fails on collisions.
This prevents QEMU from silently inserting a full-speed automatic hub when
root ports are exhausted. Partially realized USB devices are tracked and
removed before their backing files can be deleted. Windows setup can leave storage services unavailable;
a setup console and readable FAT directory alone are not a matrix pass. Do not
reuse timed-out probe responses as evidence of a later request. Preserve failed
attempts, stop the caller-owned virtual PC after evidence collection, and remove
its disposable overlay and firmware files before tearing down the cloud host.

## References

- [QEMU USB devices, hotplug, transport and packet capture](https://www.qemu.org/docs/master/system/devices/usb.html)
- [QMP commands and asynchronous events](https://www.qemu.org/docs/master/interop/qemu-qmp-ref.html)
- [Google Cloud nested virtualization](https://docs.cloud.google.com/compute/docs/instances/nested-virtualization/overview)
- [Microsoft Windows Server evaluation downloads](https://www.microsoft.com/en-us/evalcenter/download-windows-server-2025)


### Firmware restart tests after Windows installation

Remove installer-only `bootindex` overrides before testing an operating system's
one-time firmware restart. OVMF can rebuild BootOrder from QEMU's configured boot
order and prune otherwise valid HD boot entries. In the September 7 KVM run,
the real launcher restarted Windows but returned to Windows with those overrides
present. Repeating with both installer and OS `bootindex` values set to `-1`
allowed firmware to select the explicitly prepared Beamo USB entry. Keep the
failed attempt and the corrected machine configuration in the evidence.

A matching firmware entry prepared by the test fixture covers only that branch
of the launcher. It does not prove that customer firmware supplies such an entry.
Keep the normal missing-entry refusal test. Never ship fixture firmware-writing
scripts with the product, turn off Secure Boot to obtain a pass, or replace the
actual launcher restart button with a harness-issued reboot and call it product
acceptance. See the dated [lab report](../../docs/usb-simulation-lab-2026-09-07.md)
for the exact source, environment, screenshots and retained limits.
