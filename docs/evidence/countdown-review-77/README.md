# Countdown as a review period (#77)

## Source and baseline

Base: `main`, `9210aa32f1598936b752f4662ed926b1f3b60044`.
Branch: `feat/countdown-review-period`. No feature branches merged.
Read `AGENTS.md` and `.ai/memory/{MEMORY,product-constraints,visual-verification-on-this-mac}.md`.
Only demo disks / DryRunRunner are used.

Before implementation, rendered Tk and browser final review at 1280×820
(`before-tk.png`, `before-web.png`). The ring is 144px with a 56px numeral;
method explanation is ordinary body text. The title says “Last chance to stop”,
although nothing is running. Existing caption correctly says nothing starts
automatically, but the message is relegated beside the dominant ring.
The existing state machine only enables Erase at zero. Tk and browser default
focus to Back; GTK focuses the consequence warning. Preserve these differences.

Reproduce screenshots with `BEAMO_WIPE_NO_OPEN=1 ./preview --web`, then
`PYTHONPATH=src:tests dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 docs/evidence/countdown-review-77/render.py before`.
The script writes `/tmp/beamo-77/`; requires Pillow and Playwright Chromium.

## Acceptance criteria recorded before implementation

- Review title and lead ask the owner to check selected disk and method and
  explicitly say zero only enables Erase and never starts erasure.
- Ring no larger than 64px across supported Tk sizes and browser widths;
  numeral no larger than ordinary bold body text. Selected disk and plain
  method operation remain above technical pass details, readable and unclipped.
- Timer completion stays on final review with unchanged focus and no runner
  invocation. Erase requires a fresh deliberate activation.
- Existing Back/Enter, mouse, keyboard, held/repeated Enter, stale callbacks,
  refresh clearing confirmations, and new five-second review on re-entry pass.
- GTK exposes review explanation and waiting/ready text through real labels;
  unchanged countdown text does not emit duplicate text-change notifications.
- Console keeps its existing activation conventions, with explicit review and
  no-auto-start wording. Document intentional renderer differences.
- Full required local pytest passes; inspect final rendered output and diff.

## Verification and handoff

Stopped before implementation because the required baseline gate failed.

Command (exact requested form):

```sh
dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest
```

Result: **1 failed, 2508 passed, 28 skipped in 338.30s**, exit 1.
Failure: `tests/test_live_image.py::test_staged_chroot_package_matches_src`:
`AssertionError: staged copy drifted: gallery.py` (line 193).
The pre-existing, gitignored copy under
`packaging/live/config/includes.chroot/usr/lib/python3/dist-packages/beamo_wipe/`
contains selected-disk summary / more-link additions on the method screen that
are absent from the clean base source. Read-only diff confirmed the mismatch;
no staging files were repaired, removed, or regenerated.

Tk and browser baseline screenshots were inspected, as was GTK at 1024×740
(`before-gtk.png`). GTK exposes the warning, full identity, method, and “Wait 5
seconds.” No countdown redesign or regression tests were implemented because
the user explicitly required stopping on a failed required gate.

No source changes, commit, push, feature-branch merges, real-disk erase, ISO
build, or release/publication. Evidence files remain untracked on the requested
branch. No final implementation acceptance claims are made. Physical hardware,
booted live ISO, actual Orca speech, and cross-platform verification were not
performed. Local suite skips remain reported rather than treated as passes.

Next prerequisite: reconcile the stale generated chroot staging with the base
source, then repeat the baseline gate before implementing the criteria above.

## Implementation (resumed September 14, 2026)

The user explicitly waived the stale generated staging baseline failure as an
out-of-scope blocker. This supersedes the “Next prerequisite” above; the
original baseline record and images are retained unchanged.

- Shared title is “Review before erasing.” The lead asks for selected disk and
  method review and explicitly says zero only enables Erase, never erasure.
- Tk ring is 64px at every layout breakpoint (previously 96–144px), with a 4px
  stroke and ordinary bold body numeral. Browser ring is 64px with a 16px
  numeral (previously 144px / 56px). Plain method operation now uses bold body
  text in both, above technical pass details.
- GTK waiting/ready text remains a real label. It is updated only when its
  text changes, avoiding redundant text-change notifications at each tick.
- Both console paths display the shared review explanation. Disk discovery,
  confirmation authorization, countdown timing, activation handlers, and
  nwipe flags are unchanged.

### Intentional renderer differences

Tk and browser default focus to Back; GTK retains focus on the full consequence
warning for screen-reader arrival. GTK uses text instead of a decorative ring.
Tk's compact 800×600 view scrolls the review body with fixed navigation; the
disk and operation are above the timer, which is below the initial fold.
The browser scrolls the page and stacks its review at its existing CSS
breakpoint. Curses retains deliberate Enter activation after waiting; the
plain console retains its explicit typed ERASE prompt. “Enables Erase” refers
to making that renderer's explicit erase action available. Neither console
starts erasure when the wait ends. Browser remains a fake-disk preview.

### Rendered evidence and regression coverage

Inspected after-tk.png and after-web.png at 1280×820; after-small-tk.png and
after-small-web.png at 800×600; after-gtk.png at 1024×740. Selected disk and
plain operation are readable above technical details. Tk/browser ring and
numeral measurements are asserted, rather than inferred from screenshots.

New Tk regression covers 800×600, 1024×740, 1280×820, and 1600×1000,
measuring ring and font size and asserting unchanged focus, review screen,
and no runner invocation at zero. The original ring sizes fail this test.
New GTK regression checks one notification on readiness, no notifications
for duplicate waiting/ready updates, unchanged focus, and no runner start.
Console regression asserts the shared review/no-auto-start explanation.

Reproducible browser check:

```sh
BEAMO_WIPE_NO_OPEN=1 ./preview --web
python3 docs/evidence/countdown-review-77/check_browser.py
```

The script measures 375, 800, 1024, 1280, and 1600px widths and exercises
Back/Enter, repeated Enter, timer reset on re-entry, completion without
navigation or focus change, explicit keyboard/mouse activation, and F5
clearing confirmations. Playwright's virtual clock advances the real preview
interval callbacks. No erase engine is involved.

Existing local regressions additionally cover five-second timing, held/split
Enter repeats, stale callbacks, method changes invalidating authorization,
Back requiring a fresh countdown, refresh clearing all authorization, and
mouse/keyboard activation. See test_confirmation_gates.py,
test_last_chance_operation.py, test_refresh_disks.py, test_tk_runtime.py,
test_accessible_runtime.py, and test_console_parity.py.

Targeted verification:
- Native GTK (system Python, Xvfb 72 DPI): 3 passed, 82 deselected (new label
  regression, focus/Enter, and refresh).
- Tk geometry/focus plus console review copy (Xvfb 72 DPI): 7 passed,
  196 deselected.

No physical hardware, booted ISO, real-disk erasure, or image release was
performed. This is UI/copy work, with no ISO/x86 build changes. Actual spoken
review phrasing was not manually auditioned; GTK label notifications and
existing accessibility tests provide automated coverage.

### Full-suite verification history

First implementation run used the exact requested command: **3 failed,
2511 passed, 28 skipped in 340.42s**. One in-scope test still expected the
old no-auto-start caption beside the ring. Updated
test_design_runtime.py::test_countdown_ready_still_explains_nothing_started
to assert the actual rendered shared lead and its explicit no-auto-start
wording, while retaining ready-caption, numeral, Back focus, and no-runner
assertions.

The other two failures are user-accepted out-of-scope baseline failures:
- test_live_image.py::test_staged_chroot_package_matches_src: stale,
  gitignored chroot package differs from source (gallery.py).
- test_helper_boot_guidance.py::test_helper_renders_both_windows_paths_on_small_and_desktop_displays:
  external Chrome exited -11 during screenshot capture, reporting D-Bus/
  accessibility bus and viz.mojom.CopyOutputResultSender errors. Helper
  source and this test were not modified.

Final rerun excludes exactly those two known failures:

```sh
dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest \
  --deselect tests/test_live_image.py::test_staged_chroot_package_matches_src \
  --deselect tests/test_helper_boot_guidance.py::test_helper_renders_both_windows_paths_on_small_and_desktop_displays
```

Final result: **2512 passed, 28 skipped, 2 deselected in 338.77s**, exit 0.
Browser checks passed at all five widths; native GTK notification checks and
targeted Tk/console checks passed as recorded above. Re-read the task and full
diff, inspected the rendered output, and ran git diff --check successfully.
No unresolved in-scope defects were found. The two explicitly deselected
baseline failures and the suite's existing skips are not claimed as passes.
