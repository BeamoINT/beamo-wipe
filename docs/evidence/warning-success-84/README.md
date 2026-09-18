# Backlog #84 — Differentiate warning information and success messages

## Baseline (before implementation)

Source identity: `60d827a` (origin/main) on branch
`feat/improve-screen-hierarchy`, plus the uncommitted #83 screen-hierarchy
WIP (spacing only; preserved untouched).

Reproduce: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest`

Result: **3 failed, 2589 passed, 523 skipped** (85s on the dev Mac).
The 3 failures are pre-existing and environmental, unrelated to severity:

- `test_helper_boot_guidance.py::test_helper_renders_both_windows_paths_on_small_and_desktop_displays`
  — headless Chrome SIGABRTs on this Mac (also with `--no-sandbox`).
- `test_live_image.py::test_staged_chroot_package_matches_src`
  — staged `support_export.py` drift; neither file is modified in the
  working tree, so it fails at HEAD too.
- `test_usb_lab.py::test_qmp_retains_events_and_rejects_errors`
  — sandbox denies unix-socket bind.

Severity baseline (verified by reading the code):

- Tk `_panel` has kinds `warn`/`danger`/`info` only. `warn` and `danger`
  share the triangle glyph: color alone. There is no `ok`/`limits` kind.
- A saved report copy renders as neutral `info`, identical to power
  reminders. `ReportView.tone` only returns `info`/`warn`.
- The keyboard screen renders `w.error` as `warn`; pick/review/working
  render the same field as `danger`. `docs/screens.md` says layout
  failures are "shown as an error", so the keyboard rendering is a bug.
- The review-screen `erase_now_label` is bold red text: color alone.
- Console/curses print every severity as bare text, no prefixes.
- Gallery `badge()` uses one triangle for warn/danger (color alone);
  `panel()` has no severity label and no ARIA role.
- The accessible view styles erasure warnings red (error hue), errors as
  red bold (color+weight only), with no severity words or alert roles.

## Acceptance criteria (measurable)

1. `copy.py` owns five severity words: Warning, Error, Limits,
   Protected, Saved. No renderer hardcodes them.
2. Tk panels: `warn`/`danger`/`info`/`ok`/`limits` each render a distinct
   glyph shape (triangle / circle-X / circle-i / circle-check /
   square-document) plus a bold severity label line, except neutral
   `info` which stays unlabeled. Verified by stub-canvas shape
   assertions (no display) and runtime label assertions (CI/Xvfb).
3. `ReportView.tone` is `"ok"` only when `status == "saved"` with no
   evidence error and no evidence save in flight; otherwise `warn` for
   report/evidence errors, `info` otherwise. Report tone is never
   `"danger"` (deliberate: report transport must not reuse the red
   erase-failure badge) and the saved treatment never reuses the green
   erase-success badge (small in-panel check, `Saved` label, report
   wording, safe-to-remove line).
4. Every `w.error` renders as error severity in every renderer,
   including the keyboard screen and the blocked screen (badge
   `warn` -> `danger` in Tk/gallery, `Error:` prefix in console).
5. Console/curses prefix severities in words: `Error:`, `Warning:`,
   `Limits:`, `Saved:`. Protected boot keeps its banner wording
   ("protected, cannot be erased"), already distinct.
6. Gallery mirrors the Tk glyph set in SVG, adds severity labels, and
   adds roles: `alert` (warn/danger), `status` (saved), `note` (limits).
7. Accessible view: erasure warnings use amber like Tk, every severity
   carries its word, errors and warnings expose `Atk.Role.ALERT`, a
   saved report gets its own style class.
8. Contrast: every severity label color on its panel background is
   >= 4.5:1. Monochrome: glyph shapes and words differ, not just hue.
9. Existing pins updated only where the task requires it
   (`test_separate_report_status.py` tone expectations); every other
   suite result is unchanged apart from the 3 pre-existing failures.

## Intentional differences

- Report copy failures stay amber `warn`, never red `danger`
  (preserved product decision; see `docs/screens.md`).
- The web gallery is preview-only: it has no saved-report state, so the
  done screen keeps plain preview text.
- Tk has no programmatic accessibility roles; severity there is carried
  by visible labels, glyphs, and layout. Screen-reader users are served
  by the GTK view (roles + announcement) and the console (words).
- `helper/index.html` has no warnings or errors; unchanged.
- `report_recovery_warning` prose stays unprefixed (preference-recovery
  advisory, outside the five categories).
- The diagnostic flow keeps its failure-stating title
  ("Diagnostic report — wipe could not start"); its status lines are
  instructions, not error strings.

## Implementation

- `src/beamo_wipe/copy.py`: five `SEVERITY_*` words, the single
  localization source.
- `src/beamo_wipe/wizard.py`: `ReportView.tone` returns `"ok"` only for
  a fully saved copy (saved, no evidence error, no save in flight);
  report/evidence problems stay `"warn"`; never `"danger"`.
- `src/beamo_wipe/ui/tk_wizard.py`: `OK_BORDER`; glyph set triangle /
  circle-X / circle-i / circle-check / document (warn/danger/info/ok/
  limits) with `ValueError` on unknown kinds; `_panel` renders a bold
  severity label for every non-neutral kind; keyboard errors and the
  blocked badge are `danger`; storage notices are `limits`; the review
  warning and working evidence warning carry `Warning:`.
- `src/beamo_wipe/ui/console_wizard.py`: `Error:` / `Warning:` /
  `Limits:` / `Saved:` prefixes in plain and curses loops via shared
  `_report_headline`; keyboard shows errors before notices; the
  protected-boot overlay title uses the shared `Protected` word.
- `src/beamo_wipe/gallery.py`: mirrored SVG glyphs, severity labels,
  `role="alert"` (warn/danger), `role="status"` (saved),
  `role="note"` (limits); blocked badge is `danger`.
- `src/beamo_wipe/ui/accessible_wizard.py`: amber erasure warnings,
  severity words on every message, `report-saved` style,
  `Atk.Role.ALERT` on errors and warnings, shared `_error_text` so
  tick refreshes keep the label.
- `docs/screens.md`: Finished row describes the saved-copy treatment.
- `tests/test_separate_report_status.py`: tone expectations updated for
  the task-required `saved -> ok` change (only pins changed).

## Results

- New `tests/test_warning_success_differentiation.py`: 13 failed before
  the fix, all pass after (36 tests incl. the tone matrix).
- Full suite after: 3 failed, 2625 passed, 523 skipped — the same 3
  pre-existing environmental failures as baseline, +36 passes.
- Blocking lint (`compileall`, ruff security subset, `ruff check` +
  `format --check` on dev/scripts/developer_tests, shellcheck): pass.
- Advisory `ruff check`, `ruff format --check`, mypy: only
  pre-existing findings in untouched lines (verified against HEAD).
- Preview gates (`--web`, `--console`, `--helper`): pass.
  `web-preview/index.html` is gitignored (regenerated, not committed).
- Gallery JS: `node --check` clean; `badge()`/`panel()` logic executed
  in node for all five kinds (shapes, labels, roles).
- Console journey probe (splash to review and back): Warning/Limits/
  protected lines observed; no-error happy path stays unlabeled.
- Long-content wrap probe: 200+ char severity line wraps within 80
  columns without loss.
- Source identity: HEAD `60d827a` + #83 spacing WIP (preserved) +
  #84 changes listed above. Not committed (no commit authorization).

## Skipped environments (honest limits)

- Tk runtime and GTK/AT-SPI runtime tests skip on this Mac (no X
  server; `gi` unavailable) and run in CI on Xvfb.
- Headless Chrome SIGABRTs on this Mac, so no browser screenshots;
  gallery verified via string assertions plus node execution.
- Cloud Build (`./scripts/ci-cloud.sh`) unavailable: gcloud cannot
  access credentials from this sandbox. Proportionate: no packaging,
  live-build, engine, or destructive-path files changed.
- No ISO/QEMU/physical runs: nothing in this change touches erasure,
  disk selection, or nwipe flags. Only fake lsblk/demo devices used.
