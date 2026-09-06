# Desktop USB validation — 2026-09-06

Current runtime source: `f7e28ccd6ea39b4b4de37765f66d204f61047e4d` on
`codex/desktop-entry`, integrated into the local project. Its full build
`67eda7ba-a18b-4ce9-90bd-da8d9932b838` is **pending**. The previous complete
build `850fb9bf-c213-4648-b1f8-d4a98a2e5f47` passed for source
`6904d80c8b26fdf5a794f11490c947a0fc16bf6b`; it does not validate the later Linux
inventory correction. The new native-utility test and firmware handoff must pass.
No release has been published. Validation images are ephemeral; no physical
USB was flashed and the existing public v0.2.5 release was not replaced. This report distinguishes implemented behavior
from runtime, boot, and hardware evidence.

## Implemented

- Portable x64 Windows/Linux launchers with an embedded, offline browser UI.
- Automatic read-only readiness check after the user opens the application.
- One explicit restart action only after an exact existing USB boot entry is
  matched; permission, device-change, ambiguity, and pending-startup checks.
- A Windows-readable FAT32 USB image, alongside the conventional ISO.
- Signed Debian EFI boot components and ordinary BIOS boot assets.
- The live nwipe workflow still owns all disk selection and erase confirmations.
  The boot USB remains excluded and desktop restart never authorizes erasure.

## Executed evidence

- Integrated local Python: **1,404 passed, 135 skipped** (30.31 seconds).
  An ignored generated source copy from the prior build was refreshed after
  its consistency check identified stale `release_manifest.py`.
- Isolated fresh-clone Python: 1,390 passed, 147 skipped, 2 deselected (21.61 seconds).
  The deselected tests require live-build-generated `bootstrap` and `binary`
  configuration files that this fresh macOS clone lacks; an unfiltered run
  confirmed those two expected missing-file failures. The native ISO and boot
  gate remains required. Skips include display and manufacturing-image tests,
  an optional module, and isolated X11.
- Go: local race tests and vet; Windows/Linux cross-compilation; native Linux
  race tests, vet, and bounded boot-option fuzzing on Cloud Build.
- Native Windows Server 2022 AMD64: actual Win32 platform APIs; actual
  PowerShell parsing of safe GPT/MBR fixtures; refusal of duplicate identities,
  running-system disks, non-USB disks, and absent identity. Full fake-firmware
  transaction and local-server authorization suite passed. Receipt:
  `docs/evidence/desktop-windows-20260906.txt`.
- Browser preview: readiness, explicit no-op restart, visible completion,
  narrow viewport layout, refresh continuity after removing the opening URL
  fragment, Close removing all controls, and no platform mutation in preview.
- Isolated Xvfb regression: both virtual and server-delivered Enter releases
  through the erase-start redraw passed. No real device was erased.
- Final-source hosted Python gate: 1,578 passed, 12 skipped, 2 deselected (147.62 seconds); lint,
  preview, native Linux launcher tests, and the fail-open negative test passed.
- Full boot build `e7ef9ce6-de24-4131-bcfc-b6d834c7edde`: ISO provenance,
  BIOS erase/report export and ordinary UEFI boot passed. BIOS boot of the
  new FAT32 image timed out. A minimal BIOS reproduction found Syslinux
  reporting "No configuration file found". Installing to `/isolinux` instead
  of `isolinux` fixed that same test image, verified before/after in build
  `d001dd5d-88c2-46a7-b602-408ba056aeda`. The corrected full run reached BIOS USB confirmation; its additional
  check then used the ISO layout serial token instead of the USB layout
  unique-size token. The product correctly refused that incorrect token.
  The harness now enters the 1 GB size for this fixture; the full rerun passed.
  Redundant builds were canceled rather than claiming they passed.
- Previous complete hosted boot build: **PASS**. BIOS ISO erase/report export,
  UEFI ISO boot, and BIOS/UEFI/Secure Boot FAT32 USB boots passed. Each USB
  mode reached the disposable target confirmation and matched its required
  token. Secure Boot required the actual guest firmware variable to be 1
  with enrolled OVMF keys and SMM enforcement. The final publication step
  explicitly reported publication disabled. See the compact
  [boot receipt](evidence/desktop-boot-20260906.txt).
- Actual Linux desktop-to-USB firmware handoff: the private x64 test VM
  `beamo-handoff-test-0906` uses an installed Linux guest copy, the production
  launcher, and a seeded exact firmware entry. No erase is requested. A fixture
  GRUB module omission was corrected after it prevented the installed guest
  from starting. The running guest then exposed a real integration issue:
  `lsblk` with PATH-only columns emitted flat JSON, but media detection requires
  parent/partition relationships. The launcher now explicitly requests `--tree`;
  a new test invokes the native utility to check those relationships. Local Go
  race tests and unfiltered Python passed after the correction; the fresh full
  build and exact-source handoff are pending. Hardware nesting was unavailable
  because project policy disables it; that policy was not changed. The test
  uses TCG software emulation on x64, not physical PC hardware.

## Limits that remain

This is not automatic execution on insertion. Opening the application and
approving OS permissions are explicit. Windows executable signing/reputation
warnings and Linux execution/trust/noexec policies are not eliminated.

Both system and separate-drive erasure still require a restart. nwipe is the
only erase engine; native Windows erasure is not implemented. Installed-Linux
erasure is not enabled by weakening the existing live-session safeguards.

Direct restart requires an exact existing firmware entry for this USB. PCs
that expose only a generic USB device path or no entry after insertion need
the boot-menu fallback. The Linux helper also depends on standard disk tools,
EFI variable access, systemd restart support, and polkit when not already root. Firmware changes, USB/controller quirks, revocation updates, and
manufacturer trust settings can still prevent booting.

Windows Server fixture testing does not prove Windows 10/11 Explorer, UAC,
SmartScreen, physical USB mounting, or a real desktop-to-USB BootNext handoff.
Those remain hardware acceptance checks. OVMF boot testing is also not a
physical-machine or novice-usability certification.

Apple Silicon and Chromebooks remain unsupported. Intel Mac booting is
best-effort; the desktop launcher does not support macOS. Overwrite does not
prove sanitization of SSD hidden areas. The product still uses free nwipe;
its additional value is the media, guidance, safeguards, and support.

## Resource cleanup

The private Windows test VM, its disk, subnet, network, and temporary uploaded
test executable were deleted after capturing the checksum-bound test receipt.
Cloud builds are validation-only; no production release was published.
Final storage reporting showed 45.2 GiB free and deleted no files. The
reproducible temporary Go cache was registered with a one-day retention period;
source and Git history were preserved.

## Effect on the earlier customer complaints

| Complaint | Improvement | Remaining limit |
| --- | --- | --- |
| Expected Windows plug-and-play | A visible desktop application explains the process and checks readiness | Explicit launch, permission and restart still required; no in-Windows erase |
| USB not seen at boot | Ordinary boot retained; exact-entry guided restart and signed Debian EFI components added | BIOS/UEFI/Secure Boot USB matrix passed in QEMU; firmware, ports and trust settings still vary |
| Modern MacBook | Clear architecture refusal and unsupported-platform copy | Apple Silicon is not supported |
| Wrong disk or nothing happened | Boot USB exclusion and explicit live disk confirmation remain; desktop restart states that nothing has been erased | User must identify their intended disk; no automatic target selection |
| Honesty/value | Launcher, guidance, provenance and validation added; nwipe attribution retained | Open-source eraser, commodity media and SSD overwrite limits remain |

## Hardware acceptance still required

Use the [configuration record and case checklist](desktop-hardware-acceptance.md)
to preserve results without treating an untested configuration as accepted.

Test a manufactured USB on supported Windows 10/11 x64 PCs and Linux desktops.
Check file visibility and launch policy, actual UAC/polkit behavior, direct
restart when a matching USB entry exists, manual fallback when it does not,
cancelled restart, changed USB, and normal BIOS/UEFI boot. Secure Boot needs
physical machines with their actual keys and revocation state. Use disposable
targets for any destructive acceptance. Record machine/firmware and image
checksum; do not label an untested configuration as supported.

## Evidence links

- [Current exact-source full run](https://console.cloud.google.com/cloud-build/builds/67eda7ba-a18b-4ce9-90bd-da8d9932b838?project=beamo-wipe).
- [Corrected BIOS run with the subsequently fixed token fixture](https://console.cloud.google.com/cloud-build/builds/2df58471-eb18-4d3f-ae5a-3a1652ed3c7b?project=beamo-wipe).
- [BIOS configuration-path before/after reproduction](https://console.cloud.google.com/cloud-build/builds/d001dd5d-88c2-46a7-b602-408ba056aeda?project=beamo-wipe).
- [Earlier full run that exposed the BIOS USB failure](https://console.cloud.google.com/cloud-build/builds/e7ef9ce6-de24-4131-bcfc-b6d834c7edde?project=beamo-wipe).
- [Native Windows fixture receipt](evidence/desktop-windows-20260906.txt).

## Build and release boundary

Use the new `.img` for a USB that exposes the desktop launchers. The ISO remains
a conventional boot artifact. Merely extracting files or flashing the older
ISO does not establish the new desktop-readable layout. Before manufacturing,
run the full gate on a clean, versioned source tree and perform hardware
acceptance. An authorized release must publish matching source and checksums;
the publisher now requires the USB image, its ISO binding, and all USB boot
evidence. No release, signing, or manufacturing readiness is claimed here.

## Completion audit

| Requirement | Current evidence | Status |
| --- | --- | --- |
| Windows/Linux desktop entry | Both x64 executables compile; Linux race/vet/fuzz; native Windows API and PowerShell fixtures; browser preview | Implemented; physical desktop acceptance outstanding |
| Compatibility checks | Exact USB ancestry and partition identity; malformed/ambiguous EFI tests; native architecture refusal | Automated checks passed; real firmware inventory coverage limited |
| Guided restart | Explicit action, fresh elevated probe, BootNext read-back and rollback fixtures; no forced application closure | Implemented; actual desktop-to-USB handoff not yet proven |
| Ordinary BIOS/UEFI boot | ISO BIOS erase/report and UEFI boot; corrected FAT32 BIOS reaches confirmation | Automated matrix passed; physical acceptance outstanding |
| Secure Boot | Signed Debian EFI components and enrolled OVMF gate with actual firmware variable requirement | Enrolled OVMF gate passed; physical firmware acceptance outstanding |
| Disk safety and required confirmation | Existing fail-closed tests, negative mutation gate, disposable-disk erase/report; USB probes require target confirmation | Preserved; final USB probes passed |
| Desktop erasure assessment | nwipe-only engine and live-session requirement; no Windows engine and no installed-Linux running-system isolation added | Assessed; all erasure remains offline |
| Supported configurations and limitations | This report, desktop design, boot card, platform refusal, manifest compatibility wording | Documented; universal compatibility is not claimed |
| Delivery and cleanup | Integrated local branch; publication disabled; Windows test resources removed | Complete within local implementation scope |

The overall goal is not marked complete while the corrected-source full gate,
actual desktop handoff test, and physical desktop acceptance remain unproven. No test count substitutes for those
missing integration results.
