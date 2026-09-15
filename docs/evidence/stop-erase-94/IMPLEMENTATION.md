# Stop erase #94 — implementation handoff

Base: main 9210aa32f1598936b752f4662ed926b1f3b60044.
Branch: feat/stop-erase-unmistakable. Date: 2026-09-14.

The original baseline README, pytest output and screenshots are preserved alongside this
file (captured text logs have trailing whitespace normalized only). The feature commit containing this handoff identifies the delivered source;
source-sha256.txt records changed source, tests and active documentation independently.

## Behavior

- Stop erase, Escape, and native window close request confirmation. Nothing is signalled
  until the owner chooses Yes, stop erasing. Keep erasing dismisses it.
- The warning says stopping cannot restore files already erased. Stopped and interrupted
  results, report summaries and the support runbook use the same warning.
- Confirmation remains a view of WORKING. Engine polling continues; completion clears
  consent. An identity token rejects stale consent, including a dismissed confirmation.
  Existing stop claims still serialize duplicate stops and preserve the actual engine
  result when completion races stopping.
- Native controls reuse existing focus, keyboard-repeat and stale-widget guards. Keep
  erasing occupies the initiating button's position; confirmation is a separate control.
  Tk focuses Keep erasing; GTK focuses the spoken warning.
- Stopping erase means exit/cleanup is pending. Stopped by you requires confirmed
  interruption. Stop could not be confirmed leaves WORKING active, with a prominent
  warning and retry available. Tk moves the warning above disk details and progress.
  Failure to launch the stopping worker uses the same unconfirmed wording.
- Plain console: CANCEL + Enter opens confirmation; STOP + Enter confirms; KEEP + Enter
  dismisses. Repeated CANCEL cannot confirm. Ctrl-C opens confirmation where available.
  Curses uses Esc to request, S to confirm, and K/Esc/Enter to keep erasing.
- Browser preview offers stop, keep-erasing, stopping and stopped simulations, with an
  explicitly simulated stop-unconfirmed deep link. Completion continues while reading
  confirmation. Preview labels remain visible and no engine runs.
- No disk-selection, boot-exclusion, nwipe arguments, evidence schema or engine changes.

## Intentional differences and limits

Terminal EOF/unusable input and interface failure still request system interruption:
an unavailable interface cannot ask for consent. Abrupt power/process loss retains the
existing conservative recovery/evidence paths, never invented success. Native demo results
retain explicit Preview finished / nothing-erased wording; the browser additionally
provides labeled static stop outcome examples.

No ISO, Cloud Build, QEMU, physical hardware or real-disk erase was run. This is a UI and
controller-consent change, not an ISO build or release. No image was released or published.
Real device signal/cleanup timing and physical power loss were not exercised; fake runner,
process and recovery tests provide local coverage.

## Verification

Original baseline: 2507 passed, 28 skipped, 2 failed. The user explicitly authorized
continuing past the pre-existing helper Chrome render timeout and stale gitignored
chroot source copy. Both are deselected in the final command, with no broad exclusions.

Failing-before proof: archive 9210aa3's src, tests and pyproject.toml to /tmp/stop-before;
copy only tests/test_stop_confirmation.py from the feature checkout; run
python3 -m pytest tests/test_stop_confirmation.py there.
All 8 new tests fail on the original problem (regressions-before.txt).
On the implementation the same 8 pass. Coverage includes consent, dismissal, duplicate
requests, stale consent, completion while confirming, failed stop, repeated curses keys,
shared interruption wording, plain-console polling and Ctrl-C.

Native regressions also exercise visible confirmation, safe focus, minimum-window
geometry, stale widget callbacks, window close, and confirmed asynchronous stopping.
Existing race, process-kill/cleanup, no-result, late completion, stale-progress, evidence,
recovery and disk-safety tests remain in the full gate. Label assertions and two report
goldens were updated to the new customer wording.

The initial implementation-wide run found outdated label/snapshot/doc assertions and one
AT-SPI bus failure during overlapping GUI checks; implementation-checks.txt preserves it.
The focused follow-up recorded 72 passed (focused-checks.txt). An early final run was
restarted after diff review found a remaining old-label selector; it is not gate evidence.

Final required gate:

    dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest \
      --deselect tests/test_helper_boot_guidance.py::test_helper_renders_both_windows_paths_on_small_and_desktop_displays \
      --deselect tests/test_live_image.py::test_staged_chroot_package_matches_src

Final result: **2517 passed, 28 skipped, 2 deselected in 340.45s** (exit 0),
recorded in final-pytest.txt. No in-scope failures remain. Final diff/whitespace
review and source SHA-256 verification passed.

## Render and interaction evidence

    BEAMO_WIPE_NO_OPEN=1 ./preview --web
    python3 docs/evidence/stop-erase-94/verify-browser.py
    PYTHONPATH=src:tests dbus-run-session -- xvfb-run -a \
      -s "-screen 0 1600x1000x24 -dpi 72" \
      python3 docs/evidence/stop-erase-94/render-native.py

Browser checks require installed Chrome and websocket-client. They serve only the local
preview on loopback, exercise the real page, and capture full-page screenshots at 1024px
width. Browser stop/keep/confirmation/stopping/stopped and completion-during-confirmation
assertions pass (browser-checks.txt). Early screenshot attempts accidentally selected
Chrome's background extension target; selecting the page target resolved the issue.
No screenshot timeout is treated as a successful visual check.

after-tk-* and after-gtk-* show confirmation, stopping, stopped and unconfirmed at
1024x740. after-browser-* show working and all four stop states. Stopped native renders
use validated synthetic cancelled evidence; other native states use fake disks without
launching a runner. Screenshots were visually inspected for warning/action visibility
and distinct outcomes. Native geometry tests cover additional sizes.

Full diff and whitespace checks precede commit. No in-scope failures are accepted.
Only explicit source, test, documentation and evidence paths are staged.
