# Google Cloud USB simulation — 2026-09-06

Status: Validation continues after a reproduced keyboard safety defect. The
original-source primary matrix and focused repeat passed, but their results
do not validate the new fix. New-source hosted and VM checks are pending.
The NVMe default-method run timed out at 27% progress; it is not counted as passed.

The user requested a new Google Cloud VM and an accurate virtual USB test.
VM `beamo-usb-lab-0906b` (ID `2885835090945917987`) runs in project
`beamo-wipe`, zone `us-central1-a`, with no public IP. A temporary SSH rule allows only Google IAP source addresses
on the dedicated test network for authenticated diagnostics.
It has a two-hour automatic deletion limit. Dedicated NAT/router/subnet/network
resources must also be removed after evidence is captured.

Runtime source: `f7e28ccd6ea39b4b4de37765f66d204f61047e4d`. The local checkout
at `ebd2366816d72909c787881c6687573f26fa2320` adds documentation only. The
source archive is generation `1788735346552207` of
`gs://beamo-wipe_cloudbuild/source/1788735344.782105-f934dcaf53a5452a98ae29e5abd8d4fb.tgz`.
The VM builds the pinned launchers, ISO, and FAT32 image from that source.

## Simulation fidelity

QEMU emulates the PC firmware, an xHCI USB controller, and a removable USB mass
storage device backed by the actual FAT32 image. The boot USB is writable in
this run; software protection is not hidden behind a read-only QEMU device.
The guest sees USB transport and a serial number, rather than an ordinary
virtio disk relabeled as USB. Only regular image files are passed to QEMU.

Project policy currently disables hardware-assisted nested virtualization.
It was inspected through the existing Resource Manager API and not changed.
The x64 cloud host therefore runs QEMU TCG, not emulation on the development Mac.

## Original-source results (f7e28cc)

| Check | Evidence required | Current result |
| --- | --- | --- |
| BIOS USB full erase | Real wizard confirmation and nwipe completion; read back all 1 GiB initially filled with nonzero bytes | PASS |
| Correct disk only | Writable boot USB and unrelated writable 3 GiB canary disk retain their full SHA-256 hashes | PASS |
| Report export | Hot-inserted report USB; completion, checksum, clean-FAT, read-only verification and unmount | PASS |
| Ordinary BIOS and UEFI ISO boot | Actual welcome-screen markers | PASS |
| UEFI and enrolled Secure Boot USB | Welcome screen, target confirmation, actual SecureBoot=1 for enrolled probe | PASS |
| USB insertion into running Linux | QMP hotplug after the installed guest requests insertion; native Linux enumeration | PASS |
| Readiness failure cases | No exact EFI entry, pending one-time boot request, duplicate exact entries, and unconfirmed restart all refused | PASS |
| Guided handoff | Production app readiness/restart; firmware enters USB and live welcome screen appears | PASS |
| Visible UI | Captured QEMU screenshots of completed erase/report and Secure Boot confirmation | PASS |
| Focused keyboard repeat | Same full writable-USB erase with emulator keyboard trace and strict release acknowledgements | PASS |
| Default Everyday method | Emulated NVMe target; real PRNG overwrite and nwipe read-back verification, verified exported result, independent target scan | TIMEOUT at 27%; rerun pending |
| Cleanup | Receipts saved; VM/disk/IAP firewall/NAT/router/subnet/network absent | RUNNING |

The extra test harness is outside the product source and does not alter the
built USB payload. The desktop fixture uses a root service and headless browser
URL capture. It boots an installed Debian root filesystem extracted from the
built ISO, on a separate ext4 disk without `boot=live`; this is not independent
Ubuntu/Fedora distribution coverage. The test explicitly opens the launcher;
it does not demonstrate automatic application launch on insertion. It first tests the natural missing-entry fallback, then seeds exact
EFI entries only inside the disposable virtual PC to exercise supported and
ambiguous cases. The production launcher itself only writes BootNext.

This run does not represent a physical USB controller, physical firmware trust
store, Windows 10/11 desktop, Linux graphical permission prompt, or novice
usability test. Those limits remain separate from the requested VM simulation.
No release publication or physical disk erasure is part of this run.

## Intermittent input result

The first BIOS USB attempt reached DONE but failed the strict fresh Enter-release
acknowledgement. It did not run independent target readback or report export and
is recorded as a failed attempt, not a pass. A second attempt with the identical
product image and input sequence passed the release check, full erase, report
export, and all firmware probes. Additional diagnostics were added to the
external harness only. No product fix or established root cause is claimed.
The focused repeat with emulator keyboard tracing also passed the strict
release acknowledgement, full 1 GiB readback, report export, and protected-disk
hashes. That is two passing full quick-zero runs after the initial failed
attempt. It does not establish the cause of the initial failure.

The quick-zero screen correctly says that nwipe did not perform verification.
The test host independently read every byte of the 1 GiB target afterward. A
separate default Everyday run will require actual nwipe read-back verification.

## Primary run identity

- QEMU 7.2.22 (Debian 1:7.2+dfsg-7+deb12u18+b3), x64 TCG.
- Runtime source: `f7e28ccd6ea39b4b4de37765f66d204f61047e4d`.
- ISO SHA-256: `b20dd3afaf9026af0da1341faf53dac04a990ce64b7114325df22a63d8b64c4e`.
- USB image SHA-256 before and after both the firmware matrix and Linux handoff:
  `f0f9ebf4340bce60f889da4b21ad07f733f4b2742908e58eb50be60e70ef7bc7`.
- Unrelated writable 3 GiB canary SHA-256 before and after the matrix:
  `3ce2c364a9d4d9b0e019cafbfa4561318f4ec7ce6853c538f0e765efa40c44a8`.
- The newly built desktop launchers passed native Linux race tests, vet, and
  532,808 fuzz executions; both Windows and Linux binaries built successfully.

The installed Linux fixture first booted without a USB device. The host then
used QMP `device_add` to insert the removable xHCI mass-storage device. After
negative-case checks, the production launcher requested the one-time restart.
OVMF actually loaded BootBEEF from the USB partition and EFI loader, and the
shipped live application emitted `BEAMO_WIPE_SCREEN_WHAT`. This passed with
the original USB image unchanged.

The emulated NVMe check covers the disk address range visible to nwipe. It does
not emulate physical flash remapping or prove a hardware sanitize operation.

## Keyboard safety correction

The successful trace contained an autorepeat release processed while Enter was
still held. Three isolated Xvfb regressions reproduced a separate safety defect:
if Tk idles between the X11 release and matching press, Enter can skip Method
or claim erase after the countdown, and Space can toggle ownership twice.
All three failed before the fix and passed afterward. The fix retains the
server release timestamp and rejects the matching repeat press even after an
idle callback, for both Enter and Space. A separate physical press still works.
Local Python checks passed (1,404 passed, 138 skipped); isolated Linux Tk runtime
checks also passed. The required full hosted gate and rebuilt USB verification
remain pending. No release is authorized or published.
