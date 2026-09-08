# Cross-platform correctness pass — 2026-09-08

Status: local gates passed; full cross-platform acceptance remains **incomplete**.
Cloud Build could not create a build because access to its source bucket is
forbidden. No ISO was released or published, no host disk was passed to a VM,
no host firmware was changed, and no real nwipe executable was run. Work stays
on `codex/cross-platform-20260908`, based on latest main
`7bc73a0cafeb7338528ffa0915cbc811681e1368`. This report covers the source in the
commit containing it; the final task handoff records the exact branch tip/PR.

## Review and correctness plan

Reviewed AGENTS/CLAUDE and durable memory; claims, compatibility, desktop design,
hardware acceptance, CI and VM docs; README and helper; shared Go launcher,
Linux/Windows platform implementations and tests; Python entry, discovery,
safety, runner, wizard transitions, Tk/GTK/console action paths; report export
and shutdown; ISO staging/provenance and FAT32 assembly; existing desktop and
USB-lab evidence. Historical evidence was treated as prior evidence, never as
a result for this branch.

| Surface | Contract checked against code and tests | This pass / remaining boundary |
| --- | --- | --- |
| Linux live wizard | One shared state machine for ownership, exact token, five-second monotonic delay, explicit erase; view switching/refresh clears confirmation; uncertain boot/target identity refuses; runner pin remains nwipe 0.42 | Tk, GTK, console, discovery and runner fixture tests pass. Current-branch BIOS/UEFI boot and real-engine disposable-disk tests remain blocked. |
| Report and shutdown | Separate new FAT32 report USB, repeated identity checks, isolated mount worker, sync/unmount/read-only verification, explicit unsaved-report shutdown choice | Existing state and fake-I/O regression suite passes. Current-branch physical export/firmware behavior not tested. |
| Linux desktop | Read-only inventory, exact media-bound EFI entry, no pending BootNext, recheck/fingerprint after elevation, bounded helper, BootNext-only write/readback and rollback | Linux race/unit tests and vet pass; MBR ambiguity now matches Windows. Host inventory integration deliberately not opted in. Native USB/noexec/desktop trust/pkexec/reboot acceptance still needed. |
| Windows desktop | Win32 architecture/firmware queries, USB/non-system PowerShell inventory, exact entry, UAC, no forced application closure | Executable and native test suite compile; Windows vet passes. New Unicode and 4K-sector runtime cases compile but require native Windows execution. Server tests do not establish Windows 10/11 Explorer/SmartScreen/UAC or firmware acceptance. |
| macOS | Fake-disk Tk preview; never a live erase platform | Loaded-Tk-version selection and no-/proc behavior tested by simulation on Linux; Darwin arm64 Go stubs cross-compile. No native Aqua Tk run. Intel Mac picker guidance remains best-effort only; no Mac wipe support claim. |
| Packaging | Hybrid ISO and Syslinux/GRUB config, version/hash/manifest binding, one active FAT32 MBR partition with Windows-readable launcher files | Actual mtools readback succeeds on regular-file FAT32 fixtures and rejects corruption/offset errors. Full 2 GiB image, ISO and firmware boots not produced or verified here. |
| Browser/helper | Loopback Host/Origin/token authorization, bounded JSON, no platform mutation in preview, explicit restart and close | HTTP lifecycle plus Go authorization tests pass; web/helper pages generate. Browser UI attachment unavailable, so no visual click-through claim. |
| Unsupported platforms | Apple Silicon, Chromebook, Android, RAID, in-OS Windows/macOS erasure; Secure Boot refusal must not be bypassed | README/helper/launcher boundaries reviewed. Signed Debian EFI components do not establish universal Secure Boot support; firmware trust/revocations and physical testing still govern. |

## Fixes and regression coverage

1. **Fixture discovery no longer combines fake disks with host mounts/cmdline.**
   Omitted boot metadata defaults to empty only when an inventory payload is
   injected. Explicit conflicting inputs still fail closed; production discovery
   still reads real boot metadata. CLI fixture refresh preserves this separation.
   Tests: `tests/test_cross_platform_20260908.py`.
2. **Non-Linux live detection returns false before reading `/proc`.** Preview
   does not acquire a live recovery session on Darwin. This does not add Windows
   Python-wizard support; Windows uses the Go launcher.
3. **Darwin preview checks the loaded Tk patch version, rather than Tcl's.**
   The probe runs in a disposable process and exits without old Aqua Tk teardown.
   The regression supplies newer Tcl with older Tk and proves the next suitable
   interpreter is selected. Native Mac execution is still required.
4. **Linux desktop rejects duplicate MBR disk signatures even when partition
   numbers differ.** Existing partition-ID checks alone did not match Windows'
   disk-signature refusal. Tests also cover 512/4096-byte sector geometry and
   unaligned/unknown geometry. No erase or format API was added.
5. **Cancelled and expired compatibility checks cannot yield restart plans.**
   Both elevated platform helpers now use the same deadline-aware plan check as
   the UI. The regression feeds an otherwise ready snapshot after cancellation
   or deadline expiry and requires no fingerprint/direct plan.
6. **Windows inventory explicitly emits UTF-8.** This preserves non-ASCII device
   identifiers across Windows PowerShell stdout and Go JSON decoding. Added
   Unicode identity and MBR 4K-sector native runtime cases; execution pending.
7. **FAT32 validation reads from the assembled image at its partition offset.**
   It requires exactly both launcher entries and verifies the packaged manifest
   plus executable hashes. Success sidecars are written after readback, not
   before it. Tests use 64 MiB regular files and no mount/loop/device access.
8. **Native Linux inventory tests require explicit isolated-worker opt-in.**
   Hosted CI enables `BEAMO_DESKTOP_NATIVE_INVENTORY_TEST=1`; local fixture tests
   remain independent of host disk enumeration.
9. README now states the macOS/in-OS boundary and correct x86_64 Linux VM gate,
   and distinguishes the 2 GiB FAT32 image from ISO flashing. The compatibility
   matrix links this report without upgrading historical evidence to a new pass.

## Executed checks

Environment: Debian 13.6 x86_64, Python 3.13.5, Go 1.26.5 downloaded with the
checksum pinned in `scripts/ci-desktop.sh`, Ruff 0.9.2, ShellCheck 0.10.0.
`checks.json` records the results in structured form.

- Baseline full Python: **1,680 passed, 13 skipped**, 84.16 s.
- Final `./scripts/test-all.sh -rA` under private dbus + Xvfb 1600x1000 at 72 DPI,
  `BEAMO_ISOLATED_X11_TEST=1`, dosfstools/mtools on PATH:
  **1,695 passed, 12 skipped**, 85.01 s. All 12 remaining skips require the absent
  manufacturing ISO. Final test-name receipts: `python-final.txt`.
- Intermediate full run: **1 failed, 1,693 passed, 13 skipped**. Failure was
  `test_staged_chroot_package_matches_src` after editing the source: the existing
  ignored staging copy was stale. Synchronized the changed Python files, then
  reran the full gate successfully. No test assertion was weakened or skipped.
- Linux `go test -race -json ./...`: **21 top-level passed, 1 skipped**; 41 passing
  test/subtest events. Skip is the intentionally opt-in real inventory test.
  `go vet ./...` passes. Receipt: `go-linux.jsonl`.
- Windows amd64 `go test -c` and `go vet ./...`: pass. Darwin arm64 `go test -c`:
  pass. These are compilation/static checks, not native runtime tests.
- `BEAMO_GO_BIN=<pinned Go> ./scripts/build-desktop.sh`: both executable builds
  pass. Generated executables/images are not committed or published.
- Python compileall, full repository ShellCheck command and both blocking Ruff
  rule sets from `scripts/ci-hosted.sh`: pass. `git diff --check`: pass.
- Hosted `run_negative` function executed verbatim in a disposable source/test
  copy: deliberately broken boot exclusion fails as expected, source restores,
  clean e2e test passes. No shared-checkout mutation. `negative-gate.txt`.
- Actual `./preview` Tk entry remains running on Xvfb for three seconds, then
  only that preview is terminated. Web/helper generation and console EOF smoke
  return zero. The launcher preview's actual HTTP server passes initial state,
  explicit no-op restart, failed readiness, stale-plan refusal and Close.
  `desktop-preview-api.json` contains no session token.
- Seven regular-file packaging tests pass: three incomplete-manifest refusals
  and four actual FAT32 roundtrips (success, changed launcher, changed manifest,
  wrong offset). See `targeted-python.txt`.

## Blockers and residual risks

`./scripts/ci-cloud.sh` (without publication flags) fails before build creation:

> The user is forbidden from accessing the bucket [beamo-wipe_cloudbuild].

The error suggests organization policy or missing `serviceusage.services.use`;
this pass does not establish which is responsible and did not change IAM or
circumvent the source bucket. Exact error: `cloud-submit.txt`. No Cloud Build
success or current-branch BIOS/UEFI/Secure Boot/wipe proof is claimed. The local
environment has no Docker or QEMU executable and no current ISO; an existing
`/dev/kvm` node alone does not provide a gate.

Codex's browser webview timed out attaching to the preview and its surface
inventory contained no alternative browser. UI click-through remains unverified.
No Notion connector was available; this in-repository report is the handoff.

Native Windows PowerShell/Win32 regression execution, native macOS Tk open/close,
full source-bound ISO/FAT32-image BIOS+UEFI boots, disposable-QEMU erase/report
readback, and the physical acceptance checklist remain required. Physical
Windows 10/11 publisher/UAC behavior, Linux noexec/trust policies, firmware
BootNext support, application restart vetoes and retained BootNext, USB bridges,
SSD hidden/remapped areas and novice usability are not settled by unit tests.
Prior evidence under `docs/evidence/usb-lab-20260907/` remains historical.

Next useful action: restore authorized Cloud Build source-bucket access, run
`./scripts/ci-cloud.sh` on this feature branch with publication disabled, and run
the compiled Windows fixture suite on an isolated x64 Windows worker. Keep the
PR in draft until the missing platform/image gates are reviewed. Never use host
passthrough or a real host disk for verification.
