# Backlog #97 — Explain post-erase computer behavior

RISK (honest): FR/DE wording is first-draft, written without
native-speaker review (same standing risk as #87–#95).
Recommend native review before any release.

## Baseline (before implementation)

Source identity: `60d827a` (origin/main) on branch
`feat/improve-screen-hierarchy`, plus uncommitted #87–#95 WIP
(all preserved untouched).

Reproduce: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest`

Result at #95 close: **2 failed, 2787 passed, 540 skipped**
(headless Chrome SIGABRT + sandbox socket denial, both
pre-existing environmental).

Guidance baseline (verified by reading the code):

- No Done screen explains post-erase boot behavior. The
  closest text is `AFTERCARE_SUCCESS` ("Putting an
  operating system back on is a separate task."), shown
  only inside the verified/unverified next-step.
- The helper's "What this USB does" card warns pre-erase
  ("If that disk holds an operating system, erasing it
  also removes Windows or Linux..."), but nothing covers
  the post-erase "computer does not start" moment.
- Reports need no change: RESULT.txt is golden-pinned per
  outcome with a stable labeled layout; README already
  leads with the announcement; the next-step (with
  aftercare for completions) travels in "Limitations:".
- The gallery done card shows only preview results (code
  "preview": nothing was erased), so guidance must stay
  off that card; it also carries a #95 leftover duplicate
  (`<h1>` plus body rendering the same message).

## Design decisions (recorded before implementation)

- One conditional, non-alarming, role-neutral sentence set
  (`POST_ERASE_BOOT`): "If this was the disk your computer
  starts from, the computer may not start normally now. To
  use that computer again, you may need to install an
  operating system first." Never claims the OS disk was
  erased; never says "will not start".
- Shown unless the outcome proves nothing was erased:
  hidden for `preview`, `start_failed`, `occupied`,
  `open_failed`, `geometry_unusable`; shown for every
  other code including failures, interruptions, and
  unknown codes (conditional "may" stays honest there).
  Implemented as `outcomes.may_have_erased(code)` over a
  module-level set — not a `ResultView` field — so
  evidence JSON and gallery payloads are untouched.
- Uniform across internal/external/unknown targets: no
  branching on bus or kind (branching would guess disk
  role). Placement is always after the outcome next-step,
  before report content; styled informational, never a
  warning panel.
- Helper gains an "If the computer does not start after
  erasing" card in EN/FR/DE (the offline panic-moment
  surface, readable from any computer via the USB).

## Acceptance criteria (measurable)

1. `may_have_erased` is False exactly for the five
   nothing-erased codes and True for every other `VIEWS`
   code plus unknown codes.
2. Tk Done shows the note for verified/engine_failed/
   cancelled and hides it for open_failed (CI).
3. Curses + plain Done show the note for verified/
   unverified/engine_failed/cancelled/interrupted and
   hide it for start_failed/occupied/open_failed/
   geometry_unusable (local).
4. Internal (SATA), external (USB), and unknown ("")
   bus targets all show the note (local).
5. Copy discipline: EN note contains "If" + "may not
   start"; contains no "will not", no OS-erased claim,
   no forbidden-claims phrase; FR/DE parity exact.
6. Accessible Done announces the note after next-step
   for shown codes and omits it for hidden codes (CI).
7. Gallery done card omits the note (preview results),
   keeps `aria-labelledby`, and no longer duplicates
   the message (local).
8. Helper EN/FR/DE each gain the after-erasing card
   with conditional language, no forbidden phrases,
   valid heading order, self-contained (local text
   tests; pixels in CI).
9. `docs/screens.md` Finished row documents the note.
10. Full gates pass apart from pre-existing
    environmental failures.

## Implementation

- `src/beamo_wipe/outcomes.py`: `NOTHING_ERASED_CODES`
  (`preview`, `start_failed`, `occupied`, `open_failed`,
  `geometry_unusable`) + `may_have_erased(code)` (unknown
  codes show guidance). Module-level, so evidence JSON
  and gallery payloads are untouched.
- `src/beamo_wipe/copy.py` + FR/DE tables: new
  `POST_ERASE_BOOT` conditional note (first-draft
  translations).
- Tk, curses, plain, and accessible Done render the note
  after the next-step when `may_have_erased`, styled
  informational (muted/small, never a warning panel).
- Gallery: no note (done cards show preview results
  only, which prove nothing erased); removed the #95
  leftover duplicate message line.
- Helper EN/FR/DE: new `after-erasing` card ("If the
  computer does not start after erasing") with
  conditional, role-neutral guidance for both OS-disk
  and extra-drive cases.
- `docs/screens.md` Finished row documents the note.
- Reports deliberately unchanged (golden-pinned stable
  format; README already leads with the announcement;
  aftercare already travels in "Limitations:").

## Verification

- New `tests/test_post_erase_boot.py` (8 tests, all
  local): all 8 failed before the fix. Covers the exact
  code mapping, copy discipline (conditional tokens,
  no role guesses, forbidden phrases), translated
  markers, curses/plain show/hide across outcomes with
  80x24 fit, SATA/USB/unknown bus uniformity, gallery
  omission + de-duplication, helper cards in 3
  languages (ids, headings, order, phrases).
- New Tk + accessible runtime tests (CI): note shown
  for verified/engine_failed/cancelled with
  message-note-report order and no clipping; hidden
  for open_failed; accessible announcement parity.
- Full suite: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest`
  → **2 failed, 2795 passed, 548 skipped** (93s). The 2
  failures are the documented pre-existing environmental
  ones (headless Chrome SIGABRT exit -6, sandbox socket
  `PermissionError`). Ignored ISO/chroot staging
  re-synced (helper copies + package tree).
- Hosted lint commands pass (ruff check + format on
  gated paths, security-select ruff on `src/beamo_wipe`);
  new files ruff-clean and formatted; whole-package
  mypy shows the same 22 pre-existing advisory errors.
- Preview gates pass (`--web`, `--console`, `--helper`);
  verified plain Done rendered with the note placed
  after next-step, before report status (see record).
- Skipped environments (honest limits): Tk/accessible
  runtime, ISO build, QEMU wipe, Orca voice, helper
  pixels, and live nwipe need CI
  (`./scripts/ci-cloud.sh`, project `beamo-wipe`) or an
  isolated x86_64 VM — not run here. No commit made
  (awaiting authorization).
