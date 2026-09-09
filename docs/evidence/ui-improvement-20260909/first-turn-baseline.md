# UI improvement — 9 September 2026: stopped at baseline gate

## Source and outcome

Repository: BeamoINT/beamo-wipe. Requested branch created:
`codex/ui-improvement-20260909`.
Base and current HEAD: `e931d6da292e70a247792cd53050628b0f782ca2`.
`git ls-remote origin` confirmed that this remains the tip of
`codex/cross-platform-20260908`.

**Implementation is incomplete.** The unchanged baseline failed the required
full test suite. The current task explicitly says, “Stop on any failed or
unavailable required check.” Implementation, commit, push to either remote,
and PR creation stopped at that gate. No tracked application file was edited.
No new commit SHA exists. Pre-existing untracked files were left untouched.
No real disk was erased; no ISO was built, shipped, or published.

## Baseline verification

Command from the repository root:

```sh
BEAMO_WIPE_DRY_RUN=1 BEAMO_ISOLATED_X11_TEST=1 \
  dbus-run-session -- xvfb-run -a \
  -s '-screen 0 1600x1000x24 -dpi 72' ./scripts/test-all.sh -rs
```

Result: **44 failed, 1662 passed, 24 skipped; exit 1; 85.82 seconds**.
See [complete test log](baseline-tests-x11.txt).
The first sandboxed attempt could not bind the private D-Bus socket and never
started pytest; its [separate log](baseline-tests.txt) is not a test result.
The approved execution outside that socket restriction produced the full result.

The log repeatedly reports `PermissionError` for `/tmp/beamo-wipe`, followed by
`SafetyError: Refusing unsafe log directory.` The existing directory has mode
0700 and owner `nobody:nogroup`; the test session runs as UID 1000. The current
`default_log_dir()` intentionally rejects inaccessible, differently owned log
directories. Other failures show fake-runner flows remaining on LAST_CHANCE
instead of reaching WORKING or DONE. The inaccessible log directory is a
concrete baseline blocker; it has not been proved to account for every failure.
No ownership check, safety rule, fixture, or assertion was weakened.

Twelve skips require the absent manufacturing ISO. Twelve regular-file FAT32
cases skip because dosfstools/mtools prerequisites are incomplete (`mcopy` is
present; neither `mkfs.fat` nor `mkfs.vfat` is on PATH). These are skips, not passes.

`BEAMO_WIPE_NO_OPEN=1 ./preview --web` succeeded and generated
`web-preview/index.html`. `git diff --check` passed for the unchanged tracked
source. Final lint, type checking, builds, end-to-end verification, and hosted
gates were not reached. No green PR #5 result was substituted for this run.

## Initial rendered inspection

[Capture script](capture-baseline.py) renders the real Tk implementation using
`make_demo_wizard()` and a private 72-DPI Xvfb session at 1024×740:

```sh
BEAMO_WIPE_DRY_RUN=1 dbus-run-session -- xvfb-run -a \
  -s '-screen 0 1600x1000x24 -dpi 72' \
  python3 docs/evidence/ui-improvement-20260909/capture-baseline.py
```

Eighteen images are under `baseline/`. They are presentation-only fixtures:
the script supplies screen states and stops the tick timer; it does not execute
an erase, wait for completion, or prove recovery. In particular the picker
capture has a deliberately selected fixture disk, and the DONE capture does
not represent a completed operation. Capturing a screen is not equivalent to
reviewing or validating its flow.

The [picker](baseline/tk-pick.png), [confirmation](baseline/tk-confirm.png),
and [final review](baseline/tk-last_chance.png) were visually inspected. They
show the existing numbered steps, wrapping identity, serial, destructive copy,
confirmation match feedback, and safe Back focus with disabled Erase now.
The selected SSD's two notices leave roughly two complete disk rows visible
in the picker at 1024×740. This is an observation for subsequent design review,
not a demonstrated defect or authorization to hide either notice.

The complete screen/state/size review, GTK visual review, keyboard walkthrough,
and success/failure/recovery verification remain incomplete after the failed
gate. The source and existing tests were inspected for Tk, GTK, shared copy,
result mapping, ownership, confirmation, countdown, loading, report workflows,
keyboard handling, and low-resolution behavior; no new UX behavior is claimed.

## Acceptance criteria for resumption

1. Establish a passing full baseline with actual Tk, GTK, AT-SPI/Orca, keyboard,
   safety, and regular-file FAT32 coverage; explicitly account for artifact skips.
2. Review each current Screen value, cancellation dialog, result code, report
   state, and diagnostic/recovery state using fake fixtures. Add no wizard steps.
3. At Tk's 1024×740 minimum and 1280×820 default, and at 1366×768 and 1920×1080,
   require no clipped labels, overlapping controls, or unreachable actions.
   Inspect documented degraded sizes 800×600 and 1024×600 without claiming them
   as a new supported Tk minimum. Preserve GTK's actual 800×600 work-area and
   footer guarantees and verify scaling separately.
4. Keep complete model, capacity, serial, target identity, boot exclusions,
   warnings, method operations, verification state, failures, and recovery
   information accessible. Long identity fixtures must wrap without clipping.
5. Preserve logical keyboard traversal, visible focus, safe destructive-action
   defaults, held-key protection, ownership/token gates, the full five-second
   delay, and explicit erase activation. Refresh must clear prior authorization.
6. Retain existing text contrast of at least 4.5:1 and control/focus contrast of
   at least 3:1. Use native/shared components and the existing offline assets.
7. Add behavior-based regressions for demonstrated changes; inspect before/after
   pixels and final diff. Run applicable prescribed checks and record failures
   and unavailable checks honestly before any commit/push.
8. Pin nwipe 0.42 and preserve execution/discovery contracts. No real-disk
   operations, main push/merge, release, or ISO shipment.

## Next action

Restore an isolated test environment with a safe, test-user-owned
`/tmp/beamo-wipe` while preserving existing session data, and install the
missing regular-file FAT32 test prerequisites. Rerun the complete baseline and
triage any remaining failures before resuming UI implementation. Do not change
application safety checks to accommodate this environment.
