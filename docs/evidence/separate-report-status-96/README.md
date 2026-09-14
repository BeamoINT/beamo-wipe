# Backlog #96 — separate erase and report status

## Source and baseline

- Base: `9210aa32f1598936b752f4662ed926b1f3b60044`, current `origin/main` after fetch and fast-forward pull.
- Branch: `feat/separate-erase-report-status`; no feature branches merged.
- Read `AGENTS.md` and `.ai/memory/` constraints before editing. Inspected outcome,
  evidence persistence/retry, export receipt validation, Tk, GTK, console and gallery call paths.
- Fake-disk baseline: `case_evidence(CASES[0])`, report status `error`, native Tk
  at 1024×740 on Xvfb at 72 DPI. `baseline-tk.png` shows a global “Finished”
  heading and a report warning below disk/check details, partly outside the viewport.
- Browser baseline: `BEAMO_WIPE_NO_OPEN=1 ./preview --web`, Chrome headless,
  `#s=done&disk=0`. One completion heading, no named report area.
- Initial full pytest run overlapped source edits and is **invalid** as a baseline:
  5 failures (source-inspection line offsets, changed documentation, stale generated
  chroot package), 2504 passes, 28 skips. No commit/push was made on that result.
- Reproducible baseline rerun uses an isolated detached worktree at the base commit,
  with the existing generated live-build `config/bootstrap` and `config/binary`
  copied into it. These files are ignored build configuration, not source changes.

## Acceptance criteria established before implementation

1. Every completion interface names erase status and report status separately.
2. Export state cannot change the canonical erase message, success flag, color or icon.
3. Report problems use report-specific language and warning styling; a saved report
   has neutral styling and never implies erase success.
4. Every engine outcome is crossed with idle/saving/saved/error report states,
   evidence-save/check failure, and failed export receipts followed by successful retry.
5. Receipt content remains consistent with erase evidence; failed copy/check/unmount
   or checksum validation cannot announce a saved report or safe removal.
6. Native minimum-window layout, GTK heading semantics/focus, browser named sections,
   console output and existing retry/keyboard behavior remain covered.

## Implementation

`ReportView` supplies shared report headlines and tone from its existing immutable
snapshot. Shared copy names the areas and explains independence. Tk shows a compact
report panel above disk details; its erase badge remains canonical. GTK exposes ATK
headings, focusable report text and amber report warnings while preserving arrival
focus on the canonical erase announcement. Console uses explicit text headings;
HTML uses named sections with heading elements. Previews explicitly say no report
was saved and retain preview-only actions.

Evidence preparation failures still conservatively withhold a confirmed erase result.
Only their mixed erase/report headline wording changed. Existing receipt checks,
export claims, retries, shutdown guards and evidence bytes are unchanged. Successful
export receipt copy explicitly says it does not confirm erase success. No disk
selection, authorization, nwipe flags or execution changes.

## Verification

- Regression against original source:
  `python3 -m pytest -o pythonpath=/tmp/beamo-96/original/src tests/test_separate_report_status.py -x`
  fails because the rendered console lacks “Erase status” / “Report status”.
- Initial new model/export regression: 153 passed; subsequently expanded to include
  every evidence failure/saving cross-product and browser section semantics.
- New Tk/GTK runtime cross-products: 88 passed (44 per interface); final suite also
  includes existing accessibility, keyboard, receipt and evidence retry coverage.
- Browser render: Chrome headless DOM confirms both `aria-labelledby` sections
  resolve to the corresponding heading IDs. Inspected `after-web.png`.
- Native renders: inspected `after-tk.png` (verified erase, failed report) and
  `failed-erase-saved-report-tk.png` (failed read-back verification, saved report).
  Both statuses are readable at 1024×740. Long details remain scrollable; actions
  remain fixed. GTK was also rendered and its heading/keyboard semantics exercised.
- Final gate results are recorded below after completion.

## Scope, risks and skipped environments

All tests use fake disks, mocked exporters and ordinary temporary files. No real-disk
nwipe, USB write, ISO build or release. Cloud Build/ISO/QEMU gates are outside this
presentation-only change; booted ISO, physical screen readers, macOS and Windows
were not exercised. GTK accessibility is verified through runtime ATK semantics and
existing AT-SPI tests rather than human speech review. Browser remains a preview,
not a report exporter. Long receipts and disk details require scrolling on small
screens; report status does not depend on color alone.

## Final results and blocked handoff

- Isolated baseline command:
  `dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest`
  at the base commit: **2508 passed, 28 skipped, 1 failed**, 379.67 seconds.
- Final checkout command:
  `dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" ./scripts/test-all.sh`
  (`test-all.sh` runs pytest with fake-disk dry-run defaults):
  **2838 passed, 28 skipped, 1 failed**, 390.87 seconds.
- Both failures are
  `tests/test_helper_boot_guidance.py::test_helper_renders_both_windows_paths_on_small_and_desktop_displays`.
  Chrome timed out after 40 seconds with inotify “Too many open files” messages.
  This test and the helper page are unchanged by this branch.
- Retried that exact test alone using the same dbus/Xvfb/test-all command after
  both full suites stopped: **1 failed**, 1.29 seconds; Chrome exited `-11`
  (SIGSEGV). The required local gate remains failed. See the saved test logs.
- All **330 added cases passed** in the final full run. No source edits overlapped
  that run. The existing ignored chroot Python staging copy was refreshed from
  tracked `src/beamo_wipe` files before the final run, using the build script's
  copy policy; no image was built.
- Repository security Ruff rule sets for `src/beamo_wipe` and `tests`: passed.
  Full diff reread and `git diff --check`: passed.
- Initially stopped without commit because the helper Chrome gate was red.
  See coordinator clearance below after the environmental inotify limit was raised.


## Coordinator gate clearance (2026-09-14 CT)

The helper Chrome failure was environmental (`inotify_init` / Too many open files)
and reproduced on isolated baseline as well as this branch. After raising
`fs.inotify.max_user_instances` to 512 on the shared box:

- `tests/test_helper_boot_guidance.py::test_helper_renders_both_windows_paths_on_small_and_desktop_displays` **passed** (1.47s).
- Key suites: `test_separate_report_status.py`, `test_screens_report_actions.py`,
  `test_tk_runtime.py`, `test_accessible_runtime.py` — **all passed** (KEY_EXIT:0).

Commit and push of `feat/separate-erase-report-status` proceeded after these checks.
No ISO release.
