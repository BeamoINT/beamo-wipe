# Slow and unusual interaction scenarios — #113

## Baseline (before implementation)

- Repo: `beamo-wipe`
- Starting `main`: `4c26217` — `fix: gallery HTML-escape pin matches boot-card serial rendering`
- Branch: `feat/slow-unusual-interactions` (independent from current main)
- Inspection: `src/beamo_wipe/ui/tk_wizard.py`, `src/beamo_wipe/progress.py`,
  `src/beamo_wipe/support_export.py`, plus wizard/console/gallery/copy paths
  that share the same contracts.
- No real disk is used. Fakes only: demo/lsblk fixtures, `DryRunRunner` /
  held runners, injected clocks, event barriers, Tk/console stubs.

Existing coverage of these interactions is **scattered and incomplete**:

| Scenario | What already exists | Original gap |
| --- | --- | --- |
| Slow discovery | Startup stages + Tk refresh stub (`test_startup_stages`, `test_refresh_scan_flow`) | No cohesive responsiveness + stale-seq + focus contract for this card |
| Delayed progress | `ProgressTiming` unit tests; Tk paints a **mocked** `ProgressView` | Wizard clock → view → native Tk/console loop not assembled as one fake |
| Long identifiers | `_soft_break_tokens` + unicode wrap tests | Not joined to confirm-token / help-return / many-disk stress |
| Many disks | Console 18-disk paging; Tk scroll test **skips** when the demo list fits | Native Tk never **forces** an overflowing list, so KB-08 can skip |
| Failed exports | Report/evidence recovery suites | Bounded evidence retries + one-at-a-time export + visible failure not in this interaction set |
| Changed media | Refresh + checking-claim identity tests | Not combined with slow I/O, key-repeat, or help return |
| Repeated keys | Confirm-gate and some Tk Return-hold tests | Not asserted across help return / refresh / export |
| Return from help | Disk-help model + Tk reader smoke | Focus after return and held-Enter after help not asserted together |

Gallery (`./preview --web`) is a static click-through. It does **not** simulate
slow discovery, delayed engine pulses, key-repeat, failed USB export, or
mid-flow media changes. That difference is intentional; native Tk and console
own those contracts.

## Measurable acceptance

#113 is done when **all** of the following hold, using only deterministic fakes:

1. Slow discovery (startup splash and Check-disks-again) keeps the UI thread
   pumping; a second scan/start is refused; a stale sequence is dropped;
   Escape cannot restore a previous selection while the scan owns the screen.
2. Delayed / missing progress marks the last percentage **old**, shows
   `No new progress update for …`, does not animate as live data, does not
   cancel the engine, and does not skip the 5 s display throttle / stale
   window. Tk `_tick` keeps scheduling.
3. Long model/serial/path tokens wrap; no ellipsis hides the distinguishing
   tail; the confirm token is still the exact identity string.
4. A forced list of many disks overflows the pick viewport; keyboard
   selection stays in view; the boot USB is never selectable.
5. Failed export and failed evidence save stay visible (no “safe to remove”
   on failure). Export is one-at-a-time. Evidence retries are capped at
   `EVIDENCE_RETRIES` (3). A successful retry recovers.
6. Changed media (added/removed/renamed/boot-changed/identity-changed)
   clears authorization; erase does not start; boot-unidentified fails closed
   and lists no disks.
7. Held Enter / extra KEY_ENTER does not skip Confirm → Method → Last chance,
   does not power off, and does not confirm help, export, or erase.
8. Return from disk help and report help restores the origin screen, leaves
   **no** disk selected after disk help, lands keyboard focus on a safe
   control, and ignores stale help actions from other screens.

Regression tests live in `tests/test_slow_unusual_interactions.py`. They must
fail if any of the contracts above is removed, and pass on this branch.

## Safety

Never run nwipe on a real disk. `BEAMO_WIPE_DRY_RUN=1` is forced by
`tests/conftest.py`. No ISO release from this work.

## Verification (after implementation)

Product source is unchanged from `4c26217`. The change is the explicit
suite plus this evidence.

| Check | Result |
| --- | --- |
| `python3 -m pytest tests/test_slow_unusual_interactions.py` | **33 passed** in ~54 s (`new-suite.txt`) |
| Related model/Tk/console suites | **230 passed**, EXIT 0 (`related-suites.txt`) |
| Ruff on the new test file | passed |
| `python3 -m compileall` | passed |
| `git diff --check` | passed |
| Prescribed local gate, 72 DPI Xvfb | **3212 passed, 28 skipped, 1 failed** in 487.79 s (`local-pytest.txt`) |

The one full-gate failure is pre-existing and outside this card:
`tests/test_kiosk_recovery.py::test_idle_recovery_is_stable_and_signals_never_relaunch[1]`
(`stty sane` appears in a kiosk recovery trace). It fails on unmodified
`main` 4c26217 in this environment as well. It is not a disk-safety
regression and is not caused by the new tests.

Original-gap probes: see `original-regression.txt`. Inverting the
console Enter-repeat helper makes extra Enter start a fake wipe
(`skipped=0 started=True`). Stale refresh sequences stay dropped. The
new many-disk fixture has 27 selectable disks so native Tk cannot skip
for “list fits”.

### Scenario checklist

- [x] Slow discovery — scan refuses a second attempt, drops stale seq,
      startup stages before wizard, Tk loop beats during I/O
- [x] Delayed progress — old percentage, silence text, no ETA, no
      cancel, 5 s throttle, Tk bar frozen and `_tick` rescheduled
- [x] Long identifiers — wrap without ellipsis, exact confirm token,
      console 80×24, Tk serial tail visible
- [x] Many disks — boot USB never selectable, exact token still
      required, console paging, Tk overflow + selection in view
- [x] Failed exports — failure visible, no “safe to remove”, one export
      at a time, evidence retries capped at 3, Tk shows the failure
- [x] Changed media — refresh clears auth; identity change refuses
      erase; lost boot fails closed with no disks
- [x] Repeated keys — `_is_enter_repeat` swallows extra Enter; held
      Enter after help does not leave Pick or start a wipe
- [x] Return from help — disk help revokes selection; report help
      restores origin; stale opens ignored; Tk focus lands on Back

Gallery is a static click-through and does not simulate these timings.
That difference is asserted in the suite.
