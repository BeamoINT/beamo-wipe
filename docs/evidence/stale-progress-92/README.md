# Backlog #92 — Make stale progress actionable and honest

RISK (honest): FR/DE safety wording is first-draft, written
without native-speaker review (same standing risk as #87–#91).
Recommend native review before any release.

## Baseline (before implementation)

Source identity: `60d827a` (origin/main) on branch
`feat/improve-screen-hierarchy`, plus uncommitted #87–#91 WIP
(all preserved untouched).

Reproduce: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest`

Result at #91 close: **2 failed, 2740 passed, 527 skipped**
(Tk clipping under Mac retina only; `xvfb`/CI-expected).

Stale-progress baseline (verified by reading the code):

- `ProgressTiming.view` (`src/beamo_wipe/progress.py`) sets
  `stale_for` when no engine data ever arrived and elapsed ≥
  `FIRST_UPDATE_GRACE_S` (20s), or when the last data is older
  than `STALE_PROGRESS_S` (10s). Invalid clocks yield no
  staleness claim.
- Rendered stale output today is only the `(old)` percent
  marker plus `No new progress update for {duration}.`
  Nothing explains that a stale percentage does not prove the
  erase stopped, and no safe next steps are given.
- `wizard.progress_view` already nulls `stale_for` for terminal
  states (stopping / finalizing / result / recovered), so any
  stale explainer composed on `stale_for is not None` is
  automatically suppressed at process exit and cancellation.

## Acceptance criteria (measurable)

1. A stale view (`stale_for is not None`, non-terminal) shows,
   in order: the existing duration line, a meaning line ("a
   quiet screen does not mean the erase stopped"), and a
   safe-next-steps line (keep USB in, keep wall power, do not
   turn off, `Stop erase` available) — in EN/FR/DE.
2. Fresh views (`stale_for is None`) contain none of the three
   stale lines.
3. Threshold transitions are exact: 19.9s without data is
   fresh, 20.0s is stale; a 10.0s data gap is fresh, older is
   stale.
4. Resumed engine output clears all three stale lines.
5. An invalid (non-monotonic) clock shows no staleness claim
   and no duration.
6. Stale during a retry shows both the stale block and the
   retry note without contradiction.
7. Stopping, finalizing, finished, and cancelled views show
   none of the three stale lines.
8. The stale block contains no restart / reboot / unplug /
   replug / start-over / retry-the-wipe recommendation in any
   language (token blocklists, EN/FR/DE), and keeps the USB +
   power + `Stop erase` guidance.
9. Messaging is bounded: 50 consecutive stale renders keep
   exactly one copy of each stale line per render.
10. Tk pulse, console pulse + line-printer, accessible label,
    gallery, docs (`docs/screens.md`), and this note stay
    aligned; full gates pass apart from pre-existing
    environmental failures.

## Implementation

- `src/beamo_wipe/progress.py`: new `STALE_MEANING` ("A quiet
  screen does not mean the erase stopped.") and `STALE_NEXT`
  (keep USB in + wall power, do not turn off, `"Stop erase"`
  control named exactly) constants plus `stale_block()`,
  composed in `ProgressView.timing_text` so Tk, console
  (pulse + line-printer), accessible, and gallery renderers
  inherit it. Shown only when `stale_for is not None`, which
  the wizard already nulls for stopping / finalizing /
  result / recovered states. `silence_text()` kept unchanged.
- `src/beamo_wipe/locales/fr.py`, `de.py`: both keys
  translated (first-draft, needs native review).
- `docs/screens.md`: Working row documents the stale block
  and the never-recommend list.
- Adjacent safety-gate repair: `scripts/ci-hosted.sh`
  negative-test patch pattern updated for the #87
  `_copy.IDENTIFY_ERROR` reference (the stock pattern no
  longer matched the tree, so the hosted negative gate would
  have errored instead of testing).
- Staged chroot copies (ignored build output) re-synced for
  `test_staged_chroot_package_matches_src`.
- Offline helper: no change (boot-menu only, no progress
  surface) — intentional difference, documented here.

## Verification

- New `tests/test_stale_progress.py` (12 tests) failed
  before the fix (ImportError on `STALE_MEANING`) and passes
  after: content/order, grace (19.9/20.0s) and gap
  (10.0/>10s) boundaries, resume, backward clock,
  stale+retry composition, EN/FR/DE unsafe-token blocklists,
  50-render boundedness, stopping/finalizing/done
  suppression at wizard level.
- Renderer alignment: console stale test passes locally
  (80x24 fits); Tk (`test_tk_runtime.py`) and accessible
  (`test_accessible_runtime.py`, needs `gi`) additions are
  CI-covered (skip locally).
- Full suite: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest` →
  **2 failed, 2753 passed, 527 skipped** (85s). The 2
  failures are the documented pre-existing environmental
  ones: headless Chrome SIGABRT (exit -6) in
  `test_helper_boot_guidance`, sandbox socket
  `PermissionError` in `test_usb_lab`. No other failures.
- Hosted lint commands pass locally (ruff check + format on
  gated paths, security-select ruff on `src/beamo_wipe`,
  shellcheck on `ci-hosted.sh`); mypy advisory clean on
  `progress.py` (1 pre-existing error in untouched
  `inventory.py`); new test file ruff-formatted.
- Preview gates pass: `./preview --web` (writes
  `web-preview/index.html`), `./preview --console`,
  `./preview --helper`.
- Negative gate verified manually (stock script needs
  `apt-get`, absent on this Mac): fail-open patch → e2e
  safety test FAILS as required; restored tree → passes.
  `safety.py` left byte-identical; backup removed.
- Rendered EN/FR/DE stale blocks captured from
  `ProgressView.status_text` (see task record); FR/DE
  control names match translated `STOP_ASK` exactly.
- Skipped environments (honest limits): Tk clipping on
  real display, ISO build, QEMU wipe, Orca voice, and live
  nwipe need CI (`./scripts/ci-cloud.sh`, project
  `beamo-wipe`) or an isolated x86_64 VM — not run here,
  no authorization claimed. No commit made (awaiting
  authorization).
