# Backlog #100 — Guide report export through explicit stages

RISK (honest): FR/DE wording is first-draft, written without
native-speaker review (same standing risk as #87–#99).
Recommend native review before any release.

## Baseline (before implementation)

Source identity: `60d827a` on branch
`feat/improve-screen-hierarchy`, plus uncommitted #87–#99 WIP
(all preserved untouched).

Reproduce: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest`

Result at #99 close: **2 failed, 2832 passed, 553 skipped**
(headless Chrome SIGABRT + sandbox socket denial, both
pre-existing environmental).

Guidance baseline (verified by reading the code):

- `report_aftercare()` (shared by Tk, console curses,
  plain console, accessible) emits long paragraphs:
  `REPORT_INSERT` (idle), receipt record (saved), precise
  error + volatile note otherwise.
- `export_to_new_usb` is one blocking call with no
  UI-observable intermediate progress (serial markers
  are QEMU diagnostics only). UI-observable states are
  idle/saving/saved/error.
- Retry needs no re-insertion: each attempt re-scans
  against the wipe-time baseline, so a still-plugged USB
  from a failed attempt stays "new".
- Console DONE clips aftercare silently past `y_max`;
  elapsed/notice/alerts page below it ("read aftercare").

## Design decisions (recorded before implementation)

- Rework `report_aftercare` (same signature) to emit the
  numbered 5-stage list with done/now marks (reusing
  translated `progress` marks) plus one current-step
  line. All four renderers inherit stages unchanged.
- Honest middle: check/save/verify run inside one
  unobservable call, so while saving all three read as
  current together (documented in the composer).
- Errors stay stage-free: the pinned never-promise
  contract forbids "Insert" on failure, and failure
  text already locates the fault precisely. Retry
  guidance added (still-plugged → Save again).
- Saved keeps the receipt record verbatim after the
  stages (equality contract deliberately evolved to
  exact prefix+record form).
- `REPORT_INSERT` reused verbatim as idle guidance:
  zero information loss, translations already shipped.
- Console DONE merges aftercare into the existing paged
  tail (identical pixels when everything fits; nothing
  silently clipped when it does not).
- New "Saving in stages" help section (7th): pre-erase
  orientation + the gallery's visible stages surface
  (gallery done card is preview-locked, like Tk
  preview). Diagnostic Prepare/Save flow untouched
  (intentional: separate two-step UI already).

## Acceptance criteria (measurable)

1. Five numbered stages; marks idle (1 now), saving
   (1 done, 2–4 now), saved (1–4 done, 5 now).
2. Aftercare per state incl. verbatim receipt/errors,
   volatile note, retry guidance, no promises on error.
3. Console DONE pages the full block at 80x24 and
   24x60 with row bounds held; first frame fits stages
   + insert guidance at 80x24.
4. Back/cancel/retry: retry via Save again; shutdown
   refused while saving (existing gate, pinned in #98);
   diagnostic Back untouched.
5. Gallery payload/card, helper EN/FR/DE
   `saving-report` card, FR/DE parity, docs updated.

## Implementation

- `copy.py`: `EXPORT_STAGE_*`, `EXPORT_STAGES`,
  `EXPORT_GUIDE_WORKING/RETRY`, `export_stage_lines()`,
  reworked `report_aftercare`, `REPORT_HELP_STAGES`,
  `_apply_language` rebuild of `EXPORT_STAGES`.
- `ui/console_wizard.py`: DONE aftercare merged into
  paged tail.
- `locales/fr.py`, `locales/de.py` (8 keys each);
  `helper/*.html` + `START-HERE.html` sync;
  `docs/screens.md` Finished row.
- Deliberate test evolutions (task-required, intent
  preserved or strengthened): saved-aftercare equality
  → exact stages+record form; idle startswith → stages
  + INSERT + volatile containment; 80x24 receipt wrap
  → first-frame stages + paged receipt reachability;
  help headings 6 → 7.

## Verification

- New `tests/test_export_stages.py` (21 tests): 18
  failed before, all pass after. Tk (4 states) and
  accessible (4 states) tests added; they skip
  headless here and run under CI/Xvfb — including
  no-clipping asserts for the taller Done panel at
  1024x740 (unproven on this Mac; short windows
  scroll by architecture).
- Full suite: **2 failed, 2853 passed, 557 skipped** —
  the same 2 pre-existing environmental failures.
- Blocking ruff selections pass (src + tests); new
  file clean under full ruff; shellcheck clean; mypy
  advisory unchanged (22 pre-existing errors).
- 80x24 DONE eyeballed (stages + guidance fit first
  frame; paging hint for the rest); 24x60 reachability
  committed; FR stage render spot-checked.
- Ignored staged-chroot tree re-synced (4 files).
- ISO/QEMU, live nwipe, audible/AT-SPI checks remain
  CI/VM-only, unproven on this Mac.
- No commit (not authorized).
