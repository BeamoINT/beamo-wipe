# Reusable USB simulation lab — September 7, 2026

The reusable lab is implemented under [tools/usb_lab](../tools/usb_lab/README.md).
The updated product passed the full hosted gate, the KVM boot/erase gate,
all 11 Linux USB cases and all seven explicitly scoped Windows 11 BOT cases.
The actual Windows launcher also restarted into the Beamo wizard with Secure
Boot enabled after correcting the lab's forced boot order. That handoff required
a fixture-prepared matching firmware entry.

This is substantial virtual acceptance, not a claim of flawless universal use.
Windows UAS still fails at driver startup. Slow Windows inventory checks and
slow startup remain observed limitations. Physical USB and vendor firmware
acceptance remain separate. The detailed failed attempts are preserved below.

## Acceptance at a glance

| Area | Result | Limits |
| --- | --- | --- |
| Linux USB 2/3 BOT and USB 3 UAS | Updated 11-case UEFI matrix passed | Installed Debian fixture; no independent distribution coverage |
| Actual Beamo boot and erase | Updated canonical gate passed BIOS, UEFI, enrolled Secure Boot, real nwipe and independent target readback | Disposable virtual target and firmware model |
| Windows Server 2022 USB 2/3 BOT | Earlier seven-case scoped matrix passed | Server BIOS, separate from Windows client acceptance |
| Windows 11 USB 2/3 BOT | Updated seven-case scoped matrix passed | Native Windows 11 Enterprise Evaluation, build 26200, setup complete, Secure Boot enabled |
| Windows USB 3 UAS | Server and Windows 11 driver startup failed, Code 10 | QEMU/Windows stack cause unresolved; BOT passes do not cover UAS |
| Windows launcher to live wizard | Actual button, firmware USB selection, Secure Boot and step 1 visually verified | Fixture-seeded entry; administrator session; no UAC prompt; slow startup |
| Native Windows Go suite | One complete direct run ended PASS; separate wrapper runs failed inventory deadlines | Timing-sensitive fixture remains; failed runs retained |
| Code gates | Local Go and full pytest passed; Cloud Build 81b86036 passed every stage | Release publication disabled |
| Cloud teardown | All three labs verified deleted; temporary policy override removed; SSH keys revoked | Final receipts below |
| Physical USB acceptance | Not established | Electrical, flash, vendor firmware, reputation/signing and human usability require physical testing |

## What is being simulated

An isolated virtual PC runs inside a temporary Google Cloud x64 host. QEMU
presents EHCI/xHCI controllers and removable USB mass storage, including bulk-only
transport and USB Attached SCSI. The guest uses its actual USB, storage, partition
and filesystem drivers. It sees USB descriptors, transport, serials, removable
state and device arrivals/removals. These are not cloud persistent disks renamed
as USB. [QEMU's documented device model](https://www.qemu.org/docs/master/system/devices/usb.html)
supports these devices, hotplug and USB packet capture.

A separate repository was unnecessary: the reusable controller, device profiles,
Linux/Windows probes, cloud lifecycle helper and capture validator are separated
inside the existing repository. Other applications can reuse the controller and
provide their own guest actions. The optional Beamo checks remain explicit.

The lab cannot reproduce flash wear/remapping, connector quality, power-supply
behavior, exact electrical timing, every vendor controller defect or physical
firmware trust store. It provides real OS driver coverage against a controlled
hardware model; physical acceptance remains a separate requirement.

## Initial lab identity (historical)

- Project `beamo-wipe`, zone `us-central1-a`.
- Host `beamo-usb-sim-0907`, instance ID `8042171882183819313`.
- `n2-standard-8`, official host image `debian-12-bookworm-v20260902`, 100 GB
  auto-delete boot disk, three-hour maximum runtime, dedicated private VPC/subnet,
  IAP-only SSH, no public VM address and no service account.
- The effective `compute.disableNestedVirtualization` policy was enforced. It
  was preserved; the guests used x64 TCG. These are not speed benchmarks.
- Product source: `f7b6490036d62281e2133da642557cee6710f081`; no application
  runtime source changes were required.
- ISO SHA-256: `f5a9902692dbcc545224fa60af20d447a8700aa198c1ec07c8b4357b4c7d1d45`.
- USB SHA-256: `0e1253417b388e38e9938113ee9e4030a8440a2e0bdb3d6f3d0883ebee31e43c`.
- Final Linux matrix: QEMU 10.0.2, Debian's official bookworm backport
  `1:10.0.2+ds-2+deb13u1~bpo12+1`; kernel `6.1.0-52-amd64`.

The guest fixture is a separate installed Debian filesystem extracted from the
product ISO, with the serial test service added. It boots without `boot=live`.
The product USB payload itself is unchanged. This does not establish independent
Ubuntu/Fedora or desktop-environment coverage.

## Final Linux UEFI matrix: 11 passing cases

| Case | Evidence and assertion |
| --- | --- |
| USB 2 bulk storage | Actual EHCI/USB enumeration, removable and writable state, write/readback, unplug, disappearance and reconnection; independent host readback after detachment. |
| USB 3 bulk storage | Same sequence through xHCI/SuperSpeed. |
| USB 3 UAS | Same sequence through the actual `uas` driver, with explicit bridge and disk serials. |
| Write protection | Guest read-only state, actual rejected write, unchanged full backing-image hash. |
| Duplicate identity | Two real emulated devices with the same serial; the probe refused ambiguous raw I/O and both images stayed unchanged. This is a harness safety assertion, not a product duplicate-disk test. |
| Injected read error | QEMU `blkdebug` injected EIO at a specified sector; actual guest I/O returned errno 5 and the image stayed unchanged. |
| Removal during I/O and replacement | Guest acknowledged its first flushed write before QMP unplugged the device; the write failed, the device disappeared and backing bytes proved I/O had started. A replacement with a different serial did not satisfy the stale identity. |
| Beamo launcher over USB 2 | Guest mounted the actual FAT partition, verified both packaged executable hashes and executed the real Linux launcher. It recognized its original USB and returned the specific missing-boot-entry fallback. |
| Beamo launcher over USB 3 | Same actual payload and launcher check through xHCI bulk storage. |
| Beamo launcher over UAS | Same actual payload and launcher check through UAS. |
| Unrelated canary | The independently writable, attached canary retained its complete SHA-256 hash. |

The product device was writable at the emulated hardware level. The desktop
probe mounted it read-only; its complete image hash stayed unchanged after every
profile. Each UEFI product check required the specific missing-entry message,
not merely `ready:false`. That matters because BIOS returns earlier, before
USB identity inspection. These CLI checks do not claim a graphical permission
prompt or a completed reboot handoff.

The original passing Linux run has thirteen nonempty USB captures containing
**15,006 capture records**. After the root-port correction, the full Linux matrix
passed again with **14,990 capture records**. The independent
parser checked file headers, USB link types, packet lengths, completeness of the captured record bytes
and hashes. Some records use snapshot truncation; captures do not preserve every
transferred byte. Large product-file transfers were excluded from captures.

The [final receipt](evidence/usb-lab-20260907/linux/attempt-5/receipt.json),
[QMP transcript](evidence/usb-lab-20260907/linux/attempt-5/qmp.jsonl),
[guest kernel log](evidence/usb-lab-20260907/linux/attempt-5/serial.log), and
[capture summary](evidence/usb-lab-20260907/linux/usb-pcap-summary.json) preserve
actual observations. The copied archive SHA-256 was
`d21ac639f3129e89faa5e7cad2aa1a6d462c58168484f2da1c2e0ebd24258b15`;
all 83 retained evidence-file hashes were independently verified after transfer.

## Independent Beamo boot and erasure gate

The unchanged `scripts/qemu-verify.sh` passed on the freshly built product image
on this Google Cloud host, using the original QEMU 7.2 package. It performed
real nwipe erasure of a disposable target, independent zero readback, shipped
wizard report export, clean-FAT/completion/checksum/read-only/unmount checks,
BIOS and UEFI boot, and ordinary plus enrolled Secure Boot USB boot. The Secure
Boot assertion checks the actual guest variable. Initial disk exclusion, pinned
nwipe invocation and report-helper crash isolation also passed.

See the [run log](evidence/usb-lab-20260907/linux/boot-gate/run.txt),
[target readback](evidence/usb-lab-20260907/linux/boot-gate/guest-target-readback.txt),
[report checks](evidence/usb-lab-20260907/linux/boot-gate/report-bundle.txt), and
[Secure Boot serial evidence](evidence/usb-lab-20260907/linux/boot-gate/secureboot-usb-serial.txt).
The recorded helper `Killed` line is the intentional helper-crash test, followed
by the passing assertion that no host-namespace mount remained.

## Harness failures retained and corrected

These were test-environment/probe issues, not demonstrated product defects:

1. The transferred clone's origin pointed at its local bundle. The provenance
   gate refused it. The origin was corrected to the verified repository URL;
   the source commit stayed unchanged and the normal build reran.
2. Initial UAS enumeration used a generated USB bridge serial rather than the
   expected SCSI-unit serial. Both fixture identities are now explicitly set.
3. The first unplug oracle allowed too few errno values. Linux returned ENOSPC
   after removal. The corrected test synchronizes on a flushed first write,
   requires device disappearance and changed backing bytes, and preserves the
   actual errno. No filesystem is involved in that scratch-device write.
4. The probe requested JSON PATH columns without `lsblk --tree`, so partition
   children were absent. Explicit tree output fixed the product-volume probe.
5. The redundant fourth run was stopped after the tree issue was identified;
   it is not counted as a pass. Final code handles SIGTERM through cleanup.
6. Local Unix-socket tests initially encountered macOS path-length and sandbox
   restrictions. Short temporary socket paths and approved socket access allowed
   the real protocol tests to run.

Attempts [1](evidence/usb-lab-20260907/linux/attempt-1/runner.log),
[2](evidence/usb-lab-20260907/linux/attempt-2/runner.log), and
[3](evidence/usb-lab-20260907/linux/attempt-3/runner.log) remain available alongside
the final pass. The final run independently confirmed its QEMU process exited
and its run-owned scratch directory was removed. A separate real-process
[SIGTERM regression](evidence/usb-lab-20260907/interrupt-check.json) passed: an
intentional interruption produced a failed-run receipt, stopped QEMU and removed
its scratch directory. This is not counted as a successful device matrix.

## Windows fixtures and validation status

The Server 2025 evaluation VHDX came from Microsoft's
[official evaluation download](https://www.microsoft.com/en-us/evalcenter/download-windows-server-2025),
filename `26100.1742.amd64fre.ge_release_svc_refresh.240906-0331_server_serverdatacentereval_en-us.vhdx`,
SHA-256 `2d175924c8e647969a82e36f931b22397108bd94a030e0e947b7e66e47e0be9a`.
Fresh qcow2 overlays protect that base. The main QEMU 10.0.2 fixture uses UEFI,
one virtual CPU, 6 GiB memory, SATA OS storage and no guest network. Earlier
QEMU 7.2 attempts and an independent no-SVM configuration did not complete a
matrix and are not counted as passes.

Server 2025 reached its installed-OS setup console, version 10.0.26100.1742.
Its native `dir` command [read the emulated FAT USB](evidence/usb-lab-20260907/windows/server2025-usb-volume-read.png)
and the exact probe file. The initial matrix timed out before native inventory,
with no scratch devices attached, and removed its scratch directory. A separate
600-second readiness request also timed out. PowerShell storage discovery and
native service/process queries were slow during “Getting ready.” WMI and
Storage Service were already running; Virtual Disk was stopped and a test-only
start request entered START_PENDING. These observations do not establish a
product defect or a completed Windows USB matrix.

The independent Server 2022 evaluation VHD came from Microsoft's
[official evaluation download](https://www.microsoft.com/en-us/evalcenter/download-windows-server-2022),
filename `20348.169.amd64fre.fe_release_svc_refresh.210806-2348_server_serverdatacentereval_en-us.vhd`,
SHA-256 `588355586a3b99f1d47cee02f4861680a7e1bcb353582fbe7da11e2988e7562f`.
It uses a fresh overlay, BIOS, two virtual CPUs, 4 GiB memory and no guest
network. Setup completed and the native inventory reported Windows Server 2022
Datacenter Evaluation, version 10.0.20348, build 20348. The extra guests shared
the same bounded cloud host; no additional cloud VM or network was created.

The first native matrix exposed a real harness defect: seed media, pointer and
keyboard occupied root ports. QEMU silently inserted a 12 Mb/s hub for subsequent
storage, then rejected UAS with a speed mismatch. Consequently that run is FAIL;
its earlier USB 3 label is not accepted as SuperSpeed evidence. Cleanup also
missed the partly realized UAS object. The fix reserves explicit root ports and
tracks device/backend ownership before the SCSI realization steps. The new
regression failed before the fix and passed afterward. The orphan was explicitly
unplugged, DEVICE_DELETED was observed, and its block node was released.

With the seed/input devices removed from the reserved ports, the corrected run
passed native OS inventory and USB 2/USB 3 bulk-storage write, readback, unplug,
disappearance, reconnect, and independent host readback. UAS attached through
the explicit xHCI root port but never appeared in Get-Disk within 40 seconds.
The [full receipt](evidence/usb-lab-20260907/windows/windows-results-2022-2/receipt.json)
remains FAIL, with three completed cases and successful scratch cleanup. The
[timeout inventory](evidence/usb-lab-20260907/windows/windows-results-2022-2/enumeration-timeout.json)
shows only the SATA OS disk and the unrelated USB canary. This does not prove
a Beamo defect or establish the cause inside the Windows/QEMU UAS stack.

[Protocol observations](evidence/usb-lab-20260907/windows/protocol-observations.json)
show the bulk-storage devices returned USB 2.00/3.00 descriptors, received
SET_CONFIGURATION and exchanged 1,034/1,263 bulk submissions in their initial
captures. The UAS capture has 26 records: Windows read USB 3.00 descriptors and
serial strings, but issued no SET_CONFIGURATION or bulk submission. This narrows
the observed failure to enumeration before storage I/O. Decoding uses the
[kernel-documented USB mmap record layout](https://docs.kernel.org/usb/usbmon.html);
these emulator captures do not measure physical signal quality.

A separate explicitly bulk-only follow-up repeated those two I/O cases, then
was interrupted during the read-only write probe to preserve evidence before
the fixed cloud deadline. Its receipt is also FAIL. It does not prove write
protection, product-launcher behavior or canary completion on Windows. The
full matrix was not weakened to hide UAS. No Windows 10/11 acceptance or Windows
UEFI restart handoff is claimed.

All 70 files in the final archive were hash-verified after transfer; archive
SHA-256: `808cf6c233f8bb94d8c761f66c547e3c9472c947ef11c619e4b3f6cbf90e2187`.
The independent parser validated 16,264 capture records for the corrected full
Windows attempt and 21,872 for the interrupted bulk-only follow-up. Packet
validity is not a passing behavior assertion. The archive also preserves the
[final Linux rerun](evidence/usb-lab-20260907/windows/linux-rootports/receipt.json),
which passed all 11 cases and proved QEMU exit and scratch removal.

## Code verification and remaining work

Final local Python: **1,413 passed, 138 skipped**. Nine new regressions cover unsafe
backing files, QMP events/errors, guest target bounds/ambiguity, replacement cloud
resource protection, incomplete packet captures, and failed Windows adapter
connection cleanup, partial UAS attachment rollback with explicit root ports,
and refusal to emit a PASS receipt when Windows USB cleanup fails.
The new cleanup regressions failed before their corrections
and passed afterward. Ruff and shell syntax checks
passed for the new tools.

An isolated verification commit, `57ef068f6a7e73cebe24e35502df191748d3a231`, was
submitted through the canonical full hosted gate. Build
[`d02d51c2-ed8b-4288-9d60-4b134d124ba7`](https://console.cloud.google.com/cloud-build/builds/d02d51c2-ed8b-4288-9d60-4b134d124ba7?project=368895881889)
passed at 05:57:50 UTC. Hosted Python reported **1,587 passed, 12 skipped,
2 deselected**. Every required stage passed, including ISO and QEMU.
The publication step explicitly recorded “Release publication disabled”; it did
not publish a release. The [build receipt](evidence/usb-lab-20260907/cloud-build.json)
and [full log](evidence/usb-lab-20260907/cloud-build.log) are retained.

The next isolated snapshot, `3a6d4c04abd4d5c1a0beaf19ecdbfd08eab4827d`,
was submitted as hosted build `7acccd73-58c1-4145-a43d-14f62a1e55ab`. It failed
the mandatory fresh Return-release acknowledgment after reaching the completed
wipe screen. The identical snapshot passed on retry
`675ae1c3-2e9a-4c29-8595-e2f06a0373ab`. Both
[failed](evidence/usb-lab-20260907/cloud-build-final-attempt-1.json) and
[passing](evidence/usb-lab-20260907/cloud-build-final-attempt-2.json) receipts and
full logs are retained. No assertion or timeout was weakened. This intermittent
acknowledgment failure remains visible; a passing retry does not explain it.

The root-port/rollback snapshot is
`60447bb22ef96fdd9397e56af45afe1d1a56b5f6`. Its canonical hosted build
`fb7ddd96-9aab-415f-8503-01b15fff7c95` passed all required stages at
08:00:28 UTC. Its [receipt](evidence/usb-lab-20260907/cloud-build-rootports.json)
and [complete log](evidence/usb-lab-20260907/cloud-build-rootports.log) were
retrieved after authentication was restored. Release publication was disabled.
[Harness hashes](evidence/usb-lab-20260907/harness-sha256-final.json) identify
the exact reusable files; the final Linux rerun and corrected Windows attempt
used these runtime bytes. Verification commits exist only in a disposable local
clone. The shared checkout and application source were preserved; no push,
release or deployment was performed.

## Remaining acceptance

- Resolve or explicitly qualify Windows/QEMU UAS compatibility. Native Windows
  evidence now identifies a device-start failure (Code 10), associated with
  `UASPStor`; the exact failing operation inside the stack is still unproven.
- Complete Windows 11 client acceptance on a practical prepared fixture or an
  explicitly authorized KVM host. The client booted, but its setup flag remained
  active; no normal session or native USB matrix completed. Server BIOS checks
  cannot establish Windows UEFI identity or automatic restart handoff.
- Test Windows 10 separately and complete Windows 11 checks, plus physical USB
  controllers, ports, firmware and user comprehension. Server results do not
  establish these.
- Retain physical testing for electrical behavior, flash wear/remapping and
  firmware quirks; those are beyond the virtual device model.

Insertion does not automatically run the application. Erasure still requires
an offline boot and explicit confirmation.

## First-host teardown

[First-host cleanup is verified](evidence/usb-lab-20260907/cloud-cleanup.json): no lab
instance, disk, firewall, router/NAT, subnet or network remains. The fixed
three-hour automatic deletion removed the instance between the first identity
check and explicit deletion; the first command reported that race. The second
cleanup reconciled the absent VM, checked the remaining resource identities,
deleted them and verified all six resource inventories were empty.

The temporary OS Login key was revoked and its absence verified. Local test
credentials were removed; the deleted cloud disk held all disposable guest
images. Standard Cloud Build source archives and logs remain as normal CI
provenance in the existing project bucket; this receipt covers the first host only.

## Resumed Windows follow-up

Authentication expired during a separate follow-up network setup, before VM
creation. Its [creation log](evidence/usb-lab-20260907/windows-followup-create.log)
is retained. After the user restored authentication, the network, subnet,
router and firewall identities were reconciled before reuse. Failed N2 capacity
requests in zones a and b left no VM or disk; those inventories were checked
before selecting the available E2 host.

The resumed host `beamo-usb-win-0907`, ID `6798786404839282832`, ran in
`us-central1-b` as `e2-standard-8`, with the same private IAP access, official
Debian 12 image, 100 GB auto-delete disk and no service account or public address.
Its automatic deletion deadline was **19:29:52 UTC** on September 7. The test guests
were stopped and their evidence verified locally before cloud deletion began.

The clean product rebuild passed desktop, ISO and USB packaging gates from
unchanged source `f7b6490036d62281e2133da642557cee6710f081`:

- ISO SHA-256: `50841b5ad32b23746c75533792ab325976dc697248321fd1f57597f3b3e7861c`.
- USB SHA-256: `34e6fae3021f73defbb38b90381eab870d1399613b93162f0087169327ddb221`.

The Windows runner now supports an explicit profile subset and records that
scope in its receipt. The default still tests all three profiles. A regression
also demonstrated that a cleanup exception could leave a PASS receipt; the fix
sets FAIL before propagating that exception and retains backing files when
removal cannot be established. This is a harness correction, not a product wipe
change. Final verification snapshot `c6540e09e1ad717c9932800edaae8908e840583f`
passed all required stages in hosted build
`8111167d-beed-4a9d-bda7-032fb18c76b3` at 17:08:41 UTC. The
[receipt](evidence/usb-lab-20260907/cloud-build-windows-final.json) and
[full log](evidence/usb-lab-20260907/cloud-build-windows-final.log) are retained;
release publication was disabled.
The earlier subset-only build was canceled as superseded, not counted as a pass.


An independent Windows 11 Enterprise 25H2 evaluation was installed into a disk
on the same bounded host, in a new 80 GiB qcow2 virtual disk with no host-device access
or guest networking. The official Microsoft ISO is image index 1, x86_64 Client,
build 26200.6584, 7,092,807,680 bytes. SHA-256
`a61adeab895ef5a4db436e0a7011c92a2ff17bb0357f58b13bbc4062e535e7b9`
matches Microsoft's published EN-US checksum. It uses OVMF's Microsoft-enrolled
firmware, SMM and software TPM 2.0, two virtual CPUs and 6 GiB RAM. The standard
unattended installer reached the deployed OS but remained in setup at cutoff;
no normal Windows 11 client acceptance is asserted.
The firmware also writes console text to COM2; nonempty serial output alone is
not native-probe readiness. A premature readiness request was stopped and is
not counted as a result.


The resumed Server 2022 full matrix completed native inventory and both USB
bulk-storage I/O sequences, then failed UAS detection. Windows assigned
`UASPStor` to `USB\VID_46F4&PID_0003\MSFT30USBLABPROFILE2` and reported
`ConfigManagerErrorCode: 10`, `Status: Error`, name “USB Attached SCSI (UAS) Mass
Storage Device.” Microsoft defines [Code 10](https://learn.microsoft.com/en-us/windows-hardware/drivers/install/cm-prob-failed-start)
as a failure to start the device; this alone does not identify which driver in
the stack failed or establish a Beamo defect. The failed receipt retained all
three requested profiles and confirmed scratch cleanup.

A separately scoped `--profiles usb2-bot usb3-bot` run then **passed all seven
cases**, with exit status zero and scratch cleanup: native OS identity, both
write/unplug/reconnect sequences, actual read-only write rejection with an
unchanged complete hash, both shipped launcher checks, and the untouched
canary. Windows read the product as a removable FAT volume (`F:`), verified the
Windows and Linux executable hashes through its own filesystem, and ran
`Start Beamo Wipe.exe --check-json` successfully. Both results reported the
specific legacy-BIOS manual-boot fallback, with `preview:false` and version
0.2.5. This does not claim UEFI identity validation or a completed restart.


The same rebuilt product was then opened graphically from its actual removable
`F:` volume in the Server guest's installed Microsoft Edge. The page rendered
its BIOS fallback; Check again completed; the scrollable help remained readable
and disclosed nwipe, unsupported platforms and the offline erase requirement.
Keyboard activation of Close displayed the closed-session message. Screenshots
preserve the rendered, rechecked, help and closed states. Fresh Edge startup was
slow under TCG; this is not a launch-time benchmark or a UAC-prompt test because
the fixture used its built-in administrator account. These observations do not
substitute for Windows 10/11 or physical usability acceptance.


The separate read-only native PnP query returned problem status `0xC0000001`.
That general failure value does not establish the exact failed operation.
The [full failed receipt](evidence/usb-lab-20260907/windows-followup/records/server-full/receipt.json)
and [seven-case BOT pass](evidence/usb-lab-20260907/windows-followup/records/server-bot/receipt.json)
remain distinct. The [rendered launcher](evidence/usb-lab-20260907/windows-followup/records/server-launcher-rendered.png),
[help](evidence/usb-lab-20260907/windows-followup/records/server-launcher-help.png),
and [closed state](evidence/usb-lab-20260907/windows-followup/records/server-launcher-closed.png)
record the actual GUI. All 51 retained Server follow-up files passed independent
SHA-256 verification after transfer; archive hash
`315a17c6188f44ea199aea7fd28d19cd7be9fb7c8b236a3b30c604907704ee5d`.
The retained captures contain 58,636 structurally validated records; 3,547
records have snapshot-truncated payloads, explicitly counted by the parser.
Full-image hashes and independent readback establish data integrity separately. Both visual-fixture captures were small enough to retain; their sizes, hashes
and packet counts are recorded.
The visual fixture detached its devices and removed its scratch directory;
the Server QEMU process then [exited successfully](evidence/usb-lab-20260907/windows-followup/records/server-process-exit.json).


A separate faster client-fixture preparation was also exercised while the
original installer continued. The ISO was mounted read-only; wimlib applied
image 1 directly to a new regular NTFS volume image with strict ACL handling.
The host assembled that image into a separate 80 GiB GPT disk with 260 MiB EFI,
16 MiB MSR and the remaining Windows partition. No host physical disk was used.
This uses wimlib's documented [NTFS image extraction](https://wimlib.net/apidoc/group__G__extracting__wims.html);
Windows PE boot-file configuration follows Microsoft's
[image deployment workflow](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/capture-and-apply-windows-system-and-recovery-partitions?view=windows-11).
Application and assembly completed. Independent comparison verified all
272,629,760 EFI bytes and 85,607,841,792 Windows-partition bytes, including
unallocated zero ranges; GPT validation also passed. This is preparation evidence only: that alternate disk has not been
booted or counted as Windows client acceptance. Its seed deliberately has no
automatic Windows PE repartition answer file. The original installer reached its
first installed-OS reboot at 18:46 UTC and continued into the next setup phase.


The [fresh policy observation](evidence/usb-lab-20260907/windows-followup/nested-virtualization-policy-observation.json)
still reports effective `compute.disableNestedVirtualization: enforced: true`.
A [proposed follow-up](evidence/usb-lab-20260907/windows-followup/kvm-followup-proposal.json)
would temporarily disable this one constraint only in project `beamo-wipe`, run
one private N2 KVM lab under the same three-hour deletion limit, restore the
prior project inheritance, and verify effective enforcement returns to true.
This has **not been applied**. It requires explicit permission because it changes
an existing enforced cloud policy beyond creating test VMs. Google documents
both the [policy control](https://docs.cloud.google.com/compute/docs/instances/nested-virtualization/managing-constraint)
and [supported host types](https://docs.cloud.google.com/compute/docs/instances/nested-virtualization/overview).
Hardware acceleration would make client testing more practical; it does not
establish that the Windows UAS startup problem would disappear.


During final setup inspection, the original guest's native console reported
`Microsoft Windows [Version 10.0.26200.6584]` from `C:\Windows\System32`.
A read-only registry query returned `SystemSetupInProgress = 0x1`. This confirms
boot into the deployed OS while setup remained active. It does not establish a
normal desktop session, native USB matrix completion or packaged-launcher
acceptance on Windows 11.


## Final Windows 11 outcome

The guest was stopped at 19:19 UTC with its post-reboot installer still showing
42%. Its [native setup-state screenshot](evidence/usb-lab-20260907/windows-followup/windows11-final/native-setup-state.png)
records version 26200.6584 and `SystemSetupInProgress = 1`; the
[final observation](evidence/usb-lab-20260907/windows-followup/windows11-final/final-observation.json)
and [receipt](evidence/usb-lab-20260907/windows-followup/windows11-final/receipt.json)
record zero native diagnostic JSON rows and no completed USB matrix. The native
CIM caption query did not return before it was interrupted. This is an incomplete
fixture setup result, not evidence that the product failed on Windows 11.
All 14 archive files were independently hash-verified after transfer; archive
SHA-256 `8dd5c30d85ab9c54e9342316377701cef47ec9dd754b12928cda315cb3872e3d`.

The [alternate native-preparation receipt](evidence/usb-lab-20260907/windows-followup/native-preparation/receipt.json)
and [byte comparison](evidence/usb-lab-20260907/windows-followup/native-preparation/verified-assembly.json)
cover image application, GPT validation and every byte of the EFI and Windows
partition images. The MSR was checked as part of the GPT layout. That alternate
disk was not booted and its Windows PE boot-configuration script was not run.
All 13 retained preparation files were verified after transfer; archive SHA-256
`6d7512f4c278bcd0a26155a08a16be9588468c6cd8b46619fcb0b1f11aae9053`.

An [independent process inventory](evidence/usb-lab-20260907/windows-followup/usb-final-processes.json)
confirmed no QEMU or software TPM remained on the host. The transient TPM unit
had already unloaded after guest exit. The read-only ISO mount was unmounted.


## Final teardown

The [follow-up cleanup receipt](evidence/usb-lab-20260907/windows-followup/cloud-cleanup.json)
and [cleanup log](evidence/usb-lab-20260907/windows-followup/cloud-cleanup.log)
record explicit deletion and six empty inventories covering instances, disks,
firewalls, routers, networks and subnets. Together with the first lab receipt,
this verifies teardown of both test environments. Large guest images remained
on the deleted cloud disks.

The [SSH key receipt](evidence/usb-lab-20260907/windows-followup/ssh-key-cleanup.json)
verifies that the exact temporary follow-up key is absent from OS Login and its
local private key was removed. Initial key-file removal returned success but
readback still found the key; removing its exact matching fingerprint resolved
that discrepancy. No unrelated SSH keys were removed.

The final [read-only storage report](evidence/usb-lab-20260907/windows-followup/storage-final.json)
reported no storage pressure, approximately 100.8 GiB free, zero deletions and no
errors. A [Beamo Brain handoff](evidence/usb-lab-20260907/windows-followup/brain-handoff.json)
records the partial acceptance results and the remaining Windows work. No product
release, publication, commit or push was performed during this lab work.


## Offline UAS comparison after teardown

The [descriptor comparison](evidence/usb-lab-20260907/windows-followup/uas-descriptor-comparison.json)
compares the successful Linux run with both follow-up Windows UAS captures.
All three contain identical, fully captured 86-byte configuration descriptors
(SHA-256 `06adc0d3768f5ee59088189f6090718c90e19bcf8666d759d7022f5ee75555f6`).
The Linux capture has one SET_CONFIGURATION submission and 657 bulk submissions;
the Windows captures have neither. Thus the retained evidence does not support
a difference in configuration descriptor bytes between these runs as the cause.
It does not prove that Windows accepts every descriptor field or identify the
failed driver operation. No speculative emulator or application patch was made.

The [read-only reproduction script](evidence/usb-lab-20260907/windows-followup/compare-uas-descriptors.py)
runs from the repository root against the three retained captures. It associates
control submissions with completions, checks captured configuration lengths, and
compares the full descriptor bytes using the
[kernel USB mmap record layout](https://docs.kernel.org/usb/usbmon.html).
The next runtime diagnosis needs Windows USB/PnP start-failure tracing; another
packet-only run cannot identify the failing operation inside UASPStor.
At that point the proposed cloud policy exception remained unapplied; the subsequent approval and KVM run are recorded below.


## Authorized KVM follow-up

The user explicitly approved a temporary project-only nested-virtualization
exception. At 20:38 UTC the inherited baseline was recorded and the exception
applied in `beamo-wipe`. After three capacity failures, one private
`n2-standard-4` host was created in `us-central1-b`, instance ID
`5538341188545978192`, with no public IP or service account. Its automatic deletion
deadline is 23:42:40 UTC. An actual QEMU `query-kvm` returned both `present: true`
and `enabled: true`; that diagnostic process then quit without a guest image.
[Policy, host and KVM evidence](evidence/usb-lab-20260907/kvm-followup/kvm-verified.json).

Automatic approval review initially rejected the upload. The user then explicitly
approved transferring the unpublished development source and test scripts to this
private host. All eight initial upload hashes matched on the host. The
[transfer inventory](evidence/usb-lab-20260907/kvm-followup/transfer-scope.json)
records the exact source revision and destination.

The product was rebuilt from `f7b6490036d62281e2133da642557cee6710f081`.
The [Linux matrix](evidence/usb-lab-20260907/kvm-followup/linux-records/linux/receipt.json)
passed all 11 cases with KVM, including all three USB profiles, actual packaged
launchers, fault cases and the untouched canary. Its QEMU process exited and its
scratch images were removed. The [canonical boot gate](evidence/usb-lab-20260907/kvm-followup/linux-records/boot/summary.txt)
also passed BIOS, UEFI, Secure Boot, actual nwipe erasure with independent target
readback, and report-export checks. All 62 retained build, USB and boot files
[matched their transfer hashes](evidence/usb-lab-20260907/kvm-followup/linux-transfer-verified.json).

Windows 11 Enterprise Evaluation subsequently completed installation in a KVM
guest with Microsoft-enrolled OVMF and a software TPM 2.0. No requirement bypass
was used. The completed runtime and cleanup results follow below.

A [live task-specific deadline process](evidence/usb-lab-20260907/kvm-followup/deadline-cleanup-armed.json)
is armed to begin teardown at 23:32 UTC, restore the project inheritance using
server-side etag protection, and revoke the temporary SSH key. This is a backstop;
its being armed is not proof that cleanup or policy restoration has occurred.


### Windows 11 KVM runtime and timeout feedback

At 21:29 UTC, native diagnostics reported Windows 11 Enterprise Evaluation,
build 26200, `SystemSetupInProgress = 0` and Secure Boot enabled. The full USB
matrix passed both BOT write/unplug/reconnect cases and failed at UAS enumeration.
Native PnP reported UASPStor Code 10. A separate BOT run passed write protection
but its packaged launcher returned the original-media refusal instead of the
required missing-entry fallback. Both failures are retained; neither counts as
a complete Windows acceptance pass.

Read-only diagnosis ran the exact product inventory script: it returned valid
USB identity and MBR partition data, but took 36.2 seconds during the early
session. The launcher imposes a 20-second check deadline. After the desktop
settled, the unchanged packaged launcher recognized the original USB and returned
the required missing-entry fallback in a 16.2-second complete probe call.

The feedback change in `desktop/main.go` distinguishes an expired deadline from
a completed media refusal. It tells the user to wait and use Check again. It
continues to refuse restart when the check is incomplete. A regression covers
the expired check and preservation of a completed identity refusal.
[Validation provenance](evidence/usb-lab-20260907/kvm-followup/timeout-fix-validation.json)
identifies isolated snapshot `22f40612bc9b4d0f6399951ed8828b4c16dbf848` and
hosted build `81b86036-5121-4720-859a-415fa6c222fc`. Local Go and the full local
pytest gate passed. The hosted build subsequently passed every stage with release publication
disabled; the updated KVM image also passed its full boot/erase gate and the
11-case Linux USB matrix. Native Windows follow-up is recorded below. No commit was made in the shared checkout and nothing was pushed
or published.


### Resumed Windows checks

The updated USB passed all seven explicitly scoped Windows 11 BOT cases:
USB 2 and USB 3 write/readback/unplug/reconnect, write protection, both packaged
launchers, and the unchanged canary. UAS remains failed and is outside that PASS.

Native event 1074 attributes the earlier clean shutdown to `wlms.exe`: the
Windows evaluation license had expired. No license, clock, Secure Boot or
BitLocker bypass was used. The same disk and virtual TPM were resumed normally.
The initial native Go test runs were retained: one hit the 20-second PowerShell
fixture deadlines, and a later run encountered DLL initialization failure near
the licensing shutdown. In the resumed session, the unchanged updated native
test binary reached a final PASS, including the timeout regression. The exported direct log ends PASS; its separately named `native-upd` file contains
`0`. A subsequent wrapper run still failed the MBR PowerShell fixture at 20.08
seconds. The native suite therefore remains timing-sensitive, even though the
timeout feedback regression passed. Both outcomes are retained.


## Final KVM evidence and graphical handoff

[All 218 retained files matched their transfer hashes](evidence/usb-lab-20260907/kvm-followup/final-transfer-verified.json).
The archive excludes guest disk images, installation credentials, private seed
files and TPM state. The 26 files exported from the guest through an exact,
disposable USB fixture also matched their Windows-generated hashes.
[Guest export verification](evidence/usb-lab-20260907/kvm-followup/final-records/handoff/export-verified.json).

The final tested source is isolated validation commit
`22f40612bc9b4d0f6399951ed8828b4c16dbf848`, based on shared checkout
`f7b6490036d62281e2133da642557cee6710f081`. The product change only corrects
misleading timeout feedback; it does not relax USB identification or restart
checks. The isolated snapshot also contains the reusable harness. The final
README adds the observed firmware-test guidance after runtime validation.
No commit was made in the shared checkout, and nothing was pushed or released.

- [Updated Linux matrix](evidence/usb-lab-20260907/kvm-followup/final-records/updated-linux/receipt.json).
- [Updated Windows 11 BOT matrix](evidence/usb-lab-20260907/kvm-followup/final-records/windows11-updated-bot/receipt.json).
- [Updated canonical boot/erase evidence](evidence/usb-lab-20260907/kvm-followup/final-records/updated-boot/summary.txt).
- [Actual Windows-to-USB handoff receipt](evidence/usb-lab-20260907/kvm-followup/final-records/handoff/receipt.json).
- [Windows native direct PASS log](evidence/usb-lab-20260907/kvm-followup/final-records/guest-proof/native-updated-direct.txt) and
  [separate wrapper failure](evidence/usb-lab-20260907/kvm-followup/final-records/guest-proof/NativeTestsUpdated/receipt.json).

The first actual restart returned to Windows. The QEMU installation recipe still
forced CD/OS boot indices. OVMF's [boot-order implementation](https://raw.githubusercontent.com/tianocore/edk2/master/OvmfPkg/Library/QemuBootOrderLib/QemuBootOrderLib.c)
can prune unmatched HD entries when applying QEMU's boot order. With both host
boot indices changed to `-1`, the fixture recreated its exact entry and the real
launcher button restarted into `Boot9001`, GRUB, the signed Linux kernel, and
Beamo's step 1. The EFI stub explicitly reported Secure Boot enabled. This
controlled repeat supports the boot-order explanation; it does not establish
behavior on every physical firmware implementation.

The first live-wizard screen took several minutes to appear. The captured wizard
was readable at 1024 by 768 within the QEMU display; no erase began. This is
functional handoff evidence, not proof of fast or seamless startup. The fixture
installer script is retained only as test evidence and must never ship in the
product or run on customer machines.

Windows UAS still fails before storage enumeration. Native ETW and PnP identify
UASPStor, Code 10 and status `0xC0000001`. The trace's later USB port-change error
coincides with the test's unplug, so it is not claimed as the driver-start root
cause. Raw ETL, tracerpt XML (including loose-schema output), summary and packet
captures are retained under the final records. No speculative UAS patch was made.

The Windows evaluation reported an expired license and one native licensing
shutdown. The same disk and TPM resumed normally; no licensing or security bypass
was used. Future acceptance needs a currently valid client image, Windows 10,
additional Linux distributions, physical USB/controller/firmware combinations,
and standard-user permission/reputation behavior. A normal USB cannot promise
that inserting it automatically launches an application on arbitrary Windows
and Linux systems. The launcher still requires opening, and erasing the running
system disk still requires leaving that operating system.


## Final cleanup verification

The final [cloud state](evidence/usb-lab-20260907/kvm-followup/cloud-state.json)
reports `CLEANUP_VERIFIED` after deleting the VM, its auto-delete boot disk and
dedicated network resources, with empty readback inventories. All guest QEMU and
virtual TPM processes had already exited; the caller-owned handoff scratch
images were removed before the host was deleted.
[Guest lifecycle proof](evidence/usb-lab-20260907/kvm-followup/final-records/handoff/process-exit.json).

The project-only nested-virtualization override was removed with its recorded
etag, restoring the prior inherited enforced restriction.
[Policy restoration](evidence/usb-lab-20260907/kvm-followup/policy-restoration.json).
The exact temporary OS Login key was removed and absence verified; the local
private/public key files were deleted.
[Key revocation](evidence/usb-lab-20260907/kvm-followup/ssh-key-cleanup.json).
The deadline watchdog was stopped only after those checks passed.

The final read-only storage report showed no storage pressure, no errors and
zero deletions. The validation checkout and its Git history remain preserved.
[Storage receipt](evidence/usb-lab-20260907/kvm-followup/storage-final.json).

The [Beamo Brain handoff](evidence/usb-lab-20260907/kvm-followup/brain-handoff.json) records the verified scope and next acceptance work.
