# Backlog #105 — Verified support destination on error screens

RISK (honest): FR/DE wording for the new strings is
first-draft, written without native-speaker review
(same standing risk as #87–#104). Recommend native
review before any release.

## Destination ownership (confirmed before shipping)

`beamosupport.com` was designated by the repo owner
in-session for #105. Verified: no beamo domain or
support URL existed anywhere in `src/`, docs,
helper, or packaging before this change (grep over
all four), so there is nothing conflicting to
reconcile. QR encodes `https://beamosupport.com`
(scheme required for phones to open it); displayed
short text is the bare domain.

## Baseline (before implementation)

Source identity: `60d827a` on branch
`feat/improve-screen-hierarchy`, plus uncommitted
#87–#104 WIP (all preserved untouched).

Reproduce: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest`

Guidance baseline (verified by reading the code):

- 9 strings say "contact support" with no
  destination anywhere: `outcomes.SUPPORT`,
  `NEXT_START_FAILED`, `NEXT_STOP_UNCONFIRMED`,
  `wizard.RECOVERY_MAY_RUNNING`,
  `KEEP_SESSION_OPEN`, `NEXT_TRY_SUPPORT`,
  `NEXT_SUPPORT`, `copy.ACCESSIBLE_UNCONFIRMED`,
  `inventory.EMPTY_STEPS`.
- Judgment-call inclusions (same dead end,
  different wording): `occupied` ("ask
  support"), `app.STARTUP_BLOCKED` and
  `wizard.STARTUP_UNCONFIRMED` ("for support"),
  `engine_checks.HIDDEN_MAYBE` ("ask support").
- 12 of 15 outcome views refer to support;
  `verified`/`unverified` do not.
- No QR capability in `src/` or the live image.

## Design decisions (recorded before implementation)

- `support_contact.py`: single source
  (`SUPPORT_SHORT`/`SUPPORT_URL`), cached
  EC-H QR matrix with 4-module quiet zone,
  inline SVG (no xmlns: HTML parsing supplies
  it, and the namespace URI would trip the
  #102 offline-token ban). Payload is the
  constant URL only — no serials, paths, or
  evidence by construction.
- Structural triggers, never translated-text
  sniffing: `outcomes.view_needs_support`
  (code set derived from the EN vocabulary at
  import; codes are language-stable),
  `wizard.error_needs_support` (translated-
  constant comparison),
  `support_export.next_step_needs_support`
  (mapped-step identity),
  `wizard.done_support_needed` /
  `evidence_support_needed` properties.
- Outcome vocabulary byte-identical: the block
  renders adjacent, never inside canonical
  strings (goldens untouched).
- Tk: `_support_block` (QR PhotoImage ~111px +
  lead text; text-only fallback when imaging
  fails) on DONE/EMPTY/BLOCKED/working-error/
  PICK-error/diagnostic screens under the same
  conditions. Console/accessible: translated
  text block (the offline fallback), focusable
  labels in GTK. Gallery: SVG block on empty/
  stopped/stop-unconfirmed (its done screens
  use preview views without support text, so
  no block there). REPORT.html: Support section
  for failing views. README: one support line
  (covers RESULT.txt readers).
- Deliberate exclusions: RESULT.txt/SHARE.txt/
  result.json bytes (receipt stability),
  helper (no Beamo support copy), ASCII QR in
  terminals (unreliable to scan; text is the
  specified fallback), QR in the screen-reader
  UI (text is the accessible path).
- Live image gains `python3-qrcode` (matrix use
  is pure Python; no Pillow needed).

## Acceptance criteria (measurable)

1. One constant pair; QR payload byte-equals
   the URL; every surface derives from it
   (drift test).
2. Block on all trigger screens; absent on
   verified/unverified DONE, unmapped steps
   ("" preserved), identify-blocked.
3. EC-H + quiet zone + determinism; cv2
   read-back decodes the exact URL;
   constant-only payload.
4. Text fallback adjacent to every QR;
   focusable GTK labels; wrapped console.
5. FR/DE parity incl. `{short}` placeholders
   (sweep + placeholder tests).
6. Tk widget ~111px; clipping tests extended
   (CI proves); console frames eyeballed.
7. Live list + staged sync; Cloud Build gate
   attempted (see result below).
8. Goldens + #101 pins pass unchanged.

## Implementation

- New `support_contact.py`; `outcomes.py`
  (`SUPPORT_CODES`, `view_needs_support`);
  `wizard.py` (`error_needs_support`,
  `done_support_needed`,
  `evidence_support_needed`,
  `evidence_warning`/`diagnostic_step`
  appends); `support_export.py`
  (`next_step_needs_support`,
  `README_SUPPORT`); `copy.py`
  (`SUPPORT_LEAD`/`SUPPORT_TEXT`,
  `support_lead()`/`support_text()`,
  aftercare append); console/accessible/Tk
  insertions; gallery payload/template/CSS;
  `result_summary.py` section;
  `locales/fr.py`/`de.py` (2 copy + 1
  summary + 1 export key each);
  `docs/screens.md` clause; live list;
  staged-chroot re-sync (12 files);
  `python3-qrcode` in CI test/preview
  phases and Cursor Cloud setup.

Defects found and fixed during verification:
missing `VIEWS` import (NameError on
error screens — caught by the full suite,
not the focused tests); SVG xmlns tripping
the offline-token ban (removed, inline-SVG
safe); DE README string identical to EN
(keeper entry, correct German); Tk
Optional parent (mypy); staged drift after
format fixes (re-synced).

## Verification

- New `tests/test_support_contact.py` (11
  tests): errored on collection before, all
  pass after. Tk DONE-matrix + accessible
  focus tests added (skip headless, CI/Xvfb).
- Curses DONE fail (block present) vs
  verified (absent) frames rendered from
  fake discovery and eyeballed.
- Gallery JS extracted and `node --check`
  valid; REPORT.html re-validated with
  `tidy` (exit 0).
- Full suite: **2 failed, 2900 passed, 570
  skipped** (3472 total) — the 2 known
  pre-existing environmental failures.
- Blocking ruff security selections pass;
  new code format-clean; mypy back to the
  exact 22 pre-existing errors.
- Tk/accessible pixels, ISO/QEMU, live
  nwipe remain CI/VM-only (no Xvfb here;
  browsers sandbox-blocked as in #102).
- Cloud Build gate attempted and
  UNAVAILABLE: `gcloud auth list` fails
  with `Operation not permitted` on
  `~/.config/gcloud` (sandbox denies auth
  file writes), so `./scripts/ci-cloud.sh`
  cannot submit from this session. The
  `python3-qrcode` live-list addition and
  Tk clipping tests are therefore
  CI-unproven; run CI before any release.
- Keyboard-access note: console exposes
  the destination in the TTY text stream
  and GTK uses focusable labels; Tk uses
  plain labels like every other Tk status
  text in the app (its keyboard model
  covers controls, and the screen-reader
  path is the GTK UI).
- No commit (not authorized).
