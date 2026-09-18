# Backlog #106 — Show support code when export is unavailable

RISK (honest): FR/DE wording for the new strings is
first-draft, written without native-speaker review
(same standing risk as #87–#105). Recommend native
review before any release.

## Baseline (before implementation)

Source identity: `fd199de4d89f1510b67008b90773148c49396e58`
(`origin/main`, feat: screen-hierarchy #84–#105).

Reproduce: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest`

Guidance baseline (verified by reading the code):

- Diagnostic JSON already carried `error_code` plus
  injected build identity, but only after a verified
  USB export.
- Fail-closed export (FAT32, unidentified boot,
  missing media, worker receipt) left the owner with
  translated `SafetyError` text only.
- Logs live on tmpfs (`/tmp/beamo-wipe/`) and die at
  shutdown, so a phone photo could not be correlated
  to a build or a log line.
- GitHub issue #106 does not exist (same as #105).

## Design decisions (recorded before implementation)

- Closed taxonomy in `support_code.py`: displayed
  form `BW-{S|X|R|E|U}-{TOKEN}`. Tokens use a
  phone-safe alphabet (A–Z and 2–9, no 0/O/1/I/L).
  Families: S startup (`diagnostic_report.CODES`),
  X export/media refusals + wizard export wrappers,
  R finished-wipe outcomes except `verified`,
  E local evidence-save failures, U unknown
  (`BW-U-UNKN`).
- Lookup by current-language constant identity,
  never English substrings. Labels translate; code
  and `build_id` never do.
- Build id from `evidence_identity()` only (injected
  `/usr/share/beamo-wipe/build-identity.json`).
  Runtime `BUILD_ID` is ignored. Missing →
  `unavailable`.
- `identity_for_wizard`: DIAGNOSTIC always (startup
  primary; extra_code = export refusal if mapped and
  not progress); PICK_BLOCKED / PICK_EMPTY; WHAT when
  `graphical_unavailable`; LAST_CHANCE when error and
  diagnostic is reachable; live DONE when the report
  is not saved. Preview DONE stays silent.
- Log correlation: `log_diag` area `support` plus
  `BEAMO_WIPE_SUPPORT_*` serial markers.
- Intentional differences: helper has no live session
  so it only instructs reading the on-screen lines;
  gallery done-fail stays preview; console/GTK use
  text not a QR of the code; kiosk recovery cannot
  mint codes without Python.

## Acceptance criteria (measurable)

1. Every `diagnostic_report.CODES` value, every
   `ALL_REFUSALS` detail, every wizard export
   wrapper, and every evidence/outcome code except
   `verified` maps to a unique `BW-` code.
2. Tokens match `CODE_RE`; no 0/O/1/I/L.
3. FR/DE refusal text maps to the same code as EN;
   English text does not match after a language
   switch.
4. FAT32 diagnostic failure shows `BW-S-DSCV` plus
   save code `BW-X-FAT` plus build id (regression).
5. Progress/success copy does not invent a save code.
6. Identity text never contains `/dev/` or discovery
   secrets. `BUILD_ID` env is ignored.
7. `record_identity` logs area `support` and emits
   `BEAMO_WIPE_SUPPORT_*`.
8. Tk, console, GTK, gallery blocked/empty, helper
   EN/FR/DE, boot-card, screens, startup-diagnostics,
   and runbook 1.8 document the lines.
9. Disk selection and nwipe flags unchanged.

## Implementation

- New `src/beamo_wipe/support_code.py`.
- `wizard.support_identity` logs on first display.
- Tk `_support_identity_block`; console
  `_support_identity_text`; GTK
  `support_identity_labels`.
- Gallery sample codes on blocked/empty.
- Helper EN/FR/DE saving-report paragraph.
- `support_export._emit_export_failure` records the
  identity as well as the existing export marker.
- Tests: `tests/test_support_code.py`.
