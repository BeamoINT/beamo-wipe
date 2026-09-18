# Backlog #90 — Distinguish write progress from final completion

## Baseline (before implementation)

Source identity: `60d827a` on branch `feat/improve-screen-hierarchy`,
plus uncommitted #83–#89 WIP (all preserved).

Reproduce: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest`

Result: **2 failed, 2691 passed, 527 skipped** (total 3229). Both
failures environmental and unrelated (headless-Chrome SIGABRT;
sandbox unix-socket denial in test_usb_lab).

Current behavior (verified by reading the code and probing):

- The engine reports 100% at the end of each overwrite pass on
  multi-pass methods. `NwipeRunner` caps working progress at 99.9
  and holds it monotonic, so the headline pins at **99% from the
  end of pass 1 through all later passes and verification**
  (probed: pass-1 100% -> 99.9, pass-2 30% -> 99.9). The live
  per-stage percent exists in the observation but is never shown.
- The step line (#88) names the current stage but carries no
  percent, so nothing scopes a number to its step.
- Phase labels (Writing/Verifying/Syncing/Retrying/Finalizing)
  change with no plain-language explanation of what each means
  for completion. `known_quiet` has no production use: a long
  quiet sync eventually shows the generic staleness note.
- After the engine exits, the WORKING screen shows phase
  "Finalizing" with no explanation until the DONE screen
  replaces it. Evidence saving/retry states on DONE already
  explain themselves (`EVIDENCE_SAVING`, retry lines).

## Acceptance criteria (measurable)

1. The step line carries the live step percent scoped to its
   step ("Step 2 of 4: Overwrite 2 of 3 (45% of this step)");
   an engine 100% mid-plan renders as "100% of this step" next
   to a sub-100 headline, never as overall completion.
2. Stale step percents are marked old; unknown/mismatched steps
   show no step percent.
3. Verifying, Syncing, Retrying, and Finalizing phases show a
   one-line plain-language note explaining the transition and
   that completion requires the result screen; notes are
   suppressed on mismatch and never duplicate stopping text.
4. Headline percent semantics unchanged (monotonic, capped at
   99.9 while working, 100 only on verified success); all
   methods and outcomes render; cancellation, evidence
   failure/retry, and recovery paths unchanged.
5. EN/FR/DE in all renderers; console stays within 80 columns;
   suite green apart from the 2 pre-existing environmental
   failures.

## Intentional differences

- Headline percent semantics are untouched (monotonic, 99.9 cap
  while working, 100 only on verified success). The fix scopes a
  second, live number to its step instead of recomputing the
  headline.
- Stopping takes no transition note: the stop-confirmation and
  stopping texts already explain that state.
- Writing takes no note: the step line plus sequence already
  scope it. Unknown steps show the plan without a percent.
- The gallery click-through shows the step percent (evenly
  spread, like its mock progress) but no phase notes: it has no
  live engine phases.
- Helper, boot menus, `--help`, logs, claims docs, and DONE
  outcome/evidence copy are unchanged: evidence saving and retry
  states already explain themselves.

## Implementation (final state)

- `progress.py`: `STEP_PCT` / `STEP_PCT_OLD` templates scope the
  live observation percent to its step
  ("(45% of this step)", "(last reported 45% of this step)");
  `PHASE_NOTE_*` explain Verifying/Syncing/Retrying/Finalizing
  transitions; `phase_note()` keys engine codes plus the
  translated finalizing constant and stays silent on mismatch;
  `ProgressView` gains `step_percent`, rendered in `timing_text`
  (all renderers inherit; no widget changes).
- `wizard.py`: `progress_view` feeds the observation percent only
  when the step is located and matches the plan.
- 6 new `progress` strings in EN + FR + DE; language
  parity/stopword/placeholder suites green.
- `gallery.py`: `stageStepPct` payload + segment-fraction step
  percent in the working frame.
- `docs/screens.md` Working row documents step percent and
  transition notes.

## Verification evidence (final pass)

Reproduce: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest`

Result: **2 failed, 2708 passed, 527 skipped** (total 3247 =
baseline 3229 + 18 new `test_write_vs_completion.py` tests, all
green; fail-first confirmed by 13 pre-implementation failures).
Both failures are the pre-existing environmental pair
(headless-Chrome SIGABRT; sandbox socket denial), unrelated.

- New coverage: live step percent, engine-100 step scoping with
  sub-100 headline, stale marking, unknown/mismatch suppression,
  all four transition notes, mismatch/stopping note suppression,
  all methods, FR/DE render, preview ticks, German 80-column
  wrap through the curses harness, gallery template.
- One #88 test expectation updated for the specified new step
  format (exact strings now pin the percents, stronger than
  before).
- Gates: `compileall`, ruff security-select on src + tests, and
  `./preview --web/--console/--helper` all pass; gallery JS
  passes `node --check`; staged chroot re-synced (19/19
  live-image tests green).
- Manual renders: all 6 phase cases x EN/FR/DE inspected; notes
  wrap within 80 columns on console (longest raw line 102, DE
  verify note, wrapped by `_lines`); FR/DE gallery templates
  verified with no English leaks.

## Honest limits

- No live nwipe run: step percent and notes are validated
  against fake SIGUSR1 lines shaped from real-sample tests, plus
  preview synthesis. Real-engine validation needs the x86 VM gate.
- Tk pulse-label growth (up to ~2 more lines) is covered by CI Tk
  clipping suites, which skip on this display-less Mac.
- ISO/QEMU gates unavailable here per project guide.
- FR/DE note wording is first-draft without native-speaker
  review (same standing limit as #87).
- Uncommitted: #90 work on top of #83–#89 WIP on
  `feat/improve-screen-hierarchy`; no commit (not authorized).
