# Google Cloud USB simulation — September 6, 2026

The requested VM validation passed, and it found a keyboard safety defect that
was reproduced, fixed, rebuilt, and validated. This is evidence for the tested
configurations, not a universal compatibility or flawless-operation guarantee.
The VM, its disk, and the temporary IAP firewall, NAT, router, subnet, and
network were deleted. Independent absence checks passed at
`2026-09-07T01:35:32.838482Z`.

Final runtime revision: `eee3b9834cdb0b833f5e52b33ec5c28d2e9a8578`.
The full hosted gate
[`b097a80e-3607-42ea-bf79-12e56bd0cc2c`](https://console.cloud.google.com/cloud-build/builds/b097a80e-3607-42ea-bf79-12e56bd0cc2c?project=368895881889)
finished **SUCCESS** at `2026-09-07T01:22:22.370086Z`. ISO and QEMU were enabled;
release publication was disabled. Hosted Python: **1,583 passed, 12 skipped**.
Local Python: **1,404 passed, 138 skipped**. Launcher, lint, preview, negative
safety, ISO, and QEMU stages all passed.

## What the VM actually simulated

Google Cloud VM `beamo-usb-lab-0906b` (ID `2885835090945917987`) used an
x64 `n2-standard-8` host in project `beamo-wipe`, zone `us-central1-a`, with a
100 GB disposable boot disk. It had no public IP. Temporary SSH access used
Google IAP on a dedicated network; all lab network resources are included in
cleanup. The VM had a two-hour automatic deletion limit.

QEMU 7.2.22 emulated PC firmware, an xHCI controller, and a removable USB
mass-storage device backed by the actual FAT32 product image. The guest saw
USB transport and a serial number. This was not a virtio disk renamed “USB.”
The boot USB was **writable** at the emulated-device level. An unrelated
writable 3 GiB canary disk was attached too. Full-file hashes checked that
both retained their bytes. Only newly created regular image files were passed
to QEMU; no physical user disk was erased.

The project disallows hardware-assisted nested virtualization. That policy
was inspected and preserved. The x64 cloud host used QEMU TCG; these results
are not performance benchmarks for physical computers.

## Results

| Check | Result and exact scope |
| --- | --- |
| Ordinary BIOS and UEFI ISO boot | PASS in the full hosted gate for the final revision |
| BIOS, UEFI, and enrolled Secure Boot USB | PASS in the full hosted gate for the final revision; the Secure Boot probe requires the actual guest variable to equal 1 |
| Full quick-zero erase and report export | PASS on a disposable 1 GiB target in the final hosted gate; original-source writable-USB VM runs also passed twice |
| Default Everyday method on NVMe | PASS on the final rebuilt USB: real PRNG overwrite and nwipe read-back verification of a 1 GiB emulated NVMe disk |
| Independent NVMe readback | PASS: all 1,024 initially nonzero MiB blocks changed; exported result independently required `outcome=verified`, `verify=last`, and `verified=true` |
| Correct disk only | PASS: writable boot USB and unrelated writable 3 GiB canary retained their full SHA-256 hashes |
| Report export | PASS: hot-inserted report USB, completion manifest, content checksums, clean FAT, read-only validation, and unmount checks |
| Held Enter on final USB | PASS: 30-second hold stayed on Method; release followed by a distinct press advanced once to Last chance, with no Working transition |
| Linux USB insertion and guided restart | PASS on the original-source VM: hot-insertion into an installed Debian fixture, production launcher, real firmware restart, and live welcome screen |
| Launcher refusal cases | PASS: absent exact EFI entry, pending BootNext, duplicate exact entries, and unconfirmed restart were refused |
| Visible UI | Actual QEMU screenshots inspected for completed erase/report, NVMe verification, and Secure Boot target confirmation |

The desktop launcher and USB-layout code did not change in the final keyboard
fix. The Linux handoff result remains evidence for those unchanged components;
it is not relabeled as a fresh handoff run of the final image.

## Keyboard defect and correction

The VM trace showed an autorepeat release processed while Enter was still held.
Three isolated Xvfb regressions then reproduced a scheduling defect: when Tk
idled between the X11 release and matching press, Enter could skip Method or
claim an erase after the countdown, and Space could toggle ownership twice.
All three failed before the fix and passed afterward.

The fix retains the server release timestamp and rejects the matching repeat
press even if an idle callback already ran. It applies to Enter and Space,
including buttons and the ownership control. A separate physical press still
works. Owner confirmation, exact target confirmation, the five-second delay,
boot-media exclusion, and the nwipe-only engine remain required.

A physical X-server experiment used genuinely held XTest input and actual
server timestamps while deliberately processing idle callbacks between repeat
events. The original handler advanced to Last chance; the fixed handler stayed
on Method. A normal 30-second QEMU hold on the original image did not reproduce
that particular event ordering. The final rebuilt-image hold test additionally
proved that releasing the key permits a distinct subsequent press.

## Retained failures and test corrections

- The first original-source BIOS USB attempt reached Done but missed the
  required fresh Enter-release acknowledgement. It was not counted as a pass.
  Two subsequent full runs passed. Its exact cause was not established; the
  separately reproduced autorepeat defect must not be presented as a proven
  explanation of that initial missing acknowledgement.
- The first 1 GiB NVMe run exceeded the test's 300-second deadline at 27%
  progress. The bounded deadline was increased to 1,800 seconds for emulation.
- A corrected-image NVMe attempt completed and passed independent target
  readback, but the final checker incorrectly expected the report's
  `verification.requested` field to be boolean. The schema uses `"last"`.
  The assertion was corrected, report data was retained, and the full test
  reran successfully. No product change was made to accommodate that mistake.

These attempts remain in the receipts. Passing retries do not erase them.

## Image and source identity

Final VM image, rebuilt directly from the committed fix:

- ISO SHA-256: `bc1f457501f54acc8f4ab423c204f2ab1610482791214a23144e0cc8367244b1`
- USB image SHA-256: `7cf084d644af3ecf29c04487888bcfc55e8132c6d62eb1fe8805ba518b896f08`
- Final independently scanned NVMe target SHA-256:
  `d25a7c61a63c7dfc87d82d035403e262745d7549469ab164988a20a439dd77bb`

The original VM matrix and Linux handoff used runtime
`f7e28ccd6ea39b4b4de37765f66d204f61047e4d`, USB SHA-256
`f0f9ebf4340bce60f889da4b21ad07f733f4b2742908e58eb50be60e70ef7bc7`, and
ISO SHA-256 `b20dd3afaf9026af0da1341faf53dac04a990ce64b7114325df22a63d8b64c4e`.
The canary's unchanged SHA-256 was
`3ce2c364a9d4d9b0e019cafbfa4561318f4ec7ce6853c538f0e765efa40c44a8`.
The original and final artifact identities are kept separate.

## Limits

The installed Linux fixture booted a Debian root filesystem extracted from the
ISO on a separate ext4 disk without `boot=live`. It used a root service and
headless browser URL capture. The test explicitly opened the launcher; it did
not demonstrate automatic application launch on insertion, a Linux graphical
permission prompt, or independent Ubuntu/Fedora distribution coverage.

The fixture first checked the natural missing-entry fallback, then created
exact and ambiguous EFI entries only inside the disposable PC to exercise
those cases. The production launcher itself only writes BootNext. Its final
request was followed by OVMF actually loading the USB EFI file and the live
application emitting its welcome marker.

This run does not certify Windows 10/11 desktop insertion/UAC/firmware handoff,
physical USB ports and controllers, physical firmware trust stores, or novice
usability. Earlier native Windows API/PowerShell fixture results are linked in
[desktop validation](desktop-validation-2026-09-06.md); they are not consumer
Windows USB acceptance. See the [hardware checklist](desktop-hardware-acceptance.md).

The emulated NVMe check covers storage addresses exposed to nwipe. It does not
emulate physical flash remapping or prove hardware sanitization. Apple Silicon
support and automatic application launch are not added by this validation.
No physical USB was flashed and no release was published.

## Evidence

- [Original VM matrix and Linux handoff receipt](evidence/vm-usb-lab-20260906.txt)
- [Keyboard before/after, final hosted gate, and rebuilt-image receipts](evidence/vm-keyboard-fix-20260906.txt)
- [Final NVMe erase and verified report screenshot](evidence/vm-20260906-nvme-verified.png)
- [Original quick-zero completion screenshot](evidence/vm-20260906-bios-usb.png)
- [Original Secure Boot confirmation screenshot](evidence/vm-20260906-secureboot-usb.png)
- [Original NVMe timeout screenshot](evidence/vm-20260906-nvme-timeout.png)

The receipts preserve source IDs, image hashes, deployed fixture hashes,
validation output, external test fixtures, and cleanup verification. The large
VM disks and build artifacts are disposable; durable evidence is stored here.
