# Backlog #67 — compare similar disks

Base: main at 9210aa32f1598936b752f4662ed926b1f3b60044.
Branch: feat/compare-similar-disks. No feature branches merged.
Source identity: source-sha256.txt (the containing Git commit identifies the handoff).

## Baseline and acceptance

The mapped Tk picker on the base revision warns about equal capacities but offers
only vertically stacked selectable cards. See tk-before.png. The new identity
regression was also run against a detached copy of 9210aa3 and fails with
AttributeError: comparison_text is absent (regression-before.txt).

Acceptance: compare two and seven eligible candidates; show complete model,
capacity, serial and connection, including missing and duplicate identity warnings;
use two columns when space permits and one column on narrow screens; allow
keyboard reading and disclosure; preserve selected disk, picker screen, ownership
and non-started runner; keep protected devices out and fail closed without a
known boot device.

## Implementation and interface differences

The shared inventory presenter consumes the existing eligible snapshot. It uses
the full listed-disk snapshot for identity warnings, including duplicate IDs
reported by protected peers. No discovery, eligibility, confirmation, engine
flags or authorization code changed. Equal capacities appear adjacent; disk
numbers retain the path-sorted picker order.

Compare disks is offered whenever at least two candidates exist, so comparison
does not depend on a similarity heuristic. Tk uses a collapsed disclosure inside
the existing scrollable picker, two columns above 700 pixels and one below.
Each identity has a keyboard-focusable, character-wrapped, read-only text area
with its own scrollbar. Tab advances between readers; Up/Down and Page keys read
without selecting. Focus scrolls later comparison cards into view. Enter opens
the disclosure without continuing the wizard.

Browser preview uses native details/summary and responsive comparison cards.
GTK intentionally presents the same identities sequentially in an expandable,
selectable label for screen-reader reading. Curses uses C to open the existing
read-only scrolling mode and Esc to return. Plain console prints the shared
comparison before disk choices. These text fallbacks retain every field and
warning rather than depending on spatial alignment.

## Validation

All execution used demo/fake disks and DryRunRunner. No real disk erasure, nwipe
invocation, ISO build, release or publication was performed. Cloud ISO/QEMU gates
were not run: this change is presentation-only, with no ISO/x86 integration work.

Required command:

    dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest

Focused regression command adds tests/test_compare_disks.py: 13 passed.
Coverage includes complete 400-character identifiers, missing serial/model/bus,
hardware-ID fallback, duplicate warnings involving a protected peer, unknown
boot fail-closed behavior, 2/7 candidates, 900/500-pixel Tk comparison layouts,
real-picker focus/Enter handling, selection continuity, 40x16 curses navigation,
GTK disclosure/focus, and actual Chrome keyboard/reflow checks at 1100/390 pixels.
The initial 10-regression version was copied into the detached base worktree to
demonstrate failures on the original implementation.

Screenshots were inspected: Tk before/after and browser at 1100 and 390 pixels.
Browser screenshots use the generated fake-disk gallery with
#s=pick&disk=1&owner=1. The two 256 GB demo disks appear together after expansion.
Spoken comparison output was not manually verified; GTK focus and text exposure were
checked. Physical hardware and ISO boot were not exercised.

The first broad test attempt overlapped source edits, invalidating tests that
use inspect.getsource line locations. Its result was discarded. Subsequent broad
verification keeps implementation source fixed.

Final affected-suite command (same dbus/Xvfb prefix, fixed final source):

    python3 -m pytest tests/test_compare_disks.py tests/test_excluded_inventory.py tests/test_preview.py tests/test_console_parity.py tests/test_console_pick.py tests/test_accessible_runtime.py tests/test_tk_runtime.py tests/test_accessibility_lowres.py tests/test_adaptive_layout.py tests/test_rendered_visible_behavior.py tests/test_ui_rework.py tests/test_wizard_flow.py

Result: **522 passed, 2 skipped in 267.72s** (affected-suites.txt). This includes
all 13 comparison regressions, existing excluded-device keyboard isolation at
both sizes, AT-SPI external-client checks, existing Orca result announcements,
Tk layout/selection continuity, and authorization flow tests.

The full repository command completed with 2515 passed, 28 skipped and six
failures before final corrections (full-suite-summary.txt):
- Known out-of-scope helper Chrome rendering timeout:
  tests/test_helper_boot_guidance.py::test_helper_renders_both_windows_paths_on_small_and_desktop_displays.
- Known out-of-scope staged live-image source drift:
  tests/test_live_image.py::test_staged_chroot_package_matches_src.
- AT-SPI bus connection failure, subsequently passing in the final affected suite.
- An earlier over-specific comparison test expected a particular order within
  equal capacities. The corrected test requires adjacency and stable picker
  numbers, and passes in the final affected suite.
- Two excluded-device tests found that comparison readers reused their private
  inventory marker. Comparison readers now have a distinct marker; both kinds
  retain keyboard isolation. Both existing tests pass in the final affected suite.

The detached base run, augmented with the first ten new regressions, recorded
2504 passed, 30 skipped and 13 failures (base-summary.txt). Ten are expected
comparison regressions on the original implementation; the others were the
helper rendering timeout, Orca announcement test and a time-sensitive review
assertion. The latter two pass in the final affected suite.

No unresolved comparison or affected-suite failures remain. The full repository
suite is not claimed green. The two explicitly accepted helper/staging exceptions
remain outside this task. Final diff whitespace and source checksums were checked.
