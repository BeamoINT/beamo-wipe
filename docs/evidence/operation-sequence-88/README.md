# Backlog #88 — Show the complete erase operation sequence

## Baseline (before implementation)

Source identity: `60d827a` on branch `feat/improve-screen-hierarchy`,
plus uncommitted #83/#84/#85/#86/#87 WIP (all preserved).

Reproduce: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest`

Result: **2 failed, 2668 passed, 524 skipped** (total 3194). Both
failures environmental and unrelated (headless-Chrome SIGABRT;
sandbox unix-socket denial in test_usb_lab).

Current behavior (verified by reading the code):

- Working screens (Tk, console line-printer + curses, accessible)
  show integer percent (never 100 early) plus `timing_text`: phase
  display name, elapsed, optional remaining estimate, staleness
  note. No step/stage sequence exists anywhere.
- Engine SIGUSR1 `round i of n, pass i of n` counters are parsed
  into `Observation.counters` but only used for the remaining-time
  `final_operation` gate and completion proof. Never displayed.
- Preview (`DryRunRunner`) emits percent only, no observation, so
  preview shows "Phase not reported" plus a moving percent.
- Method plans (`docs/ADVANCED.md`): Everyday = 1 overwrite + 1
  read-back verify; Three overwrites = 3 overwrites + 1 verify;
  Quick zero = 1 overwrite, no verify. `operation_summary` already
  states these counts on the last-chance screen and in reports.
- During verify the engine holds pass counters at the last
  overwrite (`pass 3 of 3, [verifying]` per test samples).

## Acceptance criteria (measurable)

1. The full planned stage list derives from the actual
   `NwipeMethodSpec` (overwrite_passes + verify on/off): Everyday
   2 stages, Three-overwrites 4 stages, Quick-zero 1 stage.
2. The working screen in every renderer (Tk, console,
   accessible, gallery) shows all planned stages plus the current
   stage (e.g. "Step 2 of 4: Overwrite 2 of 3"), in EN/FR/DE.
3. Current stage derives from live observation (phase + pass
   counters) cross-checked against the plan; engine/plan mismatch,
   missing counters, and unknown progress render explicit
   uncertainty text, never a guessed stage.
4. No-verify plans omit the verify stage; verify-phase
   observations under a no-verify plan render as mismatch, not as
   a verify step.
5. Retrying/Syncing observations keep their phase label and the
   located stage; failures and stop states never claim a
   completed or current stage beyond the last located one.
6. Screen-reader/accessible text updates on stage transitions
   (no per-tick announcement storms beyond existing percent
   quantization); typed tokens, confirmation rules, percents,
   timing, evidence schema, and disk-safety boundaries unchanged.
7. Preview shows a moving sequence from synthetic DryRun
   observations; gallery shows the planned sequence; helper and
   `docs/screens.md` aligned; suite green apart from the 2
   pre-existing environmental failures.

## Intentional differences

- Stage block rides inside `timing_text`, so Tk, console
  (line-printer + curses), accessible, and the stopping screen all
  show it with zero renderer edits; no new widgets, no layout
  restructuring.
- `verify="all"` (allowed but used by no shipped method) plans a
  single unnumbered verify entry, matching `operation_summary`;
  verify stages are never numbered because engine counters freeze
  at the last overwrite during verify.
- Preview synthesis (`DryRunRunner`) spreads stages evenly over
  elapsed time; it demonstrates the UI, not real engine timing.
- Boot menus, `--help`, logs, helper pages, and claims docs are
  untouched: the helper covers boot menus only and never shows
  wipe progress.

## Implementation (final state)

- `progress.py`: `Stage`, `plan_stages` (from overwrite/verify
  counts), `stage_label`, `locate_stage` (phase + pass counters
  cross-checked against the plan; mismatch/unknown explicit, never
  guessed), `sequence_text` (`(done)`/`(now)` markers), `step_text`
  ("Step k of total: …"); `ProgressView` gains
  `stages`/`position`/`mismatch`, rendered in `timing_text`.
- `wizard.py`: `progress_view` derives the plan from the live
  method spec and locates the runner observation; stopping/
  finalizing keep the last located stage.
- `nwipe_runner.py`: `DryRunRunner(synthesize_stages=…)` emits
  plan-shaped synthetic observations; default off (all existing
  tests unaffected); enabled in `./preview` paths (`app.py`,
  `demo.py` via `make_demo_wizard`).
- `gallery.py`: methods payload carries `stages` + step templates;
  the working frame renders the list with the current step from
  `demoPct` (also honors `#s=working&pct=N` deep links).
- 7 new `progress` strings in EN + FR + DE (`STAGE_*`); language
  parity/stopword/placeholder suites green.
- `docs/screens.md` Working row documents the sequence display.

## Verification evidence (final pass)

Reproduce: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest`

Result: **2 failed, 2690 passed, 524 skipped** (total 3216 =
baseline 3194 + 22 new `test_operation_sequence.py` tests, all
green; fail-first confirmed by collection ImportError before
implementation). Both failures are the pre-existing environmental
pair (headless-Chrome SIGABRT; sandbox socket denial), unrelated.

- New coverage: plan derivation per method, overwrite/verify
  location, no-verify mismatch, counter/round disagreement,
  missing counters, unknown, retry-keeps-stage, done/now/todo
  markers, stopping keeps stage, failed runs claim no live
  stage, stage-driven announcement change, FR/DE render, DryRun
  synthesis walk + silent default, preview tick end-to-end,
  gallery payload.
- Gates: `compileall`, ruff security-select on src + tests, and
  `./preview --web/--console/--helper` all pass; gallery JS
  passes `node --check`; staged chroot re-synced (19/19
  live-image tests green).
- Manual renders: all 3 methods x EN/FR/DE status text inspected;
  longest line 50 chars (80-column safe); FR/DE gallery payloads
  verified in escaped form with no English leaks.

## Honest limits

- No live nwipe run: stage location is validated against fake
  SIGUSR1 lines shaped from real-sample tests, plus preview
  synthesis. Real-engine validation needs the x86 VM gate.
- Tk working-card growth (up to ~8 small-text lines for
  three-overwrites) is covered by CI Tk clipping suites, which
  skip on this display-less Mac.
- ISO/QEMU gates unavailable here per project guide.
- FR/DE stage wording is first-draft without native-speaker
  review (same standing limit as #87).
- Uncommitted: #88 work on top of #83–#87 WIP on
  `feat/improve-screen-hierarchy`; no commit (not authorized).
