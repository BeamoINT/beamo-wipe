# Beamo Wipe — Evidence tiers, receipts, and revalidation

> **Version 1.0 — 2026-09-11 | Owner: Accountable senior engineer (this checkout)**
> Pinned wrapper `0.2.7` / `nwipe v0.42` commit `6082bde060091e66365d852a1877f2ee80c67105`
> Next review on any revalidation trigger below, or 2026-12-11.

Fixture runs, QEMU runs, and physical hardware runs prove different things.
This page defines the three tiers, what each tier never proves, the receipt
schema every executed claim needs, when a change forces revalidation, and —
for every supported combination — the best dated receipt on file or an
explicit `UNVERIFIED` gap. It is read together with
[`docs/compatibility-matrix.md`](compatibility-matrix.md) (which combinations
are supported), [`docs/qemu-verify.md`](qemu-verify.md) (how Tier 2 runs),
and [`docs/storage-and-controller-limits.md`](storage-and-controller-limits.md)
(what no tier certifies).

No tier issues a certificate. Evidence records what was overwritten and
checked; see `docs/storage-and-controller-limits.md` §2 (terminology) and §5
(when to use vendor tools or destruction instead).

## 1. Tier definitions

### Tier 1 — Fixture-tested (fake devices, no wipe)

`python3 -m pytest` with injected `lsblk` JSON (`tests/fixtures/*.json`,
`src/beamo_wipe/demo_*.json`), `BEAMO_WIPE_DRY_RUN=1`, `DryRunRunner`.
`NwipeRunner.start` raises instead of exec'ing; no `/dev` node is opened.

Proves: discovery parsing, boot identification logic, token rules, wizard
state machine, safety gates, UI layout/copy sync, evidence shaping.

Never proves: firmware boot, the ISO contents, `nwipe` behavior, storage
controller behavior, display hardware, or anything about a real disk.
A Tier 1 pass must never be cited for boot, wipe, or hardware behavior.

### Tier 2 — QEMU-tested operation (isolated x86_64, disposable disks)

`scripts/qemu-verify.sh` on an isolated x86_64 Linux worker (`docs/qemu-verify.md`):
exact manifest-bound ISO, read-only image inspection, the shipped `nwipe`
binary on re-proved disposable loops, SeaBIOS/OVMF guests with QMP-driven
wizard journeys on disposable `qcow2` targets, and read-only report checks.
No host block device or network reaches the guest.

Proves (for the executed build only): the ISO boots in the tested firmware,
the shipped wizard is the first UI, the shipped engine completes the tested
methods on virtio/file-backed targets, and the report bundle verifies.

Never proves: physical SATA/NVMe firmware behavior, USB bridges and hubs,
Secure Boot trust on real firmware, RAID, SSD spare-area coverage, panel or
lid behavior, or a human click-through of every screen. QEMU virtio is not a
storage controller model. A Tier 2 pass must never be presented as
physical-hardware proof.

### Tier 3 — Physical-hardware verification (named machine, disposable target)

An operator-run wipe on a named physical machine (vendor, model, firmware
mode and version, target model and bus) against a `DISPOSABLE`-labeled target,
recorded per the receipt schema below. Lab hardware only; never a
development or customer disk.

Proves: the executed combination on that exact hardware and firmware.
A Tier 3 receipt covers only its named configuration; it does not transfer
to other models, firmware versions, or capacities.

## 2. Receipt schema

Every Tier 2 or Tier 3 executed claim needs a dated receipt containing:

1. Date (UTC) and operator/author.
2. Build identity: wrapper version and source commit (plus dirty state),
   `nwipe` version and commit, ISO filename and SHA-256, manifest filename
   and SHA-256.
3. Environment: runner/host (arch, CPU, accel `kvm`/`tcg`), firmware used,
   X DPI where UI is judged, tool versions that matter.
4. Scenario: matrix IDs exercised (e.g. `FW-01`, `ST-03`, Everyday).
5. Result: pass/fail per scenario with the log or marker that decides it.
6. Limitations: what the run explicitly does not prove (nearest Tier 3 gaps).

Tier 1 evidence is the passing suite at a commit (CI log or local run line
with platform and Python/pytest versions); it needs no stored artifact, but
citing it must name the commit and the environment, never just "tests pass".

## 3. Revalidation triggers

| Change | Examples | Must re-run before the affected claim is repeated |
| --- | --- | --- |
| Wrapper release | `__version__` bump | Full hosted gate plus new Tier 2 executed receipt; prior receipts stay historical |
| Engine pin | `NWIPE_PINNED_VERSION` / `NWIPE_PINNED_COMMIT` | Full gate plus Tier 2 on all three methods; `docs/ADVANCED.md` check |
| Method mapping / argv | `methods.py`, `nwipe_runner.py` flags | Fake suite plus Tier 2 method boundaries and guest journeys; never `--force` |
| Disk selection / exclusion / identity | `discover.py`, `safety.py`, `inventory.py`, `identity.py` | `safety:` commit with a test; full pytest; Tier 2 boot probes |
| Wizard flow / gates / screens | `wizard.py`, `ui/*`, `copy.py` wording | Pytest plus Xvfb 72 DPI layout/keyboard suites; `docs/screens.md` sync (pinned by test) |
| Evidence / outcomes / reports | `evidence.py`, `outcomes.py`, `result_summary.py`, `privacy.py`, `support_export.py` | Evidence/report/shutdown suites plus Tier 2 report checks; `docs/runbook.md` sync |
| Image / boot / power config | `packaging/live/**`, `package-lists`, nwipe hook, xorg, keyboard, logind/sleep, bootloaders, kernel `linux-image-*` | `test_live_image.py`, lint, full ISO build, Tier 2 image inspection and `debsecan`; display/power rows re-checked |
| Verification workflow | `scripts/qemu-verify.sh`, `cloudbuild.yaml`, `scripts/ci-hosted.sh` | Shellcheck plus at least one executed Tier 2 run with the new workflow |
| New claimed hardware / firmware | Matrix row added or widened | Tier 3 receipt on the named configuration, or keep it unsupported |
| Docs / copy only | `docs/*`, `helper/*`, gallery | Link/text checks plus the suites named in §5; no Tier 2 needed unless a claim widened |

## 4. Per-combination receipt index (0.2.7)

`UNVERIFIED` means no executed receipt at the pinned build is on file; the
combination keeps only its Tier 1 fixture coverage (or nothing) until the
stated run happens. Historical receipts stay valid for their own builds and
never transfer to 0.2.7.

### Firmware and boot mode (matrix §4)

| IDs | Tier | Best receipt on file | Gap |
| --- | --- | --- | --- |
| FW-01 (SeaBIOS), FW-02/FW-04 (UEFI, Secure Boot off), FW-05 (CSM/virtio) | Tier 1 now; Tier 2 historical | Tier 2: [hosted 0.2.5 excerpts](evidence/bugfix-20260908/hosted-verification-excerpts.txt) (2026-09-08, wrapper 0.2.5: BIOS export, UEFI WHAT, BIOS/USB and UEFI/USB boots) | `UNVERIFIED` at 0.2.7: no executed `qemu-verify.sh` run on file for this source. The `feat/qemu-three-method-journeys` workflow is also uncommitted, so its three-method journeys have no receipt yet |
| FW-03 (Secure Boot enabled, unsigned image refuses) | Tier 1 + Tier 2 historical | Tier 2: same 0.2.5 excerpts (`secureboot-usb` probe) for refusal behavior | `UNVERIFIED` at 0.2.7 as above; refusal is by design per `docs/claims.md`, never a bypass |
| FW-06 (boot-menu keys) | Tier 1 (doc render) | `tests/test_helper_boot_guidance.py` (non-pixel) plus helper page | Physical key behavior per vendor is Tier 3 `UNVERIFIED` by nature; the card documents keys, it does not prove firmware menus |

### Boot-media identification (matrix §5, BM-01…BM-17)

Tier 1. Each row names its fixture test in the matrix. No Tier 2/3 receipt
applies: identification logic is fully fixture-covered and every uncertain
case fails closed (`selectable == ()`). Revalidation: any `discover.py` /
`safety.py` change is a `safety:` commit with a test.

### Storage topology (matrix §6, ST-01…ST-18)

Tier 1. Each row names its fixture or unit test in the matrix; all fixtures
are fake JSON (`tests/fixtures/*.json`). Physical controller behavior for
every ST row is Tier 3 `UNVERIFIED`: no physical destructive receipt is on
file for any model. SSD/NVMe rows additionally carry the §5 limits of
`docs/storage-and-controller-limits.md` — overwrite is not a certificate at
any tier.

### Display and resolution (matrix §7 / a11y matrix §5)

| IDs | Tier | Best receipt on file | Gap |
| --- | --- | --- | --- |
| DISP-01 (1024×740), DISP-02 (1280×820) | Tier 1 (Xvfb 72 DPI gate) | Hosted Xvfb suite per `docs/ci.md`; local runs are not the gate (VNC `:1` @96 DPI is excluded) | Dated 0.2.7 hosted run pending (branch unmerged) |
| DISP-03 (1366×768), DISP-04 (1920×1080) | Tier 1 by bounds | Interpolation of DISP-01/02 via `CONTENT_W 940` + `minsize`; no separate parametrization | No dedicated run; stated as interpolation in the matrix, not as measured |
| DISP-05 (800×600), 1024×600 | Tier 1 (adaptive) | `tests/test_adaptive_layout.py` at both sizes | Narrow widths need scroll by design; matrix states degraded width |
| HiDPI | Tier 1 structural | `test_tk_scaling_is_pinned_to_one` | No rendered HiDPI run; untested beyond pinning |
| Console 80×24 | Tier 1 | `tests/test_console_parity.py`, `tests/test_console_pick.py` | No physical serial-console run |

### Keyboard-only and input (matrix §8, KB-01…KB-08)

Tier 1. Rows name their tests (`test_tk_runtime.py`, `test_console_pick.py`,
`test_confirmation_gates.py`). No Tier 2/3 applies beyond the QEMU QMP key
sequences, which prove the guest journey path, not human input.

### Safety gates (matrix §9)

Tier 1. Each gate names its `SafetyError` spy tests; preview/dry-run engine
refusal is pinned by `test_confirm_erase_refuses_real_runner_in_dry_run`.
Revalidation: any gate change is a `safety:` commit with a test.

### Erase methods (Everyday / Extra / Quick zero)

Tier 1 now; Tier 2 historical. Mapping and argv are pinned by
`tests/test_method_operation_copy.py` and `docs/ADVANCED.md`
(`test_advanced_docs.py`). Last executed Tier 2 method evidence is the 0.2.5
hosted excerpts (nwipe boundary + guest export; the receipt's words are
"shipped Wizard zeroed the guest target prefill"); per-method
Everyday/Extra/Quick-zero journeys at 0.2.7 are `UNVERIFIED` until the full
gate runs with the committed three-method workflow.

### Report export and shutdown

Tier 1 now; Tier 2 historical. State rules are pinned by
`tests/test_report_shutdown.py`, `tests/test_usb_report_workflow.py`, and
`tests/test_runbook.py`; the 0.2.5 excerpts record a guest export with
clean-FAT, manifest, checksum, and unmount checks. A 0.2.7 export run is
`UNVERIFIED`. Shutdown power-loss behavior is unprovable by test by nature:
no report survives power loss unless exported (`docs/report-shutdown.md`).

### Screen reader (Orca/AT-SPI)

Tier 1 structural (GTK view + `docs/screen-reader.md`); a live Orca session
is Tier 3 `UNVERIFIED`. The accessibility matrix states this limit and must
not be cited as assistive-technology proof.

### Desktop launchers (Windows/Linux readiness)

`UNVERIFIED` for native execution. The [first pass](evidence/cross-platform-20260908/README.md)
and [second pass](evidence/cross-platform-verify-20260908/README.md) record their own
scope and explicitly leave native Windows/macOS runtime, USB trust/UAC,
firmware acceptance, and physical testing open. Those READMEs are receipts
for their commits only.

## 5. Automated drift checks (what the suite pins)

| Documentation | Canonical source | Test |
| --- | --- | --- |
| Method summaries in `docs/screens.md` | `METHODS[*].summary` | `test_storage_limits.py::test_active_support_docs_match_canonical_methods_and_outcomes` |
| Outcome announcements in `docs/runbook.md` | `VIEWS[*].announcement` | Same test |
| Working interactivity + Finished report actions in `docs/screens.md` | `copy.py` buttons/hints, `tk_wizard.py`, `accessible_wizard.py`, `console_wizard.py` | `tests/test_screens_report_actions.py` (new) |
| Method flags in `docs/ADVANCED.md` | `methods.py` + `build_nwipe_argv` | `test_advanced_docs.py` + `test_method_operation_copy.py` |
| Forbidden claims absent everywhere | `docs/claims.md` | `test_copy.py::test_claims_doc_forbids_bad_bullets`, `test_ui_system.py::test_no_forbidden_claims_in_any_surface`, `test_storage_limits.py` certificate pins |
| Receipt links in this page | `docs/evidence/**` | `tests/test_evidence_tiers.py::test_receipt_links_exist` |
| Staged image equals source | `src/beamo_wipe/` | `test_live_image.py::test_staged_chroot_package_matches_src` |
| Image packages / permissions / mirrors | `packaging/live/**` | `test_live_image.py` suite |
| QEMU workflow invariants | `scripts/qemu-verify.sh` | `test_qemu_method_journeys.py`, `test_qemu_diagnostic_markers.py`, `test_accountable_audit_2026_09_03.py`, `test_usb_report_workflow.py` |
| Manifest measured evidence + package inventory | `verification_evidence.py`, `release_manifest.py` | `tests/test_verification_evidence.py`, `tests/test_release_manifest.py` |
| Publisher signatures + key registry | `release_signing.py`, `publish_release_gcs.py`, `packaging/release-keys/` | `tests/test_release_signing.py`, `tests/test_release_publisher.py` |

## 6. Claims that remain unverified (2026-09-11)

1. Every `FW-*` boot claim at 0.2.7 — no executed Tier 2 run on file.
2. Every per-method Tier 2 journey at 0.2.7 (Everyday/Extra/Quick zero).
3. Every Tier 3 physical claim — no physical destructive receipt exists in
   this repository for any machine, target, or firmware.
4. Native Windows/macOS launcher execution, USB trust/UAC behavior, and
   firmware acceptance (cross-platform READMEs leave these open).
5. Live Orca screen-reader session behavior.
6. Physical lid, power-button, battery, panel-blanking timing, and any
   storage-controller or SSD spare-area behavior.
7. `dist/` holds only 0.1.0 artifacts; no 0.2.7 ISO, manifest, or sidecars
   exist locally. Nothing above implies a releasable 0.2.7 image.
