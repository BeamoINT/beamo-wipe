# Beamo Wipe UI improvement pass 2 — 9 September 2026

## Outcome and source

Implementation, local verification and the required full Cloud Build gate
are complete. The feature branch is ready for review; final commit identity
and the PR link are recorded in the handoff and pull request.

- Feature branch: `codex/ui-improvement-20260909`.
- Base: `e931d6da292e70a247792cd53050628b0f782ca2` (PR #5, still open at review time).
- Clean validation snapshot: `73bb6504a05865e1a82e4e81a66e3a7fadd90e6c`.
- [Source hashes](source.json) cover all 975 tracked snapshot files. Every file
  matched this checkout before submission. The snapshot contains the eight
  changed source/test files and excludes unrelated untracked work.
- [Cloud Build](https://console.cloud.google.com/cloud-build/builds/80eac957-d39a-496d-89b6-8c0811831a0b?project=beamo-wipe)
  finished **SUCCESS** with `_SKIP_ISO=false`, `_SKIP_QEMU=false`,
  `_PUBLISH_RELEASE=false`. ISO, QEMU and enrolled Secure Boot checks passed;
  publication remained disabled.
  [Receipt](cloud-build.json), [submission](cloud-submit-verified.txt),
  [result summary](cloud-results.txt), [logs](cloud-log.txt).

No real disk was erased. Local execution uses fake disks and DryRunRunner;
regular-file FAT32 tests use disposable files. The hosted QEMU gate uses its
controlled disposable guest targets. No ISO publication, main push, or merge
is authorized or performed.

## Changes

The existing Tk, GTK and browser preview remain the frontend stack. No screens,
engine features, dependencies, discovery rules, authorization states, or nwipe
flags were added or removed. nwipe stays pinned at 0.42.

- **Disk identity:** Tk and the browser always display the full device path,
  alongside the full model, capacity and serial. Show more still exposes
  connection details. Picker instructions explicitly ask owners to match the
  name, size and serial, and the same-size warning names serial numbers.
- **Hierarchy:** The selected-SSD notice retains its complete limitation and
  certificate text, in a more compact secondary panel. Disk rows use less
  vertical padding. Final review gives identity more room with a 144-pixel
  countdown instead of 190 pixels.
- **Destructive communication:** Countdown completion shows zero and explicitly
  says nothing has started; it does not borrow a green success checkmark.
  The red Erase action, five-second delay and safe Back focus remain.
  GTK separates headings from destructive notices and focuses the full warning
  notice on arrival so Orca speaks the destructive consequence. The notice
  does not select its text on focus, preserving the established announcement fix.
- **GTK layout:** Utility actions occupy a three-column grid above the
  navigation row. Back is on the left; the primary action is on the right.
  Native controls retain keyboard and AT-SPI behavior, with explicit focus
  outlines and separate primary/destructive colors. All method choices are
  visible at 800×600; the former six full-width footer rows obscured them.
- **Reader sizing:** GTK's Advanced, report-help and storage-limits readers
  could request 879-pixel-wide windows at 800×600. Their inner scroller now
  constrains the text view while preserving wrapping, reading and scrolling.
  Long unbroken identities wrap by character where necessary. The existing
  monitor-workarea sizing and resize waiter are unchanged.
- **Input:** Scrolling over a Tk disk row's labels now scrolls the disk list
  without changing selection or focus. Browser keyboard selection retains
  focus on the selected disk, and countdown redraws preserve safe Back focus.

The ownership checkbox, token match, full countdown, explicit erase activation,
held-key and stale-callback defenses, boot-media exclusion, fail-closed refresh,
cancellation, evidence/report recovery, and shutdown-loss confirmation remain
covered by the full suite. Result categories and verification status are unchanged.

## Verification

Readable text logs use LF line endings with trailing whitespace removed.
[Raw log archive](raw-logs.tar.gz) preserves the original captured bytes.

| Check | Result | Evidence |
| --- | --- | --- |
| Repaired baseline, full suite at 72 DPI with FAT32 tools on PATH | **1,716 passed; 12 ISO skips; 2 deselected** | [Baseline](baseline-repaired-fat32.txt) |
| Final complete suite, including 67 added parameterized regressions | **1,783 passed; 12 ISO skips; 2 deselected**, 89.88 seconds | [Final suite](full-suite.txt) |
| Hosted Bookworm full Python suite | **1,783 passed; 12 ISO skips; 2 deselected**, 157.18 seconds | [Hosted log](cloud-log.txt) |
| Native GTK/AT-SPI/Orca iteration | **79 passed**; final full suite also covers real spoken destructive warnings | [GTK](gtk-iteration-4.txt) |
| Blocking syntax, ShellCheck and security lint | **Passed** | [Blocking lint](lint-blocking.txt) |
| Full Ruff and mypy | **Passed**; mypy reports no issues in 28 source files | [Final lint/type report](lint-final.txt) |
| Real Orca destructive-warning smoke | **Passed**, complete confirmation and final-review warnings spoken | [Spoken-warning check](orca-warnings-fixed.txt) |
| GTK 2× display scale | **21 passed**, all 19 screens plus long-identity warnings at 800×600 logical size | [Scaling](gtk-scale-2.txt) |
| Python production wheel and sdist | **Built successfully** | [Build log](python-build.txt) |
| Chromium layouts | **90 passed**: 15 states at 390×844, 800×600, 1024×740, 1280×820, 1366×768, 1920×1080 | [Browser receipt](browser-verification.json) |
| Browser keyboard, countdown, fake completion | **Passed**, no JavaScript errors | [Reproducible browser driver](verify-gallery.py) |
| Cloud Build, including desktop, negative safety, ISO and QEMU | **SUCCESS** | [Hosted receipt](cloud-build.json) |

The 12 skips require the absent manufacturing ISO. The two deselections require
live-build's generated `bootstrap`/`binary` configuration, as documented by
`scripts/ci-hosted.sh`. No GTK, Tk, Orca, keyboard or FAT32 tests were skipped in
the final local gate. No required failure is counted as a pass.

Final local command:

```sh
PATH=/usr/sbin:/sbin:/usr/local/bin:/usr/bin:/bin \
BEAMO_WIPE_DRY_RUN=1 BEAMO_ISOLATED_X11_TEST=1 \
dbus-run-session -- xvfb-run -a \
  -s '-screen 0 1600x1000x24 -dpi 72' \
  ./scripts/test-all.sh -rs \
  -k 'not test_iso_build_uses_https_debian_mirrors and not test_live_config_xinit_cannot_hijack_kiosk'
```

### Regressions demonstrated against original source

Running the new tests with the original UI modules in an isolated import tree
produced the expected **seven Tk failures**: five hidden-path cases, the old
countdown message, and wheel input over a disk label. The GTK checks produced
**four expected failures**: Advanced/report-help/limits exceeded 800-pixel width,
and the method choices extended below the footer. These tests pass against the
final implementation. [Tk before](regressions-before.txt),
[GTK before](gtk-regressions-before.txt).

An additional real-Orca smoke check exposed that overriding a short label's
accessible name did not make Orca speak the warning: Orca used the visible
text interface. The final implementation focuses the complete warning label,
and the main Orca test now exercises both confirmation and final review.
[Before](orca-warning-announcements.txt), [after](orca-warnings-fixed.txt),
[standalone driver](verify-orca-warnings.py).

Other new cases cover all 19 GTK screens at 800×600, long identity/warning
visibility and announcements, native footer keyboard traversal, and all 19 Tk
screens at both 1366×768 and 1920×1080. Existing tests retain 1024×740 and
1280×820 coverage, including long identities, report failures/recovery,
shutdown, busy transitions, held activation keys and real isolated X11 input.

### Iteration findings

Build `c87764ca-a264-4eb8-8cde-e91347cba01f` passed its desktop, lint,
Python and preview phases, then was deliberately cancelled when screenshot
review found a stale browser keyboard hint. The corrected hint now matches
safe Back focus, with browser coverage. This superseded build is not the final
gate. [Cancelled receipt](cloud-superseded.json).

Build `6ff1c860-dd9c-48ab-a8be-fc29c1c42989` was likewise superseded after
the additional real-Orca check exposed the warning-announcement issue. It is
not counted as the final gate. [Receipt](cloud-second-superseded.json).

The [first-turn baseline record](first-turn-baseline.md) and its original logs
are retained as history. The first repaired run passed 1,704 tests but skipped
FAT32 cases because `/usr/sbin` was absent from PATH. Adding the installed tools
to PATH produced the complete green baseline above.

A proposed GTK flow layout requested excessive height and was replaced by the
current grid. Footer word wrapping was kept at word boundaries to avoid
one-character minimum-width requests. An empty utility container was removed
instead of weakening the unchanged footer/resize checks. Concurrent native
capture and screen-reader tests interfered with an AT-SPI connection; final
native tests and captures ran separately.

The first final full suite found one stale generated ISO-stage Python copy.
Refreshing `packaging/live/config/includes.chroot/usr/lib/python3/dist-packages/beamo_wipe`
using the build script's tracked-source copy rule resolved that mismatch;
the complete suite then passed. The stale-copy assertion was retained. A later new selection assertion was
corrected to unpack GTK's `(has_selection, start, end)` result, matching the
existing result-focus regression. The no-selection requirement was retained.

Browser-driver corrections ensure every deep link reloads and allow one CSS
pixel for Chromium's fractional scroll rounding. They do not disable layout,
identity, keyboard, countdown or error assertions.

## Rendered review and acceptance

[Capture driver](capture-ui.py) renders the real native widgets using fake
presentation fixtures. It does not execute an erase. Thirty captures per view
cover all 19 Screen values plus 11 canonical result cases. Tk is captured at
1024×740 and GTK at 800×600, on private 72-DPI Xvfb displays. Initial baseline
GTK capture exposed the reader-width overflow and stopped after 13 states;
all 30 final states capture successfully.

- Tk contact sheets: [1](final-tk-contact-1.png), [2](final-tk-contact-2.png),
  [3](final-tk-contact-3.png). Full-size files are under `final-tk/`.
- GTK contact sheets: [1](final-gtk-contact-1.png), [2](final-gtk-contact-2.png),
  [3](final-gtk-contact-3.png). Full-size files are under `final-gtk/`.
- Browser review: [390-pixel contact sheet](gallery-contact-390.png),
  [1024-pixel contact sheet](gallery-contact-1024.png),
  [picker](gallery-1024-pick.png), [review](gallery-1024-last.png).

Screens were visually reviewed for hierarchy, complete identity/warnings,
readable progress and result distinctions, and reachable controls. Tests check
layout and actual behavior separately; a fixture's DONE screen is not proof that
an operation completed. Existing contrast tests retain 4.5:1 text and 3:1
focus/control floors for the shared palette. The new GTK colors use those same
palette values.

Tk's supported minimum remains **1024×740**. Inspection at physical
800×600 and 1024×600 confirms that it still allocates that minimum window,
so content and footer can extend beyond those smaller displays. This existing
limitation is not promoted to supported by the browser's responsive layout.
[800×600 inspection](tk-degraded-800.txt),
[1024×600 inspection](tk-degraded-1024.txt). GTK's 800×600 support is independently verified. Physical displays,
firmware and physical USB media are not newly certified by this work.

## Review handoff

All required gates passed. Review is stacked on PR #5 using base
`codex/cross-platform-20260908`; no main merge or release is part of this task.
The shipped wizard zeroed only its disposable guest target, and its exported
report passed completion, checksum, read-only verification and unmount checks.
No physical-media or firmware certification is implied by the QEMU evidence.
