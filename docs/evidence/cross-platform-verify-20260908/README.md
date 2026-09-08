# Independent cross-platform verification — 2026-09-08

Status: **local verification complete; full cross-platform acceptance incomplete**.
This second pass began from remote-confirmed `1ccac62f95d47ef4448b038de8a87e881ac7980e`
on `codex/cross-platform-20260908`, with base `7bc73a0cafeb7338528ffa0915cbc811681e1368`.
The source changes and new receipts are in the commit containing this report.
`source-snapshot.json` binds reviewed source bytes; the final handoff and PR
record the commit SHA and the newest hosted check result.

[Draft PR #5](https://github.com/BeamoINT/beamo-wipe/pull/5) remains the delivery
vehicle. No main-branch push, merge, release, ISO publication, physical-device
write, host firmware change, host restart, or real nwipe execution occurred.
Tests used fake disk/firmware data and regular temporary files. The unrelated
pre-existing `.ui-baseline-tests.log` was left untouched and uncommitted.

## Review and fresh plan

Read AGENTS/CLAUDE, durable memory, claims, README, compatibility matrix,
desktop design/validation/hardware acceptance, CI and VM guidance, first-pass
receipts, and the changes introduced by `6bb4a0c` and `1ccac62`. Re-examined
application dispatch; discovery and safety; pinned runner argv/start/completion;
confirmation, refresh, cancellation and report/shutdown transitions; Tk, GTK and
console action wiring; export worker identity and persistence/readback; Go
shared plan/server/firmware transactions and Linux/Windows platform code;
ISO staging, manifest binding, FAT32 assembly, EFI/Syslinux configuration and CI.

The plan was to establish uncached local baselines, explicitly test each first-pass
claim, reproduce adjacent defects with fixtures, repair them, then rerun the full
matrix. Earlier logs were comparison material, never receipts for this run.
No bounded test or code review can establish universal product correctness.

## First-pass claims independently checked

| Claim | New evidence and verdict |
| --- | --- |
| Fixture discovery does not mix fake inventory with host mounts/cmdline | Full suite plus `test_injected_inventory_never_reads_host_boot_metadata`, conflicting explicit metadata, fake CLI refresh and production metadata spies pass. No real discovery was opted into. |
| Non-Linux live detection runs before `/proc` | Darwin, Windows and FreeBSD simulated platform cases pass with a forbidden `/proc` reader. Native Windows Python wizard support is not claimed. |
| Darwin selects by loaded Tk patch version | The mismatched Tcl/newer-vs-Tk/older regression passes in graphical mode. This pass also fixes rejected-runtime fallback and skips Tk probes in non-Tk modes; Aqua itself remains untested here. |
| Linux duplicate-MBR refusal matches Windows | Uncached Linux race suite passes duplicate signatures with different partition numbers, distinct identities, 512/4096-byte geometry and invalid alignment. Windows equivalent fixture suite compiles; native execution remains open. |
| Cancelled/expired checks cannot authorize restart | Both helper call sites still use `inspectPlan`; cancellation/deadline cases reject an otherwise ready snapshot. Single-use, busy, changed-state, BootNext readback/rollback and fake-firmware cases pass. No real restart was requested. |
| Windows UTF-8 inventory | Production PowerShell explicitly sets UTF-8. Unicode and 4K fixture tests cross-compile with pinned Go; Windows vet passes. **Not runtime re-proven:** Windows PowerShell and Win32 execution need a native worker. |
| FAT32 offset readback precedes success sidecars | Actual mtools regular-file tests pass for launcher/manifest corruption and offset mismatch. New MBR/extent checks reject structural corruption previously accepted; stale output sidecars are refused before extraction. |
| CI has FAT32 utilities and Windows test compilation | Inspected `ci-hosted.sh` and `ci-desktop.sh`: both tools are installed and Windows `go test -c` is a required command. Local FAT32 tests execute, with no tool-related skips; Windows tests compile independently. |
| Docs do not invent platform support | README preserves offline x86_64 PC erasure, Linux/Windows readiness-only launchers, preview-only macOS, Intel Mac picker best effort, and unsupported Apple Silicon/Chromebook/Android/RAID boundaries. Updated stale hosted-status, eMMC and `/proc` wording. Historical matrix rows remain historical. |

## New defects reproduced and repaired

1. **MBR corruption could receive a success receipt.** The old verifier read at
   a constant offset without checking the partition table. Eight regular-file
   corruptions still yielded successful sidecars: wrong partition start, wrong
   extent, inactive partition, wrong type, missing boot magic, zero disk
   signature, extra partition, and unaccounted trailing bytes. The verifier now
   checks the MBR signature, one active FAT32-LBA partition, nonzero disk ID,
   sector 2048 and exact image extent, then reads at the validated offset.
   `packaging-before-fix.txt`: 8 failed, 7 passed. The repaired packaging suite
   includes actual FAT32 success and existing corruption regressions.
2. **Darwin could fall back to a rejected Tk.** After all candidates failed its
   probe, the old launcher still ran the default Python as a graphical preview.
   It also opened probe windows for console/web/help requests. Automatic selection
   now uses the existing keyboard fallback with an explanation when no usable
   Tk >= 8.6.13 is found. Non-Tk modes skip probes. Explicit Python overrides
   retain their existing contract. `darwin-before-fix.txt`: 8 failed, 7 passed;
   `darwin-after-fix.txt`: 15 passed. These are interpreter simulations on Linux,
   not native macOS runtime evidence.
3. **Old success sidecars could outlive a failed retry.** The builder previously
   checked only that the image output was unused. It now requires unused image,
   checksum and JSON paths, including refusal of dangling symlinks. Four disposable
   repo preflight regressions prove refusal before extraction and preservation
   of earlier receipts. `sidecars-before-fix.txt`: 4 failed, 15 deselected.

No disk-selection code, nwipe flags, erase engine, confirmation gate, restart
transaction, or platform support scope was changed. nwipe remains pinned at
0.42 / `6082bde060091e66365d852a1877f2ee80c67105`.

## Fresh verification results

Environment and tool receipts: `environment.json`, `cross-compile.json`.
Debian Linux x86_64, Python 3.13.5, pytest 8.3.5, Go 1.26.5; the existing Go
archive was rehashed against the repository pin. Local pytest differs from the
hosted pytest 9.0.3 pin; results are not presented as that hosted environment.
Ruff 0.9.2 and ShellCheck 0.10.0 implement the actual blocking lint rules.

| Gate | Independent result | Receipt |
| --- | --- | --- |
| Unmodified full Python baseline | 1,695 passed, 12 skipped, 83.75 s | `python-baseline.txt` |
| Intermediate full run | 1 failed, 1,710 passed, 12 skipped; old test expected console to probe Tk | `python-intermediate-failed.txt` |
| Corrected intermediate run | 1,711 passed, 12 skipped, 84.98 s | `python-intermediate-passed.txt` |
| Final full `./scripts/test-all.sh -rA` | 1715 passed, 12 skipped, 85.56 s | `python-final.txt` |
| FAT32 and output preflight | 19 passed: 12 actual FAT32 roundtrips, 3 manifest refusals, 4 stale-sidecar refusals | `packaging-after-fix.txt` |
| Linux Go `test -count=1 -race -json ./...` | 21 top-level passed, 1 skipped; 41 passes including subtests | `go-baseline.jsonl` |
| Linux Go vet; Windows amd64 test compile/vet; Darwin arm64 test compile | All pass; native Windows/macOS execution not available | `cross-compile.json` |
| Existing bounded EFI-parser fuzz gate | 599,139 executions in 15 seconds, pass | `go-fuzz.txt` |
| Both production launcher builds | Pass, pinned Go; generated binaries kept out of Git | `desktop-build.txt` |
| Blocking compileall/ShellCheck/Ruff gates | Pass | `lint.txt` |
| Exact hosted negative-test function in disposable source copy | Deliberately broken safety rejected; restored e2e passes | `negative-gate.txt` |
| Linux Tk `./preview` | Window process remains alive for 5 seconds on private Xvfb, then scoped termination | `preview-smoke.txt` |
| Console/plain-console EOF and web/helper generation | All exit 0 | `preview-smoke.txt` |
| Actual desktop preview HTTP lifecycle | Ready, no-op restart, failed recheck, stale-plan 409, Close and process exit pass | `desktop-preview-api.json` |
| Local ISO prerequisite check | Exit 2: Docker absent | `local-iso.txt` |
| Direct full Cloud Build submission | Exit 1 before build creation: forbidden source-bucket access | `cloud-submit.txt` |
| Native cloud-worker discovery | Permission denied despite gcloud returning exit 0 and `[]`; not a valid empty inventory | `cloud-workers.txt` |
| Browser click-through | Blocked: in-app browser crashed; no alternative connected browser | `browser-blocker.txt` |

The old Tk regression now invokes graphical mode, preserving modern-interpreter
selection and forced dry-run assertions. It was not skipped or weakened to accept
an old Tk. Every full-suite failure and deliberate reproduction is retained. Captured text
logs have trailing whitespace normalized for Git; outcomes and diagnostics are preserved.
All 12 Python skips require an absent manufacturing ISO; there are no skipped
Tk/GTK/X11 or mtools cases in the final local run. Native Go inventory is the
explicitly opt-in test and was left off on this shared developer host.

## Platform acceptance matrix

| Surface | Re-proven here | Still open |
| --- | --- | --- |
| Linux live Tk/GTK/console | Fake-device state transitions, ownership/token/5 s gates, held-key isolation, refresh and view switching, runner refusal and outcome classification, report/export/shutdown fixtures | Actual final ISO boots and shipped-engine disposable-disk erasure; real USB/report persistence and hardware behavior |
| Linux desktop | Native race/unit/vet/fuzz; both builds; actual loopback preview service; firmware transactions with fakes | Native USB ancestry integration, desktop noexec/trust/polkit behavior, firmware handoff and real reboot acceptance |
| Windows desktop | amd64 executable and test compilation, vet; shared fixture logic exercised on Linux | New UTF-8/4K PowerShell tests and actual Win32 execution; Windows 10/11 Explorer, UAC/SmartScreen, firmware handoff and application veto behavior |
| macOS development | Simulated Darwin no-/proc detection, loaded-Tk selection, console fallback; Darwin arm64 Go unsupported-platform stub compilation | Native Aqua Tk open/close and native interpreter/package differences; no Mac wipe support |
| ISO/FAT32/EFI/BIOS | Source/manifest/staging/boot-config tests; actual FAT32 regular-file structural and hash readback; no physical device paths | Full 2 GiB source-bound image, current ISO, BIOS/UEFI/Secure Boot and QEMU erase/report gates |
| Physical acceptance | None | Every configuration in `docs/desktop-hardware-acceptance.md` remains NOT TESTED |

## Hosted identity and remaining blockers

Fresh GitHub observation confirms PR gate SUCCESS for the starting commit
`1ccac62`, build `cd0b2fbe-1089-4c08-b135-0bf62040aedb`; see `pr-baseline.json`.
That status is previous-head evidence, not proof for this commit. The PR gate
skips QEMU by design. Its new result is reported separately after pushing.

`./scripts/ci-cloud.sh` was rerun without publication flags and with inherited
substitutions removed. It failed before creating a build:

> The user is forbidden from accessing the bucket [beamo-wipe_cloudbuild].

The diagnostic mentions organization policy or `serviceusage.services.use` as
possibilities; the exact IAM cause is not established. Worker discovery also
reports missing `compute.instances.list`. No IAM changes or alternate-account
workaround was attempted. Docker, qemu-system-x86_64 and qemu-img are absent
locally, with no current ISO available. These checks remain blocked, not passed.

Browser attachment returned a crashed-page interstitial; the generated data URL
was blocked by Browser Use URL policy. Only the in-app browser was available.
No UI visual pass is claimed from the successful HTTP checks.

Residual risks include firmware/controller and USB bridge differences, Windows
restart veto leaving BootNext pending, Linux execution policies, unsigned Windows
launcher reputation, native Aqua Tk behavior, physical Secure Boot trust and
revocation state, and SSD hidden/remapped data outside overwrite coverage.
An earlier ISO/OVMF result or compilation cannot discharge those risks.

Next useful action: restore authorized full Cloud Build submission access and run
`./scripts/ci-cloud.sh` from the final feature tip with publication disabled;
execute the compiled fixture suite on an isolated native Windows x64 worker and
preview on macOS. Then validate the exact ISO/FAT32 hashes with BIOS+UEFI and
only disposable QEMU disks. Keep this PR draft pending the missing gates.
