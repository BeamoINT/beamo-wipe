# Backlog #95 — Make the specific erase outcome the main heading

RISK (honest): FR/DE wording is first-draft, written without
native-speaker review (same standing risk as #87–#93).
Recommend native review before any release.

## Baseline (before implementation)

Source identity: `60d827a` (origin/main) on branch
`feat/improve-screen-hierarchy`, plus uncommitted #87–#93 WIP
(all preserved untouched).

Reproduce: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest`

Result at #93 close: **2 failed, 2780 passed, 531 skipped**
(headless Chrome SIGABRT + sandbox socket denial, both
pre-existing environmental).

Heading baseline (verified by reading the code):

- Tk `_done`: H1 is generic `ERASE_STATUS_TITLE`
  ("Erase status"); the specific `result.message` renders
  below in smaller bold body text.
- Console (curses + plain) Done: first line is
  "Erase status"; the message follows second or later.
- Accessible Done: a generic "Erase status" heading is
  ordered before the announcement heading.
- Gallery done card: `<h1>` is `eraseStatusTitle`;
  message is body text.
- Tk step rail and gallery step map carry
  `TITLE_DONE_OK` ("Finished") for Done, but that title
  element is never rendered by either chrome (both use
  journey label + "Step 8 of 8"); header shows neutral
  "Result · Step 8 of 8".
- `HINT_WORKING` tells the owner to wait "until you see
  Finished", which will no longer match the main heading.
- Reports already comply: README leads with the
  announcement; RESULT.txt has a "Beamo Wipe result"
  document title plus a specific "Result:" field.

## Reconciliation with #96 (recorded before implementation)

#96 (merged) requires erase/report separation and pins the
"Erase status" label in several presentation tests. #95
explicitly replaces the generic heading with the specific
outcome, so the presentation pins must move to the new
hierarchy — this is a justified expectation change, not a
weakening: separation, tone/copy independence, receipt
checks, and report-specific language are all preserved and
re-asserted. The generic label is removed uniformly (it is
redundant once the outcome heads the section); no eyebrow
is kept, in any renderer, because size-less surfaces
(console, screen-reader order) cannot demote without
deleting, and uniformity beats per-renderer idiom here.

Kept as-is with rationale: the dead step-title map entries
(no rendered effect; churning them adds risk without user
value), the RESULT.txt layout (document title plus
specific field; stable labeled format), and the helper
(boot guidance, no outcome surface).

## Acceptance criteria (measurable)

1. Every `VIEWS` code has a unique message, a tone in
   {ok, warn, danger} with an icon, and
   `announcement == message + next_step`.
2. Tk Done H1 text equals `result.message` (verified,
   unverified, cancelled, engine_failed, preview);
   "Erase status" is absent; the report title renders
   below; the message label uses the heading font.
3. Curses Done first content line equals the message;
   no "Erase status" line; Report status follows.
4. Plain Done first print equals the message; message
   precedes Report status; "Erase status" is absent.
5. Accessible Done first heading in document order is
   the announcement; headings include it plus Report
   status; "Erase status" is absent from headings.
6. Gallery done H1 equals the message; the section
   stays `aria-labelledby` to that H1.
7. RESULT.txt `Result:` equals the message for every
   code; README first line is the announcement; neither
   file claims generic "Finished"/"Erase status".
8. Failure detail + no conflation: failed outcomes show
   message plus next-step/support detail with a distinct
   report headline; #96 tone/copy independence suites
   stay green.
9. `HINT_WORKING` no longer references "Finished" in
   EN/FR/DE; FR/DE parity exact after deleting
   `ERASE_STATUS_TITLE` from all three tables.
10. Long text: the longest DE message fits (curses
    80-column suite locally, Tk clipping in CI).
11. Full gates pass apart from pre-existing
    environmental failures.

## Implementation

- Tk `_done`: H1 is now `result.message` (heading font,
  wraps); the smaller duplicate message line is removed.
- Console curses Done: first content line is the message;
  generic title line removed. Plain Done: first print is
  the message; later duplicate removed.
- Accessible Done: the generic pre-heading widget is
  removed; the announcement heading is first with role,
  description, and report heading unchanged.
- Gallery done card: `<h1 id="erase-status-heading">`
  renders `${result.message}`; the section keeps its
  `aria-labelledby`; dead `eraseStatusTitle` payload key
  removed.
- `copy.ERASE_STATUS_TITLE` deleted from EN/FR/DE
  (parity suite green); `HINT_WORKING` reworded to
  "Leave this USB in until the result appears." in
  EN/FR/DE since "Finished" is no longer the heading.
- `docs/screens.md` Finished row rewritten for
  outcome-as-heading with report separation kept.
- Reports unchanged (README already leads with the
  announcement; RESULT.txt keeps its stable labeled
  layout with a specific Result field); helper
  unchanged; dead step-title map entries untouched.
- #96 pins revised with justification comments:
  console order (message before Report status), gallery
  H1 template, accessible headings set, Tk labels,
  docs-row text, hierarchy source inspection. #96
  separation, tone/copy independence, and receipt
  checks are untouched and green.

## Verification

- New `tests/test_outcome_heading.py` (7 tests, all
  local): 3 failed before the fix (curses, plain,
  gallery); mapping/report/detail tests pin unchanged
  truth. Covers every `VIEWS` code for uniqueness,
  tone, and announcement shape; RESULT.txt/README for
  every presentation case; failure detail separation.
- New Tk tests (2, CI): H1 equals the message for
  verified/unverified/cancelled/engine_failed with
  heading-font size, generic absent, report below, no
  clipping; longest-DE-message MIN_WINDOW no-clip.
- New accessible test (1, CI): announcement is the
  first heading in document order; generic absent from
  headings; report heading present.
- Full suite: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest`
  → **2 failed, 2787 passed, 540 skipped** (89s). The 2
  failures are the documented pre-existing environmental
  ones (headless Chrome SIGABRT exit -6, sandbox socket
  `PermissionError`).
- Hosted lint commands pass (ruff check + format on
  gated paths, security-select ruff on `src/beamo_wipe`);
  default ruff on touched files shows only the 2
  pre-existing copy.py E402s; whole-package mypy shows
  the same 22 pre-existing advisory errors; gallery
  inline JS passes `node --check`.
- Preview gates pass (`--web` writes
  `web-preview/index.html` containing the new H1,
  `--console`, `--helper`); plain Done rendered in
  EN/FR/DE with the message leading (see task record).
- Staged chroot copies (ignored build output) re-synced.
- Skipped environments (honest limits): Tk/accessible
  runtime, ISO build, QEMU wipe, Orca voice, and live
  nwipe need CI (`./scripts/ci-cloud.sh`, project
  `beamo-wipe`) or an isolated x86_64 VM — not run here.
  No commit made (awaiting authorization).
