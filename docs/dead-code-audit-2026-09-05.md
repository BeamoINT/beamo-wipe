# Dead-code audit — 2026-09-05/06

Baseline: `8a548412baefcf5f83f894b3bc0803cec9a06c0f`, branch `main`.
The checkout was initially clean. A live `git ls-remote origin refs/heads/main`
check matched that exact SHA. Origin is `https://github.com/BeamoINT/beamo-wipe.git`.

The original cleanup passed full hosted validation at code commit
`5648821e99e3d4b7e46b7877a6bad36432c7f87a`. A subsequent main-trigger run
exposed a picker timing failure; the follow-up section records its reproduction
and repair. No disk-selection, confirmation, runner, or evidence policy
changed. Release publication remains disabled.

## Changes and removal proof

| Change | Evidence |
| --- | --- |
| Remove the private Tk `_primary_cmd` attribute: four assignments in `ui/tk_wizard.py` | The baseline contains exactly four references, all assignments. Production/test AST load scans, tracked string searches, generated staging searches, and class attribute-access inspection find no reader. `TkWizard` has no custom attribute-access hook. Dynamic self-attribute lookup names only draw generation and keyboard-release timer attributes. `_Button` keeps its own callback; `_primary_btn` passes `_nav(command)` directly; splash passes `_nav(w.skip_splash)` directly. `_on_return` dispatches by screen and independently checks owner, token, and erase readiness. No command/configuration/boot/recovery/hardware entry point names the removed field. |
| Split semicolon-separated statements in two UI test files | Resolves all 18 baseline Ruff E702 errors. Both complete test ASTs are identical to the baseline. No assertion, execution order, test, or skip was changed. |
| Refresh the generated staged Tk file | Its prior bytes matched HEAD. Only that ignored generated file was copied from current source after the staging parity test caught the expected drift. The real ISO builder deletes and restages tracked package source; this copy is not new-image evidence. |

An independent read-only review of the exact three-file code/test diff found no
actionable issue. The source AST equals the baseline after deleting precisely the four
assignments. Existing regressions cover keyboard navigation/countdown gating,
held Enter, stale erase callbacks, and responsive checking/stopping views. They
were preserved; no implementation-mirroring absence test was added.

## Scope and retained candidates

Inventory: 184 baseline tracked files, 28 Python source modules, 609
function/class definitions, three logo assets, three demo JSON files, and
16 disk fixtures. Scans covered source and test AST references, string-based
access, authored/generated packaging, CI, CLI/Make commands, boot hooks,
recovery APIs, package lists, UI dispatch, browser JavaScript, and hardware
fallbacks. No syntactically unreachable statement after unconditional transfer
or constant `if` branch was found in production Python. Generated gallery and
helper JavaScript had no single-occurrence named function leads.

Reference counts and AST scans are leads, not completeness proofs. The decision
rule was to retain any candidate with a test, dynamic, public, operator,
packaging, hardware, or uncertain use. Only the private assignment closure above
met the removal threshold.

| Surface or candidate | Evidence and decision |
| --- | --- |
| `MANIFEST_NAME_TEMPLATE` | One original tracked occurrence, introduced in `d238ed2`; shell generator constructs filenames directly. Retain the externally importable constant because external ownership is unproved. |
| `app.NWIPE_VERSION` | Public wrapper engine-version alias with operator/packaging documentation. Retain. |
| Tk `font_mono` | No authored reader identified, but construction registers a Tk font and exposes a public instance attribute. Retain because lifecycle/external consumers are not fully bounded. |
| `NAVY`, `NAVY_SOFT`, `NAVY_MUTED` | Tests consume them through string-based `getattr` for shared palette and contrast contracts. Retain. |
| `_log_tail`, `_last_logfile`, `_tk_wizard` | Read by string-based attribute access in runner/evidence/UI integration. Retain. |
| `Makefile` phony `lint` without a recipe | Existing externally invocable command behavior. Removing it could change `make lint`; retain. |
| Logos and demo/fixture JSON | Tk/gallery, package-data, scenario mapping, and explicit regression consumers. Every disk fixture has a test consumer. Retain. |
| `identify.py` and `identify-boot-usb.sh` | Manual module/CLI recovery surface preserved by existing sweep tests. Retain. |
| `read_diagnostics`, `build_evidence_for_wizard` | Support APIs explicitly preserved by existing sweep tests; external use uncertain. Retain. |
| `export_evidence`, `Wizard.export_evidence`, `done_ok` | Support/recovery and direct safety/evidence/result tests consume them. Retain. |
| `parse_percent`, `_target_last_percent` | Direct regression consumers cover engine log parsing, job normalization, and summary-zero handling. Retain. |
| `generate_manifest`, `write_manifest` | Embedded Python in shell manifest command consumes them; import-only source scan misses that entry point. Retain. |
| Tk, accessible GTK, curses/plain console | App flags, F8 switching, screen/generation-bound callbacks, and graphical failure fallback reach them. Retain. |
| Gallery/helper payload, JavaScript, CSS | Python payload/template insertion, DOM event handlers, screen/hash routing, dynamic classes, shared-copy/palette tests. Retain dynamic and contract surfaces. |
| Runtime flags | Boot-device/demo/dry-run flags support fake testing and are stripped on real live sessions; UI and graphical-unavailable flags support hardware fallback; NO_OPEN supports CI. Retain. |
| Build flags and diagnostic markers | ISO/version/destination/project/service-account variables cross shell/Python boundaries. Screen/report/discovery marker suffixes are constructed dynamically and consumed by QEMU. Publication/skip/dirty gates are operator contracts, not dead flags. Retain. |
| Preview scripts, aliases, macOS Python selection | Root preview delegates to its shell wrapper, CI uses web/console/helper modes, and Tk-version selection handles an established Mac compatibility issue. Retain. |
| Cursor environment/install/start/check scripts | External environment JSON, per-boot VM initialization, manual smoke command, nested Docker and Xvfb configuration. Retain. |
| Hook, launchers, systemd service, BIOS/UEFI configurations | Live-build consumes configuration by path. Hook enables kiosk service, masks gettys, pins/builds nwipe, and removes compiler tools. Kiosk starts X with console fallback and serial markers. Retain. |
| Xorg/profile sentinel/failsafe arguments | Mouse-free startup, driver probing, legacy firmware fallbacks, and suppression of live-config's conflicting X loop. Presence/absence and hardware behavior matter; retain. |
| Python dependencies | No declared runtime Python dependencies. Setuptools supplies the build backend; pytest supplies the dev gate. Retain. |
| Live-image packages | GUI/accessibility services, fonts, kernel/graphics/input drivers, engine libraries, and read-only nwipe discovery dependencies have direct, transitive, or hardware-probed uses. Retain uncertain/transitive dependencies. |
| CI, trigger installer, publisher | Cloud Build phase dispatch, GitHub event registration, and explicitly gated nondefault publication are external entry points. Retain. |
| Ignore/configuration rules | Git provenance is uploaded; generated live-build, cache, image, and preview outputs are excluded from Git. Retain. |
| Existing tests, documentation, licenses, mirrored instructions | Pytest collection, packaging/license copy, operator/recovery contracts, and external tooling reach these. Retain; test-only use was not classified as dead. |

## Original cleanup validation receipts

| Check | Result |
| --- | --- |
| Baseline `python3 -m pytest` | Exit 0: 1364 passed, 132 skipped |
| Focused dead-code/UI/confirmation/busy tests | Exit 0: 78 passed, 128 skipped (Mac has no display) |
| Final `./scripts/test-all.sh` | Exit 0: 1364 passed, 132 skipped in 31.20 seconds |
| Final `python3 -m pytest` | Exit 0: 1364 passed, 132 skipped in 60.87 seconds |
| `python3 -m compileall -q src/beamo_wipe` | Exit 0 |
| Prescribed ShellCheck command | Exit 0 for preview, scripts/*.sh, inside-docker, pinned nwipe hook |
| Both prescribed Ruff security selections | Exit 0 |
| Full Ruff 0.9.2 on source/tests | Exit 0; all 18 E702 findings resolved |
| `python3 -m mypy --ignore-missing-imports src/beamo_wipe` | Exit 0: no issues in 28 modules, local mypy 1.20.2; untyped-body informational note |
| Preview web/console/helper | Exit 0 using fake-disk wrapper and NO_OPEN; gallery/helper files present, console shows preview splash and exits on EOF |
| Gallery/helper `node --check` | Exit 0 for both extracted generated script bundles |
| Local negative phase | Unchanged `run_negative` body executed in isolated temporary clone without Linux apt installer; deliberate broken-guard test fails, restored-source test passes, final exit 0 |
| Python sdist + wheel | `python3 -m build --no-isolation` exit 0; all 34 tracked package files in both archives match final source bytes |
| Installed wheel smoke | Fresh temporary venv, no dependency downloads; `beamo-wipe --version` and `--demo --console` exit 0 |
| Independent exact-diff review | No actionable findings; test AST equivalence and assignment-only source diff confirmed |
| `git diff --check` | Exit 0 |
| Storage reports | Before build validation: 46.8 GiB free; no deletion performed. Final report: 46.7 to 46.9 GiB free, report-only, zero deletions |

Local GUI tests skip when there is no macOS display. Accessible Linux UI,
Xvfb layout, actual ISO, and isolated BIOS/UEFI validation passed in the full
hosted run below. The local mypy version differs from hosted CI's configured
2.1.0; both the local and hosted type checks passed. No dedicated formatter is prescribed in project
metadata, Makefile, contributing instructions, or hosted gate.

The build emitted nonfatal host py2app/pkg_resources and setuptools license
metadata deprecation warnings. Wheel installation emitted a disabled pip-cache
warning under the filesystem sandbox. They did not fail either operation;
this receipt does not claim a warning-free host toolchain.

Package verification hashes (ephemeral validation artifacts, not a release):

- Wheel: `fd8e18f031b9fd3eb8cfb369e3d8ee37819a0b8ed4e6e40dc046ff128fd563c5`.
- Sdist: `e46965e77910e2540c1d2fce0ab9acf4f1e8f67e2e9cb32e990eeb89af358957`.
- Restored safety source: `08e1fedf2cea2867f235cb736c425563974cd8360f1c50a7d2911b25c94b6f2b`.
- Final Tk source: `ae872ff10149741d4542685f3f2ab7729af8c8cff3974142c2ff88c599dc5528`.

## Local audit commit authorization

`./scripts/generate-release-manifest.sh` was executed on the current uncommitted
patch and exited **2** before building/uploading anything:

```text
ERROR: uncommitted source state (git status --porcelain not empty)
```

Cloud Build's ISO phase invokes that strict manifest command; QEMU also
requires clean provenance. On 2026-09-06 the user explicitly authorized the
local audit commit needed to resolve this order dependency. Pushing must still
wait for successful full validation. No ALLOW_DIRTY override, fabricated Git
metadata, skip flag, or publication was used.

The local audit commit and full verification completed as recorded below.
Physical devices and Secure Boot hardware are outside executed coverage; fake
disks and isolated x86_64 virtualization remain the validation boundary.


## Original successful full hosted validation

Validated code commit: `5648821e99e3d4b7e46b7877a6bad36432c7f87a`.
[Cloud Build 52b759c0-b13b-4a00-8f28-df9ecf0fcc3e](https://console.cloud.google.com/cloud-build/builds/52b759c0-b13b-4a00-8f28-df9ecf0fcc3e?project=beamo-wipe)
finished **SUCCESS** at `2026-09-06T05:36:27.814385Z`.
`./scripts/ci-cloud.sh --project beamo-wipe` exited 0.

A clean isolated clone matched every tracked file in the audited commit before
submission. Explicit substitutions were `_SKIP_ISO=false`, `_SKIP_QEMU=false`,
and `_PUBLISH_RELEASE=false`. Cloud Build's resolved source archive generation
was `1788671600515841` in the project source bucket.

| Hosted phase | Result |
| --- | --- |
| Lint | SUCCESS: compile, ShellCheck, both Ruff security selections, full Ruff, and mypy; no Ruff/type findings |
| Linux tests, Xvfb 72 DPI | SUCCESS: 1535 passed, 12 skipped, 2 generated-config tests deselected in 149.60 seconds |
| Preview | SUCCESS: web, console, helper |
| Negative safety test | SUCCESS: broken safety rejected, source restored, clean test passed |
| amd64 ISO | SUCCESS: fresh image, strict manifest, checksums, 529530880 bytes, ISO9660 PVD `CD001` |
| QEMU | SUCCESS: image/package/permission policy, crash isolation, engine boundary, BIOS wizard erase/export, UEFI Tk WHAT startup |
| Publication step | SUCCESS as disabled no-op: verified artifacts remained ephemeral; no release |

ISO SHA-256:
`a34fa08b35d7af02a1c40855fa6d9584e5966aa007bff3bab52e951f8e53f5be`.
Manifest SHA-256:
`7ccbf8ee222652d435b18fdb86744f4aaadb2a5687f36bdf6824add9386b06fe`.
The manifest log explicitly reports `strict=True`.

The BIOS guest completed the shipped wizard's erase and report-export path.
Independent checks confirmed the target's nonzero prefill became zero and the
FAT32 report passed clean-filesystem, completion, checksum, read-only mount,
and final unmount checks. The pinned engine's separately owned disposable loop
check and killed report-helper namespace isolation also passed. UEFI coverage
is startup through the shipped Tk WHAT screen, not a second erase run.

The live main trigger was inspected before landing: it uses `cloudbuild.yaml`
without a publication substitution. The validated cleanup and this documentation
receipt can be pushed normally after the final diff check; no release or
publication action is authorized or needed for that landing.


## Follow-up: picker timing failure and regression repair

After landing `7e235faf5b68d4eff00b9594e963e733605eb333`, the normal
[main build aa810173-044d-4cdc-8042-44f1c9634113](https://console.cloud.google.com/cloud-build/builds/aa810173-044d-4cdc-8042-44f1c9634113?project=beamo-wipe)
failed `test_pick_list_scrolls_selected_card_into_view`: the correct final disk
was selected, but its card was below the viewport. The Linux suite reported
1534 passed, 1 failed, 12 skipped, and 2 deselected. Its log also contained
Tcl `invalid command name` errors from callbacks on destroyed picker canvases.
The earlier full build's success did not establish reliable picker behavior.

Two defects were reproduced before editing the runtime:

- A viewport or content-height change can clamp the canvas offset. Restoration
  treated this automatic movement as manual scrolling and stopped too early.
  Deterministic viewport and content cases both failed before the fix.
- Destroying a Tk widget deletes its registered Tcl commands but does not
  cancel pending `after` events. A real headless Tcl event-loop regression
  reproduced the deleted-command error on redraw before the fix.

The fix records the geometry associated with an applied offset, so layout
clamping can settle while same-geometry direct scrolling still takes ownership.
Existing wheel/scrollbar input continues to stop restoration explicitly.
All four picker callbacks are tracked and cancelled before canvas destruction
or application teardown; the idle callback also checks the picker generation.
The existing runtime visibility assertion and click-scroll test are unchanged.

Five deterministic regressions pass, covering both geometry changes, direct
scroll ownership, redraw callback lifetime, and teardown callback lifetime.
A new real-Tk integration test verifies all four registered events disappear
when leaving the picker. Independent exact-diff review found no actionable
issue and independently ran the five headless regressions successfully.

[Linux picker repetition build 21fa5273-e8cd-4991-8f7e-214833b549e5](https://console.cloud.google.com/cloud-build/builds/21fa5273-e8cd-4991-8f7e-214833b549e5?project=beamo-wipe)
finished SUCCESS at `2026-09-06T06:01:08.722534Z`: 30 consecutive Xvfb
72-DPI runs of eight focused picker regressions passed (240 test executions).
This supplementary diagnostic used fake disks and did not replace the full gate.

Local follow-up verification: `python3 -m pytest` and `./scripts/test-all.sh`
both exited 0 with **1369 passed, 133 skipped** (28.96 and 28.88 seconds).
Compileall, prescribed ShellCheck, both Ruff security selections, full Ruff,
and mypy all passed. Web/console/helper preview checks passed. Fresh wheel
and sdist builds succeeded; all 34 tracked package files in both archives
match the corrected source byte-for-byte. A fresh wheel installation passed
version and fake-disk console smoke checks.

Follow-up package SHA-256 values:

- Wheel: `cf75d76ffa0ed90c307ce2cdf231395ed7fa93f526d6d6b8ec671263e1c31c3f`.
- Sdist: `7289c11661d2e09d96a5d5a99c7bcadfb57230968be9baac9f8ecc8ca5167dfb`.

A clean local commit is required for strict ISO provenance, as authorized
above. The complete hosted ISO/QEMU gate and the normal post-push main gate
must pass for that correction before completion; their immutable build receipts
are reported with the final delivery. No release publication is authorized.
