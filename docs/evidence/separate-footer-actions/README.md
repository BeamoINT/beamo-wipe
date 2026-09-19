# #82 Simplify and separate footer actions

Fake disks only. No image published.

## Baseline (`origin/main` `60d827a`)

Primary navigation is not in one consistent place relative to assistance.

Tk `_footer_shell` already packs utilities (Advanced, Keyboard layout,
Check disks again, Need a report?, Screen-reader view, Diagnostic) above a
hairline. Keyboard hints still sit in the middle of the action row
(`left Back | mid hints | right Primary`). On Review before erasing that
places “Tab to Erase” between **Back** and **Erase now**. Short windows
already wrap the hint above the action row; default and large windows do
not.

The browser gallery mirrors that mix: `#utilities` is above `.footrow`,
but `#hint` is still between `#btnsL` and `#btnsR`. At `max-width: 700px`
the hint wraps under the buttons (`order: 3`).

GTK already keeps `self.utilities` above `self.navigation`. The 80×24
console already prints `_primary_footer` first and drops `_chrome_extra`
before an action is clipped. The boot helper has no wizard footer.

Gallery baseline (fake disks, headless Chrome `--virtual-time-budget=8000`):
`before-last-1280.png`, `before-pick-1280.png`, `before-method-1280.png`,
`before-done-1280.png`, `before-last-800.png`. Tk pixels: `screencapture`
is TCC-blocked on this Mac.

## Acceptance

1. Every screen’s primary navigation is the same row: secondary/Back left,
   primary right. No keyboard hint sits between those actions.
2. Assistance, diagnostics, refresh, report help, accessibility, and
   keyboard hints live in a separate accessible structure above the
   hairline. Tab order is assist controls, then Back, then Primary.
3. Last chance still focuses Back, never Erase. Enter/Space on Back still
   returns. Erase still requires a focused, countdown-enabled control.
4. Finished still focuses Shut down; Tab still reaches Show more then
   Save report without a new control stealing that path. Erase another
   stays a non-primary control, not adjacent to a new destructive control.
5. Small screens (800×600, 1024×600) keep identity, warnings, and both
   the assist structure and the navigation row reachable. Hints wrap;
   utilities stack rather than vanish.
6. No recovery path is lost: F5, report help, diagnostic, keyboard
   layout, F8, Advanced, and the console extras remain available on the
   same screens as today.
7. Disk identity, uncertainty, exclusions, destructive warnings,
   verification state, failures, and recovery limits stay visible.
8. Tk, gallery, GTK, console, helper, and docs stay aligned. Intentional
   differences are documented.

## Intentional differences

- GTK has no key-cap hint bar: AT-SPI already names each native control.
  Utilities stay a separate grid; that grid and the navigation row get
  accessible names.
- Console keeps primary actions first so Enter/Esc survive 80×24
  clipping. Extra chrome is a following line and is dropped first.
- The boot helper has no wizard footer; it is not a wipe UI.
- Gallery Erase another stays in the utilities strip (preview has no
  live report USB). Tk live Finished keeps Erase another on the
  navigation left with Save report, so Shut down → Show more → Save
  report Tab order is unchanged.
- Gallery has no Keyboard layout utility; Tk and the console still do.
  The preview does not change the live keyboard map.

## Implementation

Tk `_footer_shell` packs utilities, the Done USB reminder, and keyboard
hints in one assist strip above the hairline. The navigation row is only
`row._left` and `row._right`. Gallery `#hint` moved into `.assist`
(`role="region"`). Method Advanced is a ghost in that strip, matching Tk.
GTK sets accessible names on the existing utilities grid and navigation
box. Console extras were already separate.

## Verification

- `original-regression.txt`: the new source pins failed on `60d827a`.
- `PYTHONPATH=src python3 -m pytest tests/test_separate_footer_actions.py`
  plus `DISPLAY=:0` geometry/tab tests at 1280×820, 1024×740, 800×600:
  last-chance hint is above Back/Erase; Back stays focused; Tab goes to
  Erase once the countdown is ready; METHOD keeps Advanced, Check disks
  again, and Need a report? above the navigation row.
- `DISPLAY=:0` also passed
  `test_result_tab_order_reaches_report_without_shutdown`,
  `test_last_chance_enter_activates_default_back`,
  `test_screen_fits_without_clipping`, `test_done_screen_fits`,
  `test_erase_another_report_guard_and_layout`, and
  `tests/test_adaptive_layout.py`.
- `BEAMO_GATE_CHILD=1 ./scripts/ci-hosted.sh lint|preview|negative` PASS.
- Non-Tk pytest (ignored `test_tk_runtime.py`, `test_design_runtime.py`,
  `test_accessible_runtime.py`, `test_ui_rework.py`; excluded the two
  known Mac failures below) exit 0.
- After screenshots: `after-last-1280.png`, `after-method-1280.png`,
  `after-pick-1280.png`, `after-done-1280.png`, `after-last-800.png`.
  Review before erasing shows Check disks again and the hint above the
  hairline, Back left, Erase now right, identity and the irreversible
  warning still visible.

## Skipped environments

- Full `DISPLAY=:0 python3 -m pytest tests/test_tk_runtime.py` hung around
  38% after ~10 minutes (pre-existing on this Mac; killed). Focused Tk
  tests above passed.
- GTK `gi` missing: `test_gtk_comparison_disclosure_is_read_only`.
- Gitignored `support_export.py` chroot drift:
  `test_staged_chroot_package_matches_src`.
- ISO/QEMU and physical hardware were not run. Presentation-only; no
  image published.
- `screencapture` is TCC-blocked; Tk covered by runtime tests.

Source identity is the Git commit on `feat/separate-footer-actions`.
Author: Grok 4.6.
