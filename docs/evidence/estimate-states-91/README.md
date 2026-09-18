# Backlog #91 — Explain unavailable erase-time estimates

## Baseline (before implementation)

Source identity: `60d827a` on branch `feat/improve-screen-hierarchy`,
plus uncommitted #83–#90 WIP (all preserved).

Reproduce: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest`

Result: **2 failed, 2718 passed, 527 skipped** (total 3247). Both
failures environmental and unrelated (headless-Chrome SIGABRT;
sandbox unix-socket denial in test_usb_lab).

Correction note: the first #91 baseline command no-oped (its
junit/log files kept their #90-baseline mtimes) and its printed
3229 total was the stale #90-baseline file, caught during final
verification by timestamp + per-file case audit. No edits
happened between #90's final green run and #91's first edit, so
#90's final counts (3247/2/527) are the valid #91 baseline,
cross-checked by exact arithmetic: 3247 + 22 new tests = 3269
observed after implementation.

Current behavior (verified by reading the code and probing):

- The estimator needs six samples over a 20-second span,
  Writing/Verifying phase only, engine ETA agreement, and the
  final operation. Any unmet gate yields silence: no
  time-remaining line at all, with no explanation.
- New samples during retry/sync, phase/counter changes, stalls,
  regressions, and missing engine ETAs all clear the sample
  history, silently returning to the same blank state.
- After the engine exits, the WORKING screen shows phase
  "Finalizing" with no estimate and no explanation until DONE.
- Evidence saving/retry states on DONE already explain
  themselves (`EVIDENCE_SAVING`, retry lines).

Note: the baseline suite ran before the first #91 edit, and the
criteria below were fixed during pre-implementation inspection
(the fail-first test run below predates all implementation
edits). This file was written up at the end of the task.

## Acceptance criteria (measurable)

1. Every unmet estimate gate renders an explicit state in the
   stable time-remaining slot: early/short-span, non-final
   step, retrying, syncing, stalled, missing engine ETA,
   disagreeing reports, finished step awaiting result.
2. A live estimate still renders unchanged when all gates pass;
   the estimate computation itself is untouched.
3. Stale step data, regressions, and resume-after-stall behave
   sanely (pause, rebuild, restore) with no manufactured
   numbers and no per-tick state flapping.
4. Terminal views (stopping, finalizing, result, recovered)
   suppress the state line exactly like the estimate.
5. EN/FR/DE in all renderers; console stays within 80 columns;
   suite green apart from the 2 pre-existing environmental
   failures.

## Intentional differences

- The estimate computation itself is untouched (six samples,
  20-second span, Writing/Verifying only, engine agreement,
  final operation). Only the previously silent absence gains an
  explanation.
- Terminal views (stopping, finalizing, result, recovered)
  suppress the state line exactly like the estimate: those
  states carry their own text (stop/finalizing notes, DONE
  screens).
- Near-impossible fallthrough (non-retry/non-sync phase with
  otherwise perfect data) stays silent, matching previous
  behavior; every reachable path names a state.
- FR/DE state texts are phrased as continuations of the
  "time remaining" label to avoid noun doubling; EN keeps the
  task's example wordings.
- The gallery click-through and helper are unchanged: neither
  has a live estimator to explain. Preview (`DryRunRunner`)
  synthesizes a shrinking ETA so it demonstrates early,
  last-step, and live-estimate states.
- `docs/screens.md` Working row documents the estimator states.

## Implementation (final state)

- `progress.py`: 8 `ESTIMATE_*` states; `ProgressView` gains
  `estimate_state`, rendered in the stable time-remaining slot;
  `ProgressTiming._estimate_state()` names the first unmet gate
  (retrying > syncing > stalled > no engine ETA > early/short
  span > non-final step > finished step > disagreeing reports).
- `wizard.py`: `progress_view` passes the state through, cleared
  on terminal views.
- `nwipe_runner.py`: synthetic observations carry a shrinking
  ETA (`max(1, duration * (1 - frac))`) so preview exercises the
  estimator.
- 8 new `progress` strings in EN + FR + DE; language
  parity/stopword/placeholder suites green.

## Verification evidence (final pass)

Reproduce: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest`

Result: **2 failed, 2740 passed, 527 skipped** (total 3269 =
baseline 3247 + 22 new `test_estimator_states.py` tests; all
green; fail-first confirmed by 20 pre-implementation failures).
Both failures are the pre-existing environmental pair
(headless-Chrome SIGABRT; sandbox socket denial), unrelated.

- New coverage: early/insufficient-span, non-final step,
  retrying, syncing, stall-pause, missing engine ETA, unsteady
  rate, engine disagreement, final-100 and midplan-100,
  regression back to estimating, stall-resume rebuild and
  restore, no-flap repeats, hand-built default, fresh/retry
  working views, finalizing/stopping suppression, FR/DE states,
  preview mid/late segment walk.
- Gates: `compileall`, ruff security-select on src + tests, and
  `./preview --web/--console/--helper` all pass; locale files
  format-clean; staged chroot re-synced (19/19 live-image tests
  green).
- Manual renders: early/retry/sync states x EN/FR/DE inspected;
  all 8 German state lines wrap within 80 columns (worst
  segment 77 chars).

## Honest limits

- No live nwipe run: states are validated against fake SIGUSR1
  lines shaped from real-sample tests, plus preview synthesis.
  Real-engine validation needs the x86 VM gate.
- Tk pulse-label growth (one ETA line always present now) is
  covered by CI Tk clipping suites, which skip on this
  display-less Mac.
- ISO/QEMU gates unavailable here per project guide.
- FR/DE state wording is first-draft without native-speaker
  review (same standing limit as #87).
- Uncommitted: #91 work on top of #83–#90 WIP on
  `feat/improve-screen-hierarchy`; no commit (not authorized).
