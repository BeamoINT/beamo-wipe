# #69 — implementation and verification handoff

Date: 2026-09-14. Status: **implemented; local in-scope gates passed**.
Branch: `feat/im-not-sure-which-disk`.
Base: `9210aa32f1598936b752f4662ed926b1f3b60044` on main. No feature branches merged.
The earlier sandbox block below is historical and has been resolved.

## Acceptance decisions and implementation

The eight measurable checks in the original handoff below remain the acceptance
criteria. Ownership is retained only if previously acknowledged; opening help
never grants ownership. The guarded `Wizard.open_disk_help` transition clears
selected target, token, countdown, operation authorization and stale error under
the existing lock. It is accepted only on PICK, and ignored after shutdown is
requested. Back returns to PICK without choosing even the first or only disk.
Keyboard-layout help returns to the identification page; refreshing disks uses
the existing full reset, including ownership. Discovery, inventory eligibility,
identity rules, nwipe flags and the engine are unchanged.

Tk, GTK, browser preview and both console modes use shared copy. The guidance
covers external targets and disks from another computer, trusted labels/records,
similar sizes, missing/duplicate identity, unstable device paths, and stopping
before changing connections. The stop action uses existing report-loss protection.
README and `docs/screen-reader.md` document the route and external-target wording.

Intentional interface differences: GTK uses its accessible text reader and
announces the heading on arrival; Tk/browser focus the reader. GTK and plain
console already show identity details without a Show more disclosure. Curses
uses U / Esc / S and paged reading; plain console uses U / BACK / STOP and terminal
scrollback. Tk preview closes its window; browser preview offers a close-tab
message. Neither powers off the development computer. No confirmation is
advanced by Enter while reading help.

## Reproducible baseline

Before source edits, rendered the shipped Tk picker at 1024x740 and GTK picker;
also inspected the original generated browser picker. All lacked the explicit
uncertainty action. Screenshots from these inspections are in `/tmp/issue69-before-*`.
The original five new state regressions failed with missing `open_disk_help`.

The initial full baseline command used the exact required D-Bus/Xvfb form. It
finished with 2502 passed, 28 skipped and 7 failures. Six source-inspection
failures are invalid baseline results: edits made while that run was active
changed line offsets used by `inspect.getsource`. The seventh is the documented
staged-chroot package mismatch. To recover a stable baseline, extracted
`git archive 9210aa3` into `/tmp/beamo-69-baseline` and ran:

```sh
dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest tests/test_preview.py tests/test_wizard_flow.py tests/test_identity.py tests/test_excluded_inventory.py tests/test_console_pick.py tests/test_console_parity.py
```

Result: **111 passed in 14.31s**. This also resolves all six invalid baseline
source-inspection failures against unchanged source.

## Verification results

Logs live under `/tmp/issue69-*.log`.

- State/console/identity/refresh/browser regressions: **13 passed in 2.49s**.
- Browser rerun after hardening help deep links: **2 passed in 2.38s**.
- Actual Orca speech plus state/browser checks: **14 passed** (exit 0).
- `git diff --check`: passed.
- Supplemental hosted submission:
  `SUBSTITUTIONS=_SKIP_QEMU=true ./scripts/ci-cloud.sh --skip-iso`
  failed before submission because Google auth tokens require interactive
  reauthentication. No hosted build ran. ISO and QEMU phases were explicitly
  excluded for this UI-only task; no release/publish was requested.

The exact full command was run again on the implementation:

```sh
dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest
```

It reported **2504 passed, 28 skipped, 27 failed in 341.47s**. Two were approved
exclusions: stale staged package and the helper Chrome pixel check (this run
crashed Chrome rather than timing out). The other 25 shared one in-scope test
fixture issue: the diagnostic-marker fake Tk object did not stub `_disk_help`.
Updated that fixture; **all 28 marker tests passed in 0.59s**. No product
behavior was weakened to satisfy the tests. Helper/START-HERE equality passed
in this full run.

Final applicable-suite command:

```sh
dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest tests/test_unsure_disk.py tests/test_unsure_disk_browser.py tests/test_tk_runtime.py tests/test_accessible_runtime.py tests/test_console_pick.py tests/test_console_parity.py tests/test_identity.py tests/test_excluded_inventory.py tests/test_wizard_flow.py tests/test_preview.py tests/test_ui_system.py
```

Result: **395 passed, 2 skipped in 180.53s**. The skipped checks require an
explicitly isolated X server. Reran both with `BEAMO_ISOLATED_X11_TEST=1` and
the same D-Bus/Xvfb prefix:
`tests/test_tk_runtime.py::test_fullscreen_kiosk_has_fixed_display_geometry_without_window_manager`
and `tests/test_tk_runtime.py::test_isolated_x11_physical_return_release_after_start`:
**2 passed in 4.24s**. Real Tk/GTK tests and Orca speech checks ran. Browser/source-preview rerun after guarding stale card
callbacks: **37 passed in 3.26s**. Help deep links also clear supplied disk,
token and ready-countdown parameters.

Final complete local gate, with only the user-approved exclusions:

```sh
dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest --deselect=tests/test_live_image.py::test_staged_chroot_package_matches_src --deselect=tests/test_helper_boot_guidance.py::test_helper_renders_both_windows_paths_on_small_and_desktop_displays --deselect=tests/test_helper_boot_guidance.py::test_helper_and_iso_start_here_are_identical
```

Result: **2528 passed, 28 skipped, 3 deselected in 357.57s**, exit 0.
No source changes were made during this final gate. All in-scope failures are
resolved. The 28 default environment-dependent skips remain explicitly reported;
this does not claim ISO/QEMU, physical speakers, braille hardware or hardware
boot verification. The two isolated Tk checks also passed separately as above.

Final review: re-read the task and full staged diff, checked all adapter call
paths and help return/utility paths, verified screenshots, and ran
`git diff --cached --check`. Source identity is the commit containing this
handoff on the feature branch, based on the full main SHA above. Intended
commit: `safety: add an unsure-disk identification route (#69)`.
No ISO was built or published. Cloud Build remains unverified due to auth;
this is a UI-only change with no ISO/x86 packaging changes.
New runtime checks cover Tk at 1024x740 and 1280x820, GTK at 800x600 and 1280x820,
and Chrome at 1024x740 and 1280x820. Regression coverage includes revocation,
stale callbacks during checking/working, return state, similar/missing identity,
keyboard/refresh utility returns, report-protected shutdown and remaining
confirmation gates. Orca speech checks exercise the help action, heading and
reader in addition to existing result announcements.

Reviewed renders: [Tk picker](issue-69/tk-picker.png),
[Tk help](issue-69/tk-help.png), [GTK help](issue-69/gtk-help.png),
[browser help](issue-69/browser-help.png).

Known task exclusions: staged chroot/source mismatch; helper Chrome pixel
timeout; helper/START-HERE drift. Only failures actually reproduced are included
in the final results. No real disks, real nwipe invocation, ISO publication,
release, merge or unmerged feature dependency is involved. Hardware boot and
physical-disk identification are outside this fake-disk UI verification.

---

# #69 — unsure disk route: baseline and blocked handoff

Date: 2026-09-14. Status: **not implemented; not ready to merge**.

## Source and scope

- Checkout: `/home/box/beamo-wipe`, clean at start, branch `main`.
- HEAD: `9210aa32f1598936b752f4662ed926b1f3b60044` (the requested base).
- Requested branch: `feat/im-not-sure-which-disk`.
- No feature branches merged. No wipe engine invoked, no disk writes, no ISO
  build/release/publish. Inspected source and ran existing tests only.
- Read `AGENTS.md`, `.ai/memory/MEMORY.md`, product constraints and visual
  verification notes.

## Blocking environment evidence

Branch creation attempted with `git switch -c feat/im-not-sure-which-disk`:

```text
fatal: cannot lock ref 'refs/heads/feat/im-not-sure-which-disk': Unable to create
'/home/box/beamo-wipe/.git/refs/heads/feat/im-not-sure-which-disk.lock': Read-only file system
```

The exact required baseline command was attempted:

```bash
dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest
```

It exited 127 before pytest started: D-Bus could not bind its `/tmp/dbus-*`
socket (`Operation not permitted`); `dbus-run-session` reported EOF reading
the bus address. This is an environment block, not a passing test gate.

Pre-edit rendered inspection was also attempted and could not be completed:

- A Tk connection probe with `DISPLAY=:99` failed with
  `TclError: couldn't connect to display ":99"`.
- Headless Chrome targeting the existing preview picker failed initially to
  create its profile. Retrying with `--user-data-dir=/tmp/beamo-69-chrome`
  failed with Crashpad `setsockopt: Operation not permitted`, exit 133.
- No screenshot was obtained or visually inspected. Native layout,
  keyboard focus and AT-SPI announcements remain unverified.

No product source edits were made because the requested branch, pre-edit
render inspection and required GUI baseline cannot be established here.
This handoff is the only intended checkout change. No commit or push was
possible with the read-only Git metadata. Resume in an environment that
permits Git writes and D-Bus/Xvfb/Chrome sockets.

## Baseline findings from source

- `ui/tk_wizard.py::_pick` displays the shared picker subtitle, same-size and
  ambiguous-identity warnings, selectable cards, excluded inventory, Back
  and Continue. There is no explicit unsure-disk action.
- `inventory.py` explains excluded devices; it is display-only and must not
  become a second eligibility implementation.
- `identity.py` already presents model, capacity, connection, serial/hardware
  ID, missing identity and duplicate warnings. Reuse these distinctions.
- `wizard.py::select_disk` and `continue_pick` guard the picker state and
  boot exclusion. `continue_pick` rejects unconfirmable identity.
  `_clear_authorization_locked` clears the token, countdown and operation
  authorization, but does not clear `selected` or `owner_ok`.
- `wizard.py::back` maps screens explicitly. A new help screen needs a safe
  explicit return path. Check keyboard/report-help/refresh utility return
  paths as well as the ordinary Back action.
- The shipped screen-reader interface is GTK in `ui/accessible_wizard.py`;
  Tk alone cannot satisfy screen-reader acceptance. GTK supplies a reader
  component and explicitly enumerates screens with a Back action.
- Both `_plain_loop` and the curses rendering/key handler in
  `ui/console_wizard.py` need equivalent entry, read, back and stop actions.
- `gallery.py` has independent JavaScript state. Mirror reset semantics,
  focus and safe exit there; this preview never performs a wipe.
- The current picker subtitle already says “the disk you intend to erase”.
  Preserve that inclusive wording and the existing identity warnings.

## Proposed measurable acceptance checks (before implementation)

1. An explicit “I'm not sure which disk” action is visible on the picker
   without selecting a disk, in Tk, GTK and browser preview. Both console
   modes offer a named equivalent. Keyboard users can activate it.
2. Opening help clears the selected target, typed confirmation, countdown
   and operation authorization. It never selects the first/only disk and
   never calls the runner. Guard the transition so a stale callback cannot
   interrupt checking or erasure.
3. Back/Escape returns to the picker with no disk selected and Continue
   disabled. Repeated Enter, arrow keys while reading, stale callbacks and
   calls to continue/erase from help cannot advance authorization.
4. Subsequent erasure still requires the existing explicit ownership
   checkbox, a deliberately selected confirmable disk, the exact token and
   the full five-second delay. Help must not grant ownership. Decide and
   document whether an already-checked ownership acknowledgement is retained;
   if cleared, return through the ownership step so it can be checked again.
5. Guidance explicitly covers an external disk or a disk from another
   computer. Compare name/model, capacity and serial/hardware ID against a
   trusted label or record. Explain that size alone and `/dev/...` names do
   not establish identity. Do not imply that USB means the boot stick or that
   the desired target is necessarily an internal system disk.
6. Similar disks and missing/duplicate identity say not to guess. Offer
   shutdown before checking connections; retain the Beamo boot USB and never
   suggest bypassing protections or disconnecting live hardware.
7. Help contains an explicit stop/shutdown action using the existing shutdown
   flow (including report-loss protection). Preview uses its existing safe
   close/simulation behavior, documented as an intentional difference.
8. Verify readable, scrollable help at the repository's supported small and
   desktop sizes; visible focus, Tab/Shift-Tab, Return/Space, Escape and page
   scrolling. Verify GTK accessible names/reading order and browser semantic
   buttons/labelled reading region. Do not substitute source-string assertions
   for runtime keyboard and accessibility verification.

Use one shared copy source and a guarded Wizard help transition, adapting the
existing help readers and controls. Avoid modifying discovery or nwipe flags.
Add behavioral regression coverage that fails against this base before
implementation, including preselected target, same-size fake disks, absent
identity, blocked boot discovery, return state and the full authorization
sequence. Preserve existing inventory, scrolling and keyboard shortcuts.

## Checks and resume procedure

- `python3 -m pytest tests/test_safety.py tests/test_storage_limits.py -q`:
  **28 passed**, exit 0. This limited baseline does not replace the required
  D-Bus/Xvfb gate.
- `python3 -m pytest tests/test_wizard_flow.py tests/test_identity.py tests/test_excluded_inventory.py tests/test_console_pick.py tests/test_console_parity.py -q`:
  **94 passed**, exit 0, using existing fake-disk tests without a GUI display.
- The same command without `tests/test_wizard_flow.py` was inadvertently
  repeated during final status collection: **61 passed**, exit 0.
- `git diff --check`: exit 0. The handoff is an untracked Markdown file;
  no tracked source changes exist.
- An earlier test invocation mistakenly named nonexistent
  `tests/test_wizard.py`; pytest exited 4. The actual file is
  `tests/test_wizard_flow.py`.

Known pre-existing exclusions supplied by the task, not independently
reproduced by the blocked full baseline:

- `tests/test_live_image.py::test_staged_chroot_package_matches_src`
  (requires live-build configuration).
- `tests/test_helper_boot_guidance.py::test_helper_renders_both_windows_paths_on_small_and_desktop_displays`
  (Chrome pixel timeout).
- `tests/test_helper_boot_guidance.py::test_helper_and_iso_start_here_are_identical`
  (helper/START-HERE drift).

Coordinator: first verify HEAD and working-tree changes, create the requested
branch from the specified main, then inspect rendered fake-disk interfaces and
establish the exact required baseline. Implement and test the route, update
this record with actual results and screenshots, inspect the full diff and
rerun applicable checks. Stage explicit paths and use a `safety:` commit for
the selection-state change. Commit and push only after in-scope gates pass.
No ISO release or publish is authorized.
