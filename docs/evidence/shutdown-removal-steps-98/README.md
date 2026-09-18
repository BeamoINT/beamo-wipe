# Backlog #98 — Explicit shutdown and USB-removal steps

RISK (honest): FR/DE wording is first-draft, written without
native-speaker review (same standing risk as #87–#97).
Recommend native review before any release.

## Baseline (before implementation)

Source identity: `60d827a` on branch
`feat/improve-screen-hierarchy`, plus uncommitted #87–#97 WIP
(all preserved untouched).

Reproduce: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest`

Result at #97 close: **2 failed, 2795 passed, 548 skipped**
(headless Chrome SIGABRT + sandbox socket denial, both
pre-existing environmental).

Guidance baseline (verified by reading the code):

- Removal guidance scattered: `REPORT_HELP_REMOVE`
  (report USB timing), receipt leads (report USB
  safe-to-remove), `README_COMPLETE` (COMPLETE is not a
  removal claim), `HINT_WORKING` ("Leave this USB in until
  the result appears").
- Nothing states when the Beamo USB is safe to remove,
  restart rules, or multi-USB/changed-media rules.
- `SHUTDOWN_CONFIRM` shows only the unsaved-report loss
  paragraph; direct shutdown (no report / verified export)
  shows no screen at all.

## Design decisions (recorded before implementation)

- One shared composer, `copy.media_steps()`, with a
  shutdown variant and an erase-another
  (`stay_in_session`) variant; `wizard.exit_media_steps`
  selects by `_new_session_pending`.
- Render on `SHUTDOWN_CONFIRM` in Tk, console curses,
  plain console (+EOF path), accessible GTK, and gallery.
  Done screen untouched (crowding); direct shutdown keeps
  its documented one-step contract instead.
- Safe order: report first, stay connected, Beamo USB
  only after fully off, restart rule, unsure-media rule.

## Acceptance criteria (measurable)

1. `media_steps()` returns the five steps in safe order;
   stay-variant swaps the removal line for the
   next-erase line.
2. All renderers show the exact shared text below the
   loss text; `SHUTDOWN_LOSS` contract preserved.
3. Verified/failed/cancelled/interrupted outcomes all
   reach steps via shutdown; Working and exporting
   states keep blocking shutdown (export: WAIT message).
4. No-report path keeps direct shutdown (documented
   intentional difference).
5. Gallery payload, helper EN/FR/DE, FR/DE locale
   tables, and docs carry the same steps.

## Implementation

- `src/beamo_wipe/copy.py`: `MEDIA_STEPS_TITLE`,
  `MEDIA_STEP_REPORT/STAY/BEAMO_OFF/RESTART/UNSURE/
  ANOTHER`, `media_steps()`.
- `src/beamo_wipe/wizard.py`: `exit_media_steps`.
- `ui/tk_wizard.py`, `ui/console_wizard.py` (curses
  fixed title+loss + paged remainder, plain, EOF),
  `ui/accessible_wizard.py`, `gallery.py`.
- `locales/fr.py`, `locales/de.py`; `helper/*.html`
  `removing-usb` card; packaged `START-HERE.html` sync;
  `docs/report-shutdown.md`, `docs/screens.md`.
- Incidental: module-level `descendants()` in
  `tests/test_tk_runtime.py` (three tests used the bare
  name; F821, would NameError under a display).

Defect found and fixed during verification: German
step-5 tail clipped at 80x24. Fixed with the existing
`_paint_paged` pattern (title+loss fixed, remainder
paged, screen added to `_paged`); EN/FR still fit
without paging.

## Verification

- New `tests/test_media_removal_steps.py` (21 tests):
  16 failed before, all pass after. Tk (3) and
  accessible (4) tests added; they skip headless here
  and run under CI/Xvfb.
- Full suite: **2 failed, 2816 passed, 549 skipped** —
  the same 2 pre-existing environmental failures
  (Chrome failure re-verified identical on pristine
  HEAD via worktree).
- Blocking ruff selections pass (src + tests);
  shellcheck clean; gallery JS passes `node --check`;
  mypy advisory unchanged (22 pre-existing errors).
- 80x24 EN layout eyeballed (all steps + footer fit);
  DE paging verified (more-below hint, scroll reveals
  tail, title stays fixed).
- Ignored staged-chroot tree re-synced from working
  src (builder copies tracked-only; `locales/` is new
  untracked work, so a full-tree sync was needed for
  the drift test).
- No commit (not authorized).
