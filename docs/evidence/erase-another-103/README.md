# Erase another disk — #103

## Baseline and acceptance criteria

Base: main `9210aa3`; branch `feat/erase-another-disk`. The resumed baseline
pytest run reported pre-existing live-image staging failure(s). These are
outside this task; final results are recorded below. Inspection found that
live Done offers report export and shutdown; preview alone resets in place.
`baseline.png` renders the shipped native result screen with fake disks at
1024 × 740, 72 DPI. No real disk is used.

Acceptance: each new live session constructs a new wizard and runner and runs
startup discovery again. No selection, ownership, token, method choice,
countdown, request, progress, log text, evidence or export receipt is inherited.
Every unsaved result requires explicit acknowledgement, regardless of report
opt-in. Cancel returns to the original report. Export/evidence work and active
or unconfirmed erases block transition. Old evidence/log files remain intact.
Repeated sessions must rotate the recovery journal under interface ownership
and prove the prior runner has released its lock. Every outcome and report
state, changed devices and unavailable boot identity receive regression tests.

## Implementation and threat model

The application loops around its existing startup path. Each iteration creates
new discovery, Wizard and runner objects. The old interface closes only after
its model requests a new session. No preview reset code is used for live work.
The existing unsaved-report confirmation component is shared, with copy for
the selected action; Enter/Escape keeps the report open. Confirmations carry a
screen generation so cancelled/reopened dialogs reject stale clicks.

- Every unsaved result prompts, including no opt-in, failed export and failed
  evidence save. A receipt must match the current evidence revision, result and
  discovery to bypass the prompt. Busy evidence/export/diagnostic work blocks
  the action; finishing reserves the result until evidence handling completes.
- Terminal failure, interruption and cancellation may start a new session only
  after stopping. An active/unknown process or invalid recovery journal cannot.
  The same-boot runner lock is acquired before leaving the result and checked
  again before journal rotation. Interface ownership remains held. Failed
  rotation fails closed through the application's recovery error path.
- The journal gets a new session ID, creation time and preflight state. It does
  not delete or overwrite prior evidence/log artifacts. Existing unique log
  and evidence filenames separate successive operations. The result screen
  cannot return to an earlier session after continuing.
- Disk paths, identities, boot identity, mounts and inventory are rediscovered.
  The boot USB is never selectable. Missing/invalid discovery exposes no disks.
  The existing fresh pre-start validation and all authorization gates still run.
- Fresh objects isolate report receipts, evidence, timers, callbacks, logs,
  diagnostics, runner state and authorization. The old wizard also revokes its
  ownership/token/countdown authority and refuses further starts or exports.
  Keyboard layout and the chosen interface (including the screen-reader view)
  are carried forward to match the system and accessibility preference. The existing report preference journal may retain opt-in;
  this grants no export receipt or erase authorization.

## Customer workflow and interface differences

After the result, choose **Erase another disk**. Save the current report first,
or explicitly choose **Continue without saving**. Keep the Beamo USB connected.
Remove the report USB before starting the next session, then reinsert it only
when that session offers report saving. A USB present during initial discovery
is intentionally ineligible as report media under the existing exporter rules.
The next session checks disks again and asks for ownership, disk selection,
typed confirmation, method and the full five-second wait. Starting the next
session does not erase anything by itself. Shut down before disconnecting disks;
this feature does not introduce instructions for hot-swapping hardware.

Native Tk uses a fixed footer action; the accessible GTK view exposes a named,
keyboard-focusable button. Plain console accepts `ANOTHER`; curses uses `A`.
Both use typed `CONTINUE WITHOUT SAVING` when a report is unsaved. Shutdown's
existing typed phrase and safe default remain unchanged.

Browser preview simulates the report choice and clears its fake selection,
ownership, token, method and countdown. It has no real report export, engine,
recovery journal or hardware discovery, so its new-session path always asks
about the simulated unsaved report. The existing **Run again** preview control
remains available, including native demo mode. The boot helper is unaffected.

## Verification handoff

Source identity: base `9210aa32f1598936b752f4662ed926b1f3b60044`; final runtime
source SHA-256 `977367dff9618588fbd706fe42a7abc3945b30f74c942010c0b45b2fcce27d0b`.

Commands run with fake disks only:

- New model regression suite: `python3 -m pytest tests/test_erase_another.py` —
  114 passed. Includes all result categories, report receipt states, cancellation,
  busy work, unchanged/changed/absent boot media, repeated app sessions across
  interfaces, all fresh gates, keyboard/accessibility preferences, and journal
  failure/real runner-lock contention.
- Broader model/report/confirmation/startup suites — 386 passed, 2 skipped
  (display-dependent tests without a display). Subsequent affected model checks
  passed 270 tests; the required full run below covers the final source.
- Original-source check: copied the new regression onto an isolated archive of
  `9210aa3`; the first new-session case fails because the original Wizard has no
  new-session action. See `original-regression.txt`.
- `BEAMO_WIPE_NO_OPEN=1 ./preview --web` followed by
  `python3 docs/evidence/erase-another-103/verify-browser.py` — passed Chromium
  report choice, cancel, continue, and all simulated state-reset assertions.
  Additional checks at 390px and 800px passed with no horizontal overflow.
- Native Tk renders at 1024 × 740, 72 DPI — inspected result, unsaved-report
  choice and evidence-save failure. Buttons remain in the window. Existing
  two-Tab traversal from shutdown through details to Save report is preserved.
- `python3 -m compileall -q src/beamo_wipe`, repository-prescribed blocking
  Ruff security selections for source/tests, and `git diff --check` — passed.

Required local command:

```sh
dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest
```

Final local result: **2625 passed, 28 skipped, 1 known pre-existing failure** in
335.55 seconds. The only failure is
`tests/test_live_image.py::test_staged_chroot_package_matches_src`, comparing
stale gitignored live-build chroot staging with current source. Per task scope,
the staging tree was not rebuilt or committed. No helper pixel failures remain
in this final run. All erase-another, Tk/GTK, console, report, recovery and
confirmation checks pass. See `local-pytest.txt` for the complete output.

Hosted command: `./scripts/ci-cloud.sh`, project `beamo-wipe`, build
[`22ab1e2f-3be1-42ee-ad62-ae0fbebc868d`](https://console.cloud.google.com/cloud-build/builds/22ab1e2f-3be1-42ee-ad62-ae0fbebc868d?project=368895881889).
`_PUBLISH_RELEASE=false`; no release or image publication was requested.

No physical-disk erasure or hardware hot-swap testing was performed. Native
Tk/GTK, console and browser checks use fake inventory. Prior results remain as
volatile evidence files, but their UI cannot be reopened after continuing;
users must save reports first if they need them.

Initial hosted results: **2640 passed, 14 skipped** in the Python gate
(270.73 seconds). Desktop launchers, blocking lint, preview and negative tests
passed. The ISO stage then stopped with `production image refuses dirty source`:
this first submission was made before the requested feature commit. It did not
build an ISO or reach QEMU, and is not claimed as a passing overall build.

After committing and pushing `21494c36f635e68608adbc9769707636efb8cabf`,
`git status --porcelain` was empty and `./scripts/ci-cloud.sh` was submitted again.
Clean-source verification build
[`12b67b54-b4e6-4d70-aa17-caeb838cba5d`](https://console.cloud.google.com/cloud-build/builds/12b67b54-b4e6-4d70-aa17-caeb838cba5d?project=368895881889)
is pending at handoff; ISO/QEMU success is not claimed. This documentation-only
follow-up does not change the tested application source. Cloud Build manages
the disposable environment; no separate VM was created. Release publication
remains disabled for both submissions.

The final diff and staged paths were reviewed. Only the feature, its regression
tests, customer documentation and this evidence are included; no ISO or secrets
are staged. Commit/push target: `origin/feat/erase-another-disk`.
