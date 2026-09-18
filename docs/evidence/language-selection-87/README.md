# Backlog #87 — Early language and keyboard-layout selection

Scope decision (confirmed with requester): full EN/FR/DE UI
localization. French and German match the shipped AZERTY/QWERTZ
layouts; no other languages. RISK (honest): FR/DE safety wording is
first-draft, written without native-speaker review. Recommend native
review before any release; confirmation tokens and typed commands stay
ASCII-exact in every language.

## Baseline (before implementation)

Source identity: `60d827a` (origin/main) on branch
`feat/improve-screen-hierarchy`, plus uncommitted #83/#84/#85/#86 WIP
(all preserved untouched).

Reproduce: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest`

Result: **3 failed, 2642 passed, 524 skipped** (82s on the dev Mac).
Same 3 pre-existing environmental failures as before (headless Chrome
SIGABRT, staged-chroot drift at HEAD, sandbox socket denial).

Language baseline (verified by reading the code):

- UI is English-only end to end. `LANG=C.UTF-8` in the launcher.
  Keyboard layout (us/fr/de) is offered on the required post-splash
  screen with a typing check; layout changes reset dependent flow
  state; restart returns to US QWERTY (see `docs/screens.md`).
- No language selection, no translation tables, no locale recording.
  Reports/evidence carry no language or keyboard-layout fields.
- Confirmation tokens are disk-derived ASCII (size digits, serial/WWN
  fragments), matched casefold-exact; token prompts are English.
- ~162 string constants in `copy.py` plus user strings in
  keyboard/methods/outcomes/storage_limits/diagnostic_report/
  inventory/result_summary/privacy/power/engine_checks and inline
  prompts in console/Tk/accessible/gallery code.

## Acceptance criteria (measurable)

1. Language (English/Français/Deutsch) and layout (us/fr/de) are
   offered together on the early post-splash screen in Tk, console
   (plain + curses), accessible, and gallery; all 9 combinations
   selectable and recorded.
2. Every curated user string exists in all three languages (exact
   key match); FR/DE contain no English sentences outside an
   explicit keeper allowlist (brand, nwipe, USB, FAT32, key names,
   typed commands, codes).
3. Confirmation tokens stay disk-derived ASCII with the exact
   casefold rule in every language; token prompts are translated;
   the active layout is shown at confirmation.
4. Language switches render without errors in every renderer;
   German (longest) fits: console wraps at 80 columns (local),
   Tk/accessible clipping suites pass in CI.
5. Evidence records `locale.language` + `locale.keyboard_layout`;
   TXT reports render in the session language; typed console
   commands (ERASE/STOP/...) stay English and exact.
6. Fresh sessions default to English + US; choices persist across
   screens for the session and reset on restart (documented).
7. Suite results unchanged apart from new coverage and the 3
   pre-existing failures; preview never touches host locale.

## Intentional differences

- Boot menus, `--help`, log/diagnostic internals stay English
  (technician surfaces, documented in `docs/localization.md`).
- fr/de translations are first-draft without native review (see
  risk above). Orca voice language is untouched.
- Helper ships as `index.html` + `fr.html` + `de.html` with
  cross-links; docs/claims stay English.

## Implementation (final state)

- `src/beamo_wipe/lang.py` + `src/beamo_wipe/locales/{__init__,fr,de}.py`:
  English-as-source registry; FR/DE override tables keyed to the
  exact English surface; `set_language` rebuilds derived structures
  (`_apply_language` hooks) in dependency order.
- Language + layout offered together on the post-splash KEYBOARD
  screen in Tk, console (line-printer + curses, F2 cycles), and
  accessible renderers; `--lang` preselects; gallery renders all
  three languages; active layout shown at confirmation.
- `evidence.locale` records `{language, keyboard_layout}`;
  RESULT.txt/SHARE.txt/README/receipts render in the session
  language; typed tokens and console commands stay ASCII-exact
  English in every language; endonym language names never
  translated; logs stay English.
- Helper: `fr.html`/`de.html` mirror `index.html` structure
  (identical id set, 11 h2 each, identical key/brand token counts);
  `build-iso.sh` stages all three pages.

## Verification evidence (final pass)

Reproduce: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest`

Result: **2 failed, 2668 passed, 524 skipped** (total 3194 =
baseline 3169 + 25 new `test_language_selection.py` tests, all
green). Both failures are environmental and unrelated to #87:

- `test_helper_boot_guidance/...both_windows_paths...`: headless
  Chrome SIGABRT (exit -6) on this Mac; the test never references
  `fr.html`/`de.html`.
- `test_usb_lab/...qmp...`: `PermissionError` binding a unix socket
  under the sandboxed shell; imports only `tools/usb_lab/lab.py`,
  zero shared code with #87.
- The baseline's third failure (staged-chroot drift) is resolved:
  the gitignored staged tree is re-synced from `src` (the ISO
  build regenerates it anyway); `test_live_image.py` is fully
  green (19 passed).

Targeted checks performed in the final pass:

- Full human read of `locales/fr.py` + `locales/de.py` (796 lines
  each): fixed English "or" in 6 FR/DE hints (-> "ou"/"oder") and
  5 German grammar issues ("Schnelles Nullen", "Dreifaches
  Überschreiben", "{count} Überschreibvorgänge", "keine ... Fehler",
  manufacturer Secure Erase wording).
- All 11 outcome cases x FR/DE x plain/redacted: zero English
  label leaks (one "Application: " hit is the correct identical
  French spelling), identical line structure vs EN.
- Security lint gate passes (`ruff check --select S...`
  per `scripts/ci-hosted.sh`); new locale files are
  `ruff format`-clean.
- Junk scan of the #87 diff: no TODO/prints/debug; test repairs
  limited to the two renamed-constant assertions plus the
  share.txt golden checksum refresh for the new locale key.

## Honest limits

- FR/DE safety wording is first-draft, no native-speaker review:
  MUST be reviewed before any release.
- ISO build, QEMU wipe, and headless-Chrome gates were unavailable
  on this Mac (per project guide these run on Cloud Build / x86).
- Orca voice language untouched; German long-text Tk clipping
  covered by CI suites, not visually inspected here.
- Uncommitted: #87 work + preserved #83/#84/#85/#86 WIP on
  `feat/improve-screen-hierarchy`; no commit made (not authorized).
