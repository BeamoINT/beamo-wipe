# Backlog #89 — Keep method and disk identity visible while erasing

## Baseline (before implementation)

Source identity: `60d827a` on branch `feat/improve-screen-hierarchy`,
plus uncommitted #83–#88 WIP (all preserved).

Reproduce: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest`

Result: **2 failed, 2690 passed, 524 skipped** (total 3216). Both
failures environmental and unrelated (headless-Chrome SIGABRT;
sandbox unix-socket denial in test_usb_lab).

Current behavior (verified by reading the code). Disk + method
visibility on operation screens:

| Renderer | WORKING disk | WORKING method | STOPPING disk | STOPPING method |
|---|---|---|---|---|
| Tk | card | summary | none (timing only) | none |
| Tk stop-confirm | card | none | — | — |
| Curses | view | none | view | none |
| Line-printer | once, scrolls away | none | view (reprinted) | none |
| Accessible | announcement | summary | none | none |
| Gallery | card | summary | card | none |

- `select_disk` is PICK-gated and `set_method` METHOD-gated, and
  refresh requires no active `_wipe_request`, so the selected disk
  and method are invariant during WORKING/STOPPING. The wipe
  request (`device` + `method`) is the operation receipt; it is
  set at confirm time and cleared only on full session reset.
- Shared components already exist: `DiskIdentityView.announcement`
  (compact one-paragraph identity with uncertainty notes) and
  `NwipeMethodSpec.operation_summary` (compact one-line method +
  verify statement). Both fully translated (EN/FR/DE).

## Acceptance criteria (measurable)

1. Every operation screen (WORKING, STOPPING, stop-confirm) in
   every renderer (Tk, curses, line-printer, accessible, gallery)
   shows the target disk identity and the method summary; nothing
   on those screens shows timing text in place of identity.
2. The shown disk and method bind exactly to the wipe request
   (`_wipe_request.device` / `.method`); a request whose device
   is absent from the listing renders the path plus "Device
   identity unavailable" instead of another disk.
3. Long/unicode identities wrap within 80 columns on console
   (existing `Terminal.addstr` width assertion); no new
   interactive controls; static identity labels (no per-tick
   announcement spam beyond existing progress updates).
4. Phase changes (writing/verifying/retrying), stopping, failure,
   and result transitions never drop or contradict the operation
   identity; confirmation, evidence, and safety contracts
   unchanged.
5. Suite green apart from the 2 pre-existing environmental
   failures; no new user strings (reuse translated announcement +
   operation summary).

## Intentional differences

- CHECKING and REFRESHING screens are unchanged: they are not
  operation screens (no wipe request exists there yet).
- Tk main-working and accessible working screens already showed a
  rich disk card plus the full method summary, so they gain no
  new method line; their disk render now binds to the request.
- The scrolling line-printer reprints the compact identity with
  every progress update; screen renderers show it once as a
  static label (no per-tick announcement spam).
- Two existing `SimpleNamespace` wizard doubles gained the new
  `operation_*` attributes to mirror the extended Wizard
  interface; their assertions are unchanged.
- No new user strings: identity reuses `announcement` and method
  reuses `operation_summary`, both already translated.

## Implementation (final state)

- `wizard.py`: `operation_disk` (request-bound target, never a
  substitute), `operation_identity_text` (announcement, or the
  request path plus "Device identity unavailable" when the device
  is absent from the listing), `operation_method_text`
  (request-bound `operation_summary`); all fall back to
  selected/method when no request exists yet.
- Curses WORKING/STOPPING and line-printer WORKING/STOPPING render
  the request-bound pair via `_wrap_operation_identity` /
  `_print_operation_identity`; the line-printer once-only disk
  print is replaced by per-update identity + method.
- Tk stop-confirm gains the method line; Tk STOPPING gains the
  disk card (or fallback text) plus the method line; Tk working
  disk binding follows the request.
- Accessible `identity()` follows the request with a path fallback;
  accessible STOPPING gains identity + method labels.
- Gallery stop/stopping/stopped frames gain the method
  `operation` line (`#stop-method`).
- `docs/screens.md` Working row documents stopping identity.

## Verification evidence (final pass)

Reproduce: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest`

Result: **2 failed, 2691 passed, 527 skipped** (total 3229 =
baseline 3216 + 13 new `test_operation_identity.py` tests: 10
pass here; 2 Tk + 1 accessible skip without a display/gi and run
in CI; fail-first confirmed by 9 pre-implementation failures).
Both failures are the pre-existing environmental pair
(headless-Chrome SIGABRT; sandbox socket denial), unrelated.

- New coverage: request binding for disk + method, tampered
  selection/method ignored, unresolvable device fail-closed,
  curses working/stopping method, long-unicode wrap within 80
  columns on working, line-printer working/stopping, accessible
  stopping, gallery stop frames, Tk stop-confirm/stopping.
- Gates: `compileall`, ruff security-select on src + tests, and
  `./preview --web/--console/--helper` all pass; gallery JS
  passes `node --check`; staged chroot re-synced (19/19
  live-image tests green).
- Manual renders: FR/DE operation identity + method inspected
  ("Trois écrasements, suivi d’une vérification.",
  "Dreifaches Überschreiben, gefolgt von Prüfung."); no English
  leaks; no new strings added.

## Honest limits

- Tk (2 tests) and accessible (1 test) render assertions skip on
  this display-less, gi-less Mac; they run in CI, where Tk
  clipping suites also cover the new stopping/stop-confirm rows.
- ISO/QEMU gates unavailable here per project guide.
- Uncommitted: #89 work on top of #83–#88 WIP on
  `feat/improve-screen-hierarchy`; no commit (not authorized).
