# Backlog #85 — Normal arrow cursor in the live UI

## Baseline (before implementation)

Source identity: `60d827a` (origin/main) on branch
`feat/improve-screen-hierarchy`, plus uncommitted #83 spacing WIP and the
#84 severity WIP (both preserved untouched).

Reproduce: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest`

Result: **3 failed, 2625 passed, 523 skipped** (78s on the dev Mac).
Same 3 pre-existing environmental failures as the #84 baseline (headless
Chrome SIGABRT, staged-chroot drift at HEAD, sandbox socket denial).

Cursor baseline (verified by reading the code):

- `TkWizard.__init__` never sets a cursor on the root toplevel, so all
  ordinary content (labels, frames, panels, readers, canvases) inherits
  the X default. The kiosk runs bare `startx` with no window manager,
  no cursor theme, and no `xsetroot`, so that default is the X-server
  X cursor — over app content and over the root window (startup gap,
  any uncovered area).
- Explicit cursors today, all preserved: `_Button` hand2/arrow by
  enabled state, clickable cards and checkbox hand2. Entries/readers
  rely on Tk class defaults (xterm expected for text).
- `x11-xserver-utils` (ships `xsetroot` and `xset`) is already in
  `beamo.list.chroot`. `left_ptr` lives in the server core cursor
  font, so no new package is needed.

## Acceptance criteria (measurable)

1. Tk root cursor is `arrow`; ordinary-content widgets resolve to it
   through Tk inheritance.
2. Enabled buttons, clickable cards, and the checkbox keep `hand2`;
   disabled buttons keep `arrow`; text entries and readers show
   `xterm`.
3. The live launcher sets the X root cursor with
   `xsetroot -cursor_name left_ptr`, guarded by `DISPLAY` and with
   failures ignored (same pattern as the existing `xset` lines).
4. `x11-xserver-utils` stays pinned in `beamo.list.chroot`; the package
   list gains no cursor-theme package.
5. Only core Tk/X cursor names are used
   (arrow/hand2/xterm/left_ptr): no theme dependency, no `X_cursor`.
6. Suite results unchanged apart from new coverage and the 3
   pre-existing failures; no focus, click, touch, or keyboard change.

## Intentional differences

- The web preview, offline helper, and console keep their own cursor
  behavior (CSS defaults; VT text cursor): this task is the live X
  session plus the Tk app that fills it.
- The accessible GTK view is covered for the root window by the same
  launcher `xsetroot` call (it launches through `beamo-wipe` with
  `DISPLAY` set). Its in-app cursors are GTK defaults, unchanged.
- Staged chroot copies under `packaging/live/.../includes.chroot` are
  refreshed from git-tracked `src` by `scripts/build-iso.sh` at build
  time; the pre-existing drift-test failure is out of scope and the
  checkout is left un-restaged, consistent with in-flight work.
- Cursor-pixel screenshots are unavailable: no X server or working
  headless Chrome on this Mac, and CI has no root-cursor capture tool.
  Verification is programmatic (cursor option names, launcher text,
  package list) plus the unchanged runtime suites.

## Implementation

- `src/beamo_wipe/ui/tk_wizard.py`: root toplevel gets
  `cursor="arrow"` (ordinary content inherits it); the shared
  `_reader` constructor and both `tk.Entry` fields (typing check,
  confirmation token) pin `cursor="xterm"`. Existing `hand2` (enabled
  buttons, clickable cards, checkbox) and `arrow` (disabled buttons)
  settings are untouched.
- `packaging/live/.../usr/local/bin/beamo-wipe`: the existing
  `DISPLAY`-guarded block gains
  `xsetroot -cursor_name left_ptr 2>/dev/null || true`, covering the
  X root window for both the Tk and the accessible GTK sessions
  (both launch through this script with `DISPLAY` set). Mode 100755
  preserved. No package-list change: `x11-xserver-utils` already
  ships `xsetroot`, and `left_ptr` is in the server core cursor font.

## Results

- New `tests/test_arrow_cursor.py` (5 tests): 3 failed before the fix
  (launcher call, root arrow, xterm text), all pass after. New
  `test_cursor_roles_arrow_content_hand2_actions_xterm_text` in
  `tests/test_tk_runtime.py` asserts runtime roles on PICK/CONFIRM
  (skips without a display; runs in CI on Xvfb).
- Full suite after: 3 failed, 2630 passed, 524 skipped — the same 3
  pre-existing environmental failures as baseline (+5 passes, +1
  headless skip).
- Blocking lint (`compileall`, ruff security subsets), `ruff format`
  + `ruff check` on touched tests, shellcheck (incl. the launcher),
  and preview gates (`--web`, `--console`, `--helper`): pass.
- Fallback probes: missing `xsetroot` exits true and silent;
  unset `DISPLAY` skips the block.
- Source identity: HEAD `60d827a` + #83/#84 WIP (preserved) + #85
  changes above. Not committed (no commit authorization).

## Skipped environments (honest limits)

- No manufactured-ISO or QEMU run: Docker amd64 emulation on this
  Apple-silicon Mac is TCG (per repo guidance, not waited on) and
  Cloud Build credentials are unreachable from this sandbox. The
  change touches no boot, wipe, disk, or engine path.
- No cursor-pixel screenshots (see above); pointer shape verified by
  cursor-name assertions at every layer instead.
- Tk/GTK runtime tests skip locally (no X server, no `gi`) and run
  in CI.
