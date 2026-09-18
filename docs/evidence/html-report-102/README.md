# Backlog #102 — Export a readable offline HTML erase report

RISK (honest): FR/DE wording for the new strings is
first-draft, written without native-speaker review
(same standing risk as #87–#101). Recommend native
review before any release.

## Baseline (before implementation)

Source identity: `60d827a` on branch
`feat/improve-screen-hierarchy`, plus uncommitted
#87–#101 WIP (all preserved untouched).

Reproduce: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest`

Guidance baseline (verified by reading the code):

- `_bundle_files()` wrote `result.json`, `RESULT.txt`,
  engine log, per-file `.sha256` sidecars, `README.txt`,
  and the `COMPLETE` content-only manifest. No
  readable report existed; owners had to read
  `RESULT.txt` or raw JSON.
- `build_result_summary()` is the canonical labeled
  renderer (disk, method, elapsed, result,
  verification, warnings, limitations, app/engine/
  build, clock). Its per-outcome goldens pin
  byte-identical text.
- Bundles render in the session language (labels via
  the `lang` tables); the language sweep test
  requires every UPPER-case module string to have
  exact FR/DE table entries.
- Diagnostic bundles (`diagnostic.json`) are a
  separate file set with an exact-set test; the task
  covers erase reports only.

## Design decisions (recorded before implementation)

- `REPORT.html` joins the non-diagnostic bundle next
  to `RESULT.txt`, with its own `.sha256` sidecar and
  automatic `COMPLETE` coverage (manifest hashes
  every file). Diagnostic bundles unchanged.
- One shared canonical field list `_result_fields()`
  feeds both `RESULT.txt` and `REPORT.html`, so the
  page cannot drift from the receipt data. The txt
  goldens prove the refactor is byte-identical.
- Owner form only: no `SHARE.html` (the sharing copy
  keeps `SHARE.txt`). `REPORT.html` carries disk
  identifiers, so the do-not-share warning names it.
- Page: plain HTML5 + inline CSS, no scripts,
  images, links, or external references; `lang`
  follows the session language (fail-closed to
  `en`); semantic `main`/`h1`/captioned table with
  `th scope=row`; `@media print`; narrow-screen
  wrapper for long checksums.
- New caption/note strings are module constants with
  FR/DE table entries (swept-surface architecture);
  the CSS blob is `_`-private so it is not swept.
- Receipts unchanged on purpose: `owner_file` stays
  `RESULT.txt` as the canonical anchor; the in-
  bundle `README.txt` documents the new page.

## Acceptance criteria (measurable)

1. Non-diagnostic bundles contain `REPORT.html` +
   sidecar; `COMPLETE` covers it; diagnostic
   bundles have no `REPORT.html`.
2. Every `RESULT.txt` value appears escaped in the
   page for every outcome case.
3. Hostile model/serial/warnings render inert
   (`&lt;` etc.); page parses with `html.parser`.
4. `{}` and non-dict evidence render `unavailable`,
   never blank cells, never raise.
5. No `script`/`src`/`href`/`link`/`img`/`iframe`/
   `http(s)`/`url(`/`@import`/`javascript:` tokens.
6. `lang` attr, `title`, `h1`, `main`, captioned
   table, `th scope=row`, `@media print`.
7. README names the page; share-how lists it under
   do-not-share (EN/FR/DE).
8. FR/DE sessions: `lang` attr, caption, and
   heading match the txt language.
9. All pre-existing report/export/language tests
   pass unchanged (txt goldens byte-identical).

## Implementation

- `result_summary.py`: `_result_fields()` shared
  list; `build_result_report_html()` +
  `_html_value()` + `_REPORT_HTML_STYLE`;
  `HTML_CAPTION`/`HTML_NOTE` constants;
  `_current_language()` allowlist helper.
- `support_export.py`: `REPORT.html` + sidecar in
  `_bundle_files()`; `README_ORIGINAL` /
  `README_SIMPLE` / `README_SHARE_HOW` mention it.
- `locales/fr.py`, `locales/de.py`: 3 README keys
  + 2 HTML keys updated.
- `docs/runbook.md`: artifact-table row for the
  new file.

Defects found and fixed during verification: the
CSS constant tripped the translation sweep
(renamed `_`-private); the `lang` attribute and
caption/note needed session-language support
(added constants + FR/DE entries + round-trip
test); two test-side bugs (mismatched checksum
input, presentation-title shadowing).

## Verification

- New `tests/test_report_html.py` (8 tests):
  errored on collection before (missing builder),
  all pass after.
- Full suite: **3 failed, 2881 passed, 560
  skipped** (3444 total). The 3 failures
  (helper DOM SIGABRT, staged-chroot package
  match, QMP permission) reproduce identically on
  unmodified HEAD via `git stash` — pre-existing
  environmental, unrelated to this change.
- Blocking ruff security selections pass (src +
  tests); full `ruff check` clean on touched
  files; new code format-clean (remaining format
  drift is pre-existing).
- mypy advisory unchanged: 22 pre-existing
  errors, none in touched files.
- Rendered `verified` + `verification_failed`
  pages from fake evidence inspected: all
  required sections, warnings list, escaped
  values, offline-safe.
- No browser pixels (genuine environmental
  block, every path attempted): cached
  Playwright chromium/headless-shell SIGABRT;
  installed Chrome `--headless` abort-trap-6
  (same crash as the pre-existing helper DOM
  test); installed Firefox headless exits 0 but
  writes no screenshot in any syntax, incl.
  fresh profile; `qlmanage` sandbox-denied; no
  network for new tools; safaridriver would need
  a visible window. Instead: strict `tidy`
  validation passes clean (exit 0) on 13 pages
  (all 11 outcomes + hostile + FR), CSS
  class/markup cross-check exact, plus the
  static-compat test assertions and full source
  review of two rendered samples.
- Tk/accessible runtime, ISO/QEMU, live nwipe
  remain CI/VM-only, unproven on this Mac.
- No commit (not authorized).
