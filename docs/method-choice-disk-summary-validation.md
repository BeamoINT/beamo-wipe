# Method choice disk summary — validated

Backlog #74; branch `feat/method-choice-disk-summary`.
Final implementation SHA: `d09de0a219162bff80da6f72c43c0841e6b24fbb`.
This validation record is committed separately after the implementation so it can
name the exact tested source commit.

## Final continuation — 2026-09-14

All remaining blockers cleared. The draft selected-disk summary is retained:
model/name, capacity, serial/ID and connection, with system path under Show more.
Advanced now uses the fixed footer's wrapping utility row, keeping it within
the initial viewport alongside fixed Back/Continue. The body still scrolls for
method cards and long identities. Target binding remains display-only.
No adaptive assertion was weakened. The source-inspection regression test now
checks the Advanced navigation callback in its new footer location.

Commands and results (source stationary during each full gate):

- `dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest tests/test_adaptive_layout.py tests/test_tk_runtime.py -k 'walkable_screen_keeps_actions or method_keeps_selected_disk_identity or method_identity_wraps'`:
  **12 passed, 227 deselected**, including enlarged 800×600 cases.
- Refreshed the entire ignored staged Python package using
  `git ls-files -- src/beamo_wipe` and `cp` into
  `packaging/live/config/includes.chroot/usr/lib/python3/dist-packages/beamo_wipe`,
  following the tracked-source copy mechanism in `scripts/build-iso.sh`.
  `python3 -m pytest tests/test_live_image.py::test_staged_chroot_package_matches_src`:
  **1 passed**.
- First full gate: **1 failed, 2515 passed, 28 skipped**; only the source-inspection
  test still expected Advanced's callback inside `_method`. Updated its expected
  location to `_footer_shell`, retaining the navigation-wrapper assertion.
- Final `dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" ./scripts/test-all.sh`:
  **2516 passed, 28 skipped in 357.59 seconds**. No flaky-test exception needed.
- `git diff --check`: passed.

Evidence: `docs/evidence/method-choice-disk-summary/cleared-targeted.txt`,
`cleared-full-gate.txt`, and visually inspected `cleared-tk.png`.
Only fake disks/dry-run tests were used. No real nwipe, Docker/ISO build, Cloud
Build, QEMU, ISO release, or generated chroot files are included in the commits.
Git had no configured author; commits use the existing repository-history
identity, BeamoINT <beamo@beamosupport.com>, through per-command configuration.

## Historical draft record (superseded by the results above)

# Method choice disk summary — incomplete, blocked

Source: `9210aa32f1598936b752f4662ed926b1f3b60044` (`main` and
`origin/main` at start), branch `feat/method-choice-disk-summary`.
Backlog: #74. No feature branches merged. Work remains uncommitted and unpushed.

## Latest continuation — 2026-09-14

Still blocked; no commit or push. HEAD remains
`9210aa32f1598936b752f4662ed926b1f3b60044` on
`feat/method-choice-disk-summary`. The original draft is preserved.

Fixed the enlarged-text footer overflow: utility buttons wrap into rows based
on their requested widths, and short-window key hints wrap above the navigation
row. Selected-disk identity remains in the existing scrolling method body.
Neither clipping nor off-window assertions were weakened. Inspected the
800×600 / 150% fake-disk screenshot (`final-tk-800-enlarged.png`).

Final targeted command:
`dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest tests/test_tk_runtime.py tests/test_console_parity.py -k 'method_keeps_selected_disk_identity or method_identity_wraps or method or identity'`
— **54 passed, 152 deselected**, including both previously failing enlarged
identity cases. Evidence: `final-targeted.txt`.

Used the existing tracked-file copy operation and staging destination from
`scripts/build-iso.sh` (lines 65–81), without invoking its Docker/ISO build, to
refresh only `gallery.py`, `ui/console_wizard.py`, and `ui/tk_wizard.py` in the
ignored chroot package. No packaging script, generated binary, or ISO changed.

After source edits and staging stopped, ran:
`dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" ./scripts/test-all.sh`
— **4 failed, 2512 passed, 28 skipped** in 355.24 seconds.
Evidence: `final-local-gate.txt`. Remaining blockers:

- `tests/test_adaptive_layout.py::test_every_walkable_screen_keeps_actions_and_copy[size0]`,
  `[size1]`, and `[size2]`: the method body's **Advanced (technicians)** button
  lies below the initial viewport at 800×600, 1024×600, and 1024×740. The
  assertion requires every mapped button to fit without scrolling, including
  buttons inside the scrolling canvas. Its measured y/height pairs are
  675/31, 660/31, and 721/33 respectively. This is distinct from the fixed
  footer overflow, which now passes. No assertion was changed. A read-only
  fake-disk reproduction confirmed the button and geometry; see
  `final-action-blockers.txt`.
- `tests/test_live_image.py::test_staged_chroot_package_matches_src`: first
  remaining mismatch is unchanged `wizard.py` (byte 462). A complete comparison
  also finds unchanged `copy.py`, `inventory.py`, and `ui/accessible_wizard.py`
  stale. Feature files now match. These unrelated staging copies were left
  alone under the instruction to refresh only feature changes.

`git diff --check` passes. Required gates are **not all cleared**. Per the stop
condition, leave the complete draft uncommitted and unpushed. No real disks,
real nwipe, Cloud Build, QEMU, ISO build, or release was used in this continuation.
The following sections retain the prior run's historical results; the latest
results above supersede its unresolved enlarged-footer and gallery-staging notes.

## Baseline and acceptance

Read AGENTS.md and all three indexed memory notes, followed method selection
through Wizard, Tk, gallery, console, accessible GTK, shared identity and method
specifications. Rendered the original Tk method screen at 1024×740 and browser
screen at 1024px. Neither showed the selected disk. Images are in
`docs/evidence/method-choice-disk-summary/`.

Before implementation, the new
`test_method_keeps_selected_disk_identity` failed on the original renderer:
`Samsung SSD 970 EVO` was absent from method-screen labels.

Acceptance: retain model/name, capacity, serial or existing explicit missing-ID
fallback, and connection; expose the system path as technical detail; retain
full long values and missing-identity warnings; preserve the same selected Disk
through each method and Continue; keep controls usable at 1280×820, 1024×740,
and 800×600, including enlarged text. No selection or engine changes.

## Draft implementation and intentional differences

Tk and the browser reuse their existing selected-disk summary and keyboard
accessible Show more disclosure. The system path keeps its existing “not a
stable identity” wording. The card has no selection action. Tk method selection
now uses the existing scrolling body, leaving navigation in the fixed footer;
smaller screens may require scrolling to see all method cards.

Both console modes print the shared identity before the methods. They show the
system path directly because they have no Show more disclosure. Curses retains
its existing paging controls. Accessible GTK already calls its shared identity
renderer during method selection; it remains unchanged and has no new path
disclosure. Native screen-reader behavior was not verified.

`methods.py`, discovery, target selection, confirmation, and nwipe invocation
are unchanged. No real disk was used, no nwipe binary invoked, and no ISO was
built, released, or published.

## Verification and blockers

Commands run from the repository root unless noted:

- Baseline regression: `dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest tests/test_tk_runtime.py -k method_keeps_selected_disk_identity -x`:
  **1 failed as expected**, missing selected model, before implementation.
- Same new continuity tests after implementation: **3 passed**. All three
  methods preserve the selected object, and Continue retains it.
- `dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest tests/test_tk_runtime.py tests/test_console_parity.py -k 'method or identity_wraps'`:
  **28 passed, 2 failed**. Both failures are the 150% font-enlargement cases at
  800×600: fixed footer content extends beyond the window. Full long/missing
  identity strings are present; the off-window acceptance check fails.
  This remains unresolved. See `targeted.txt` in the evidence directory.
- `BEAMO_WIPE_NO_OPEN=1 ./preview --web`, then Playwright against the generated
  file: identity, path disclosure, all three method choices, and no horizontal
  overflow passed at 1024px and 390px, also with browser zoom at 150%.
  Browser and Tk screenshots were inspected. Reproduction scripts are saved
  with the evidence; they use only the fake preview.
- `dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" ./scripts/test-all.sh`:
  **7 failed, 2502 passed, 28 skipped**. This run began on main but source edits
  happened while it was running. Four `inspect.getsource` failures resulted
  from old imported line offsets against edited files; this is not a valid
  clean baseline or final gate. The other failures concerned Chrome rendering,
  stale generated chroot sources, and a busy-transition GUI test.
- Rechecked all seven reported failures with the edited sources stationary:
  **6 passed, 1 failed**. The remaining failure is
  `test_staged_chroot_package_matches_src`: the generated chroot `gallery.py`
  is stale. Comparing it with `git show 9210aa3:src/beamo_wipe/gallery.py` also
  differs at byte 4356, so the existing generated copy was stale before this
  feature. It has not been refreshed or committed.
- Rechecked the same seven failures on a separate detached worktree of
  `9210aa3`, with no edits: **6 passed, 1 failed**. Chrome's helper screenshot
  test timed out. The clean worktree has no generated chroot copy; that test
  returns without comparing files there. See `clean-baseline-recheck.txt`.
- `git diff --check`: passed.

Per the request to stop on failed required gates, no commit or push was made.
There is no passing final full-suite result. Required follow-up is to resolve
the enlarged-text layout failure, refresh generated staging appropriately,
and rerun the stationary full gate before committing and pushing. Long/missing
browser identities, explicit similar-disk switching, live GTK/screen-reader
verification, macOS, and the shipped ISO environment remain unverified. No
Cloud Build or QEMU gate was attempted after the local failure.
