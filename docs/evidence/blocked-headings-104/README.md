# Backlog #104 — Use the specific problem as the error heading

RISK (honest): FR/DE wording for the new strings is
first-draft, written without native-speaker review
(same standing risk as #87–#102). Recommend native
review before any release.

## Baseline (before implementation)

Source identity: `60d827a` on branch
`feat/improve-screen-hierarchy`, plus uncommitted
#87–#102 WIP (all preserved untouched).

Reproduce: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest`

Guidance baseline (verified by reading the code):

- Tk blocked screen headed every failure with the
  generic `TITLE_BLOCKED` ("Stop"); the gallery
  preview did the same.
- The accessible renderer misused the entire
  `IDENTIFY_ERROR` message as the heading, then
  repeated it in the body.
- Console plain/curses showed only
  `Error: {message}` with no problem heading.
- Blocked errors found by inventory (all flow
  through `wizard.error` on `PICK_BLOCKED`):
  `IDENTIFY_ERROR` (discover + boot exclusion),
  `BOOT_APPEARED_SELECTABLE`, `BOOT_APPEARED_ALIAS`
  (safety), `STARTUP_BLOCKED` (app startup),
  `REDISCOVER_ERROR` (refresh), plus the recovery
  path (already headed "Session recovery").
  `CHECKING_AGAIN` is a refresh transient, never
  a blocked error.

## Design decisions (recorded before implementation)

- `BLOCKED_HEADINGS` map + `blocked_heading_for()`
  in `copy.py`, mirroring the #101
  `EXPORT_NEXT_STEPS` precedent: known errors name
  the problem; unknown errors map to "" and callers
  keep `TITLE_BLOCKED` as the honest fallback.
- Empty/None error maps to the identify heading
  because every caller renders `IDENTIFY_ERROR`
  as the body in that case — heading always
  matches the shown explanation.
- One shared `blocked_title(error, recovered=)`
  used by all four renderers (recovery keeps its
  existing precedence everywhere, including
  console, which now matches Tk/GTK there).
- Map keys are the live module attributes (read
  under local import; safety and app both import
  copy), rebuilt in `_apply_language`, so FR/DE
  sessions match translated messages. Built
  lazily because app/safety may still be
  importing when copy loads.
- House voice has zero contractions anywhere, so
  the task's illustrative "couldn't" ships as
  "We could not identify the Beamo USB".
  Deliberate, documented here.
- Error bodies byte-identical; severity labels,
  buttons, hints, and the diagnostic flow from
  blocked are untouched.

## Acceptance criteria (measurable)

1. All 5 blocked errors map to unique headings
   naming the problem (≤60 chars); unknown → ""
   → generic fallback; empty → identify.
2. Tk + accessible + console-plain + console-
   curses + gallery show the specific heading
   first, then the unchanged explanation.
3. Heading precedes the severity line in every
   renderer; accessible no longer uses the whole
   message as its heading.
4. FR/DE parity for the 5 new keys (sweep test).
5. Small screens: Tk adaptive assertion extended;
   curses wraps; console frame eyeballed.
6. Technical detail preserved: diagnostic action,
   error codes, and stderr log untouched.
7. Safe recovery preserved: shutdown/back/
   diagnostic/refresh actions untouched.

## Implementation

- `copy.py`: 5 `BLOCKED_HEADING_*` constants,
  `_build_blocked_headings()`,
  `blocked_heading_for()`, `blocked_title()`,
  `_apply_language` rebuild.
- `ui/tk_wizard.py`, `ui/accessible_wizard.py`:
  one-line heading switch each.
- `ui/console_wizard.py`: heading line before the
  severity line in plain + curses.
- `gallery.py`: blocked title is the identify
  heading (the gallery blocked demo is the
  identify case; body already was).
- `locales/fr.py`, `locales/de.py`: 5 keys each.
- Helper has no blocked-screen content; no doc
  pins the old heading — both intentionally
  untouched.

Known limit: an error raised in English before a
language switch keeps its English text, so under
FR/DE it falls back to the translated generic
heading rather than a wrong specific one. No
crash, no mismatch with the body language.

## Verification

- New `tests/test_blocked_headings.py` (7 tests):
  errored on collection before (missing
  helper), all pass after. Covers uniqueness,
  key/source drift guard, fallbacks, FR/DE
  round-trip, console plain + curses ordering,
  gallery payload.
- Extended Tk adaptive assertion (CI/Xvfb) and
  added an accessible heading test (skips
  headless here); both follow existing file
  patterns.
- Curses 80x24 blocked frame rendered from fake
  discovery and eyeballed: heading → Error →
  actions, correctly wrapped.
- Full suite: **3 failed, 2888 passed, 560
  skipped** (3451 total). The 3 failures are
  the known pre-existing environmental ones.
- Blocking ruff security selections pass (src +
  tests); new code format-clean (remaining
  full-check E402/E702 and format drift are
  pre-existing WIP, and CI's full check is
  advisory).
- mypy advisory unchanged: 22 pre-existing
  errors, none in touched files.
- Tk/accessible pixels, ISO/QEMU, live nwipe
  remain CI/VM-only, unproven on this Mac
  (no Xvfb; browsers sandbox-blocked as in
  #102).
- No commit (not authorized).
