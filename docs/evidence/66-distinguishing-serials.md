# #66 — distinguishing serial characters

## Baseline and acceptance (recorded before implementation)

Base: main `9210aa32f1598936b752f4662ed926b1f3b60044`.
Branch: `feat/highlight-distinguishing-serials`; no feature branches merged.
Verification environment: x86_64 Debian GNU/Linux 13 (trixie), Python 3.13.5,
Google Chrome 151.0.7922.169, isolated Xvfb at 72 DPI (2026-09-14 UTC).
Read AGENTS.md and memory; traced inventory, identity, safety, Wizard,
Tk, GTK screen-reader view, both console modes, and browser gallery.
Inspected native fake-disk PICK at 1024×740: full serials are present,
but the same-size warning gives no character-level comparison aid.
Baseline image: `/tmp/serial-before.png` (temporary local artifact).
The initial full-suite command (results below):

```sh
dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest
```

Acceptance: compare the same displayed-size groups as the existing warning;
retain full raw IDs; mark a comparison portion by removing the group's common
prefix and suffix, with explicit one-based character positions in plain text.
Near matches, more than two candidates, duplicates (including case differences),
missing serials, unequal lengths, and long serials must have deterministic,
accurate results. Never imply that a duplicate/missing serial distinguishes a
disk. Preserve confirmation tokens, owner gate, countdown and boot protection.
Native and browser comparison markers must work without color; GTK and console
must receive readable comparison guidance. Long IDs must wrap without clipping.

## Implementation and intentional presentation differences

`inventory.serial_comparison` compares the same displayed-capacity group used
by `same_size_conflict`, regardless of model. It removes only the group's
case-insensitive common prefix and non-overlapping common suffix. The remaining
contiguous portion retains all differences; it can include shared characters
between differences. Offsets refer to the complete, trimmed, displayed serial.
A shorter serial with no remaining portion gets an explicit length comparison,
not an invented character highlight. A duplicate serial receives no marker,
even if its duplicate has another capacity; a missing serial suppresses comparison for that group. Existing missing,
duplicate and ambiguous-identity warnings remain authoritative.

`DiskIdentityView` keeps `id_value` intact and adds display-only offsets,
`marked_id`, and a plain-language note. Comparison is opt-in; default identity
and evidence presentations retain their original content. Tk and browser
pickers use square brackets (no color dependency). GTK's accessible disk name and both console
pickers retain the full serial and announce the same character positions and
comparison text; they do not add punctuation to the serial itself. The wizard
requests this extra guidance only on PICK. Confirmation, method, review,
working and result screens continue to show the original full ID. The browser
has the same screen restriction. No boot eligibility, confirmation specification,
owner gate, countdown, nwipe flag or engine code changed.

The browser's serial label cannot shrink into a vertical column next to long
identifiers. All browser metadata still passes through HTML escaping; a real
headless-browser test checks long-ID bounds and hostile metadata rendering.

## Final verification and handoff

**Ready for review. All executed in-scope checks passed.** Final full gate:

```sh
dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest
```

Result: **2535 passed, 28 skipped, 2 failed in 429.72 seconds**. Exit status 1
is solely from the two user-approved exclusions listed below: the helper's
40-second Chrome rendering timeout and stale live-image staging (`gallery.py`).
No exclusion was added for serial highlighting. The complete local run log is
`/tmp/serial-full-verified.log`. The final suite includes all **28 new regression
cases**, covering comparison logic, authorization separation, native wrapping,
GTK accessible names, browser escaping and browser layout.

The final focused serial/rendered-behavior run also passed **58 tests**:

```sh
dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest tests/test_serial_comparison.py tests/test_rendered_visible_behavior.py
```

Final syntax, repository-prescribed blocking security lint, source checksums
and `git diff --check` passed:

```sh
python3 -m compileall -q src/beamo_wipe
python3 -m ruff check --select S102,S103,S104,S105,S106,S107,S113,S307,S501,S506,S508,S602,S604,S605,S606,S608,S609,S610,S611,S612 src/beamo_wipe
python3 -m ruff check --select S102,S103,S104,S107,S113,S307,S501,S506,S508,S602,S604,S605,S606,S608,S609,S610,S611,S612 tests
sha256sum -c docs/evidence/66-source-sha256.txt
git diff --check
```

The task and full diff were reread after implementation; every in-scope failure
found during verification was resolved and covered by the final full run.
The temporary detached baseline checkout was removed. Commit and push are
limited to `feat/highlight-distinguishing-serials`; no merge or image publication.

## Verification ledger

- Isolated original revision (`git worktree add --detach /tmp/beamo-serial-base
  9210aa32f1598936b752f4662ed926b1f3b60044`), with the first version of the new
  regression file copied in: **17 failed**, proving missing comparison behavior.
  Command: the standard dbus/Xvfb prefix above followed by
  `python3 -m pytest tests/test_serial_comparison.py`.
- First implementation: **22 focused checks passed** (shared logic, Tk at
  1024×740 and 1280×820, GTK accessible names). Subsequent browser checks caught
  and fixed long-serial label shrinkage.
- Initial whole-suite invocation began before editing and finished during edits:
  **2506 passed, 28 skipped, 3 failed**. Two are the user-listed exclusions below.
  The third, `test_gallery_escapes_html`, reads source during execution and
  encountered the new escaped display expression. Its assertion was updated
  to the new expression, retaining the escaping requirement; hostile metadata
  is also checked in a real browser. This overlapping run is not represented
  as a pristine whole-suite baseline.
- First broader in-scope run: **367 passed, 2 skipped, 2 failed**. A GTK method
  choice was displaced by comparison prose outside the picker; fixed by limiting
  guidance to PICK. The AT-SPI external-client test lost its bus socket while
  GUI runs overlapped; subsequent GUI gates run sequentially.

- Sequential comparison/security/GTK run after the layout fix: **115 passed**,
  including the external AT-SPI client and method-choice visibility checks.
- A later full-suite attempt was stopped after four native label-lookup
  assertions expected unmarked picker text. `test_design_runtime.py` now
  locates the marked display while separately checking raw-ID preservation;
  its existing wrapping, geometry and wheel-scrolling checks remain intact.
  Rerun: **53 passed** (`tests/test_design_runtime.py`).
- Final review added suppression for duplicate serials at another capacity,
  keeping comparison guidance consistent with the existing duplicate warning.

Known exclusions, supplied by the user:

- `tests/test_live_image.py::test_staged_chroot_package_matches_src`: live-build
  staging needs `lb config` / an ISO build.
- `tests/test_helper_boot_guidance.py::test_helper_renders_both_windows_paths_on_small_and_desktop_displays`:
  existing Chrome pixel-test timeout.

## Scope and remaining environment limits

Only synthetic disk fixtures, `DryRunRunner`, and preview rendering were used.
No real disk was targeted. No ISO build, QEMU run, release or image publication.
This is a Python presentation change, not ISO/x86 build work, so Cloud Build
and physical boot media were not exercised. Automated GTK accessible names
and the existing external AT-SPI client checks cover accessibility semantics;
a human Orca listening session and physical hardware remain untested.

Comparison markers are an aid for inspection, not proof that a physical drive
has been identified. Raw identifiers, confirmation tokens and evidence fields
retain their existing values. A missing peer serial deliberately prevents a
partial comparison rather than implying uniqueness.

## Reproducing the visual evidence

From the repository root (Pillow and the repository's GUI dependencies required):

```sh
dbus-run-session -- xvfb-run -a -s "-screen 0 1024x740x24 -dpi 72" env PYTHONPATH=src:tests python3 docs/evidence/66-render-serials.py near /tmp/serial-final
```

Repeat with `long`, `duplicate`, or `missing`. Each run writes an isolated
native PNG and a self-contained browser preview to the output directory.
For the browser, open the generated `near.html#s=pick`, or reproduce the
headless capture (using a fresh temporary Chrome profile):

```sh
google-chrome --headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage --no-first-run --user-data-dir=/tmp/serial-review-chrome --window-size=1024,1160 --screenshot=/tmp/serial-final/near-web.png 'file:///tmp/serial-final/near.html#s=pick'
```

Inspected evidence:

- [Original near-match picker](66-serials/near-before-tk.png)
- [Updated near-match picker](66-serials/near-tk.png)
- [Updated 321-character serials in Tk](66-serials/long-tk.png)
- [Updated browser picker](66-serials/near-web.png)
- [Updated long serials in browser](66-serials/long-web.png)

The baseline near-match image was rendered at the isolated original revision
with the same synthetic fixture. Duplicate and missing-serial renders were
also inspected; they retain existing warnings and have no comparison markers.
The browser test checks rendered text, label line count, serial bounds and
HTML injection; Tk checks actual label geometry at both supported test sizes.

The final implementation and regression-source identities are recorded in
[66-source-sha256.txt](66-source-sha256.txt); verify from the repository root
with `sha256sum -c docs/evidence/66-source-sha256.txt`. The feature commit
containing this note is the reviewable source revision; it descends directly
from the base commit above without merging #58 or #61.
