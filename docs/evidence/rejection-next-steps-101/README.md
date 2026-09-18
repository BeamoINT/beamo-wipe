# Backlog #101 — Make report-media rejection actionable

RISK (honest): FR/DE wording is first-draft, written without
native-speaker review (same standing risk as #87–#100).
Recommend native review before any release.

## Baseline (before implementation)

Source identity: `60d827a` on branch
`feat/improve-screen-hierarchy`, plus uncommitted #87–#100 WIP
(all preserved untouched).

Reproduce: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest`

Result at #100 close: **2 failed, 2853 passed, 557 skipped**
(headless Chrome SIGABRT + sandbox socket denial, both
pre-existing environmental).

Guidance baseline (verified by reading the code):

- Only no-media/multiple-media rejections carried a next
  step (`USB_NOT_SINGLE` wrapper). All ~50 other refusal
  details surfaced as bare problem statements.
- Parent-side specific errors (discovery/selection/
  identity) surface verbatim; worker-internal failures
  (mount/write/sync/verify/unmount, incl. full media)
  collapse to the exact fail-closed receipt
  `ExportReceipt(False, False, "export_failed")` →
  generic `REPORT_NOT_SAVED`. The receipt equality is a
  deliberate security invariant (untrusted worker
  stdout); the parent must not learn causes from it.
- Diagnostic errors surface as a bare message line.
- Retry needs no re-insertion (attempts re-scan against
  the wipe-time baseline; verified in #100).

## Design decisions (recorded before implementation)

- Mapping table `EXPORT_NEXT_STEPS` + `next_step_for()`
  in `support_export.py` (owns the details, translated
  module): 7 shared steps (replug, different stick,
  try-then-support, support, try-then-shutdown,
  sort-while-off, wait-other); self-contained details
  map to ""; unknown details map to "".
- Raised strings byte-identical: refusal rules,
  precedence, markers, and all exporter contracts
  untouched — only presentation appends steps.
- Wipe flow: `report_aftercare(error)` = message + step
  + extended retry + volatile. `EXPORT_GUIDE_RETRY`
  gains the different-stick escalation (covers generic
  worker failures incl. full media).
- Diagnostic flow: `wizard.diagnostic_step` + one-line
  appends in all four renderers.
- Full media is NOT named as such: distinguishing
  worker-internal causes would require trusting worker
  stdout or a new exit-code channel — rejected as scope
  expansion into the security boundary (see limit
  below). The escalation ladder covers it actionably.

## Acceptance criteria (measurable)

1. Every refusal constant maps (explicit ~60-entry
   list); "" only for the 9 self-contained messages.
2. Steps static and safe: no paths/serials/templates,
   no "safe to remove" (EN + FR/DE equivalents).
3. Aftercare error: problem + step + retry + volatile;
   never-promise contract preserved.
4. Precedence: multi-fault fixtures surface the first
   error and its step (count beats filesystem;
   writability beats filesystem).
5. Retry after correction succeeds; changed-media maps
   to its embedded "Try again".
6. Console curses + plain show problem + step;
   diagnostic property + render covered.
7. FR/DE parity for all new keys; helper remedies
   EN/FR/DE; docs updated.
8. No weakening: all pre-existing exporter/UI tests
   pass unchanged (raised strings identical).

## Implementation

- `support_export.py`: `NEXT_*` x7,
  `_build_next_steps()`/`EXPORT_NEXT_STEPS`,
  `next_step_for()`; `_apply_language` rebuild.
- `copy.py`: error branch appends step; extended
  `EXPORT_GUIDE_RETRY`.
- `wizard.py`: `diagnostic_step`.
- `ui/console_wizard.py` (curses + plain),
  `ui/tk_wizard.py`, `ui/accessible_wizard.py`:
  diagnostic step appends.
- `locales/fr.py`, `locales/de.py` (7 support_export
  + 1 extended copy key); helper `saving-report`
  rejection list x3 + `START-HERE.html` sync;
  `docs/screens.md` sentence.

Defect found and fixed during verification: the table
keys went stale after `set_language` (French lookup
missed). Fixed by rebuilding via `_apply_language`;
covered by a language round-trip test.

## Verification

- New `tests/test_rejection_next_steps.py` (21 tests):
  20 failed before (1 existing-behavior pin passed),
  all pass after. Tk + accessible diagnostic tests
  added; they skip headless here and run under CI/Xvfb.
- Full suite: **2 failed, 2874 passed, 558 skipped** —
  the same 2 pre-existing environmental failures.
- Blocking ruff selections pass (src + tests); new
  file clean under full ruff; mypy advisory unchanged
  (22 pre-existing errors).
- 80x24 DONE error render eyeballed (problem → step →
  retry → escalation → volatile, coherent ladder);
  French error render spot-checked after the rebuild
  fix; narrow DONE paging already covered in #100.
- Ignored staged-chroot tree re-synced (8 files).
- Tk/accessible runtime, ISO/QEMU, live nwipe remain
  CI/VM-only, unproven on this Mac.
- No commit (not authorized).
