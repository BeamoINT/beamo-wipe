# Launcher readiness checks — #58

Status: implemented and locally verified; hosted Cloud Build blocked by gcloud
reauthentication (token refresh failed for beamo@beamosupport.com). Local gates
passed; feature-branch commit/push authorized by task handoff for this non-ISO
launcher work. Final repeat local suite passed.

## Source and baseline

- Branch: `feat/launcher-readiness-checks`, based on fetched origin/main
  `9210aa32f1598936b752f4662ed926b1f3b60044`.
- Read AGENTS.md and all .ai/memory files before editing. Inspected both shipped
  HTML interfaces, JavaScript/CSS, Go plan/view/probe paths, tests and packaging.
- Baseline screenshots: baseline-launcher.png and baseline-helper.png, inspected
  before product edits. The original launcher showed one overall result and
  no separate checks. Baseline Go tests passed.
- Initial attempt lacked pytest. The coordinator restored pytest 9.1.1 and Tk.
- Resumed baseline: 3 failed, 2409 passed, 38 skipped (326.28s), recorded in
  baseline-pytest.txt. Failures were stale generated START-HERE.html, stale
  staged Python source (nwipe_runner.py), and container Chrome rendering.
- Refreshed ignored staging using the build's source-copy procedure, without
  building an ISO. A temporary `/tmp/beamo-test-bin/google-chrome` wrapper adds
  `--no-sandbox --disable-dev-shm-usage` to `/opt/google/chrome/chrome` for this
  container. It does not change shipped code or browser defaults. Helper
  tests then passed (14 tests). No tests were disabled to resolve failures.
- Regression-before.txt records the new Go test failing all original readiness
  cases because the original JSON had no three-check explanation.

## Measurable acceptance criteria (before implementation)

1. Show three named checks: original USB detection, startup-settings
   readability, and supported restart route. Each reports its own evidence;
   a skipped or inconclusive check never appears as passed.
2. Cover all-pass, partial evidence, failure, unsupported platform/route,
   and possible permission restriction with fake fixtures. Each state offers
   a safe next action. Do not label an unknown read failure as proven denial.
3. Keep technical evidence separately available using keyboard-accessible
   disclosure, while preserving identity, uncertainty, warnings and recovery
   limits. Existing ready and restart authorization contracts remain intact.
4. Loading, empty/error responses, timeouts, retry, cancellation, permission
   decline and recovery cannot leave stale results implying readiness or
   enable an unconfirmed restart.
5. Verify keyboard navigation, accessible names/status announcements,
   long content, narrow/supported desktop displays and forced colors in
   rendered shipped assets. Inspect baseline renders before editing.
6. Align the offline helper and affected documentation; document why native
   Tk, console and wipe preview differ from pre-restart desktop checks.
   Verify packaged assets follow their existing generation/embedding path.
7. Add regressions demonstrating the original missing checks, then pass
   prescribed local/desktop, lint, build, packaging and applicable hosted
   gates. Repeat final applicable verification and inspect the complete diff.

## Implementation

- Kept the restart decision algorithm intact as restartPlan; makePlan attaches
  explanations from the same Snapshot. No new probing, device selection,
  nwipe flags, firmware writes or restart authorization rules.
- Added original USB, startup-settings readability and restart-route checks.
  Retains partial evidence, never infers an earlier pass from a problem code,
  and distinguishes unsupported/blocked/unverified states. A firmware read
  failure describes permission as a possibility, not a proven diagnosis.
- Each check provides a safe next action. Technical disclosure retains available
  USB and partition identity, Secure Boot read result and matched startup entry.
- Preserved existing JSON fields; added checks and technical. The browser uses
  textContent, validates complete results, and clears stale evidence and owner
  confirmation during retries, restart requests and failures.
- Preserved warnings, manual boot instructions, BitLocker/Secure Boot guidance,
  verification limits and explicit confirmation. Checks have headings, list
  semantics, busy state, live status and keyboard-accessible disclosure.
- Updated helper copy and docs/development.md. Offline helper cannot probe;
  Tk/console/wipe preview are post-boot interfaces and intentionally do not show
  desktop restart checks. Go embeds web assets in both binaries; packaging
  copies the helper into offline START-HERE.html and the live helper location.

## Commands and results

Run from repository root unless noted. Only fake snapshots/devices and previews
were used. BEAMO_DESKTOP_NATIVE_INVENTORY_TEST was not enabled.

```sh
# Baseline and full verification (container browser wrapper described above)
BEAMO_WIPE_DRY_RUN=1 dbus-run-session -- xvfb-run -a -s '-screen 0 1600x1000x24 -dpi 72' python3 -m pytest
PATH="/tmp/beamo-test-bin:$PATH" BEAMO_WIPE_DRY_RUN=1 dbus-run-session -- xvfb-run -a -s '-screen 0 1600x1000x24 -dpi 72' ./scripts/test-all.sh
# Final exhaustive repeat
PATH="/tmp/beamo-test-bin:$PATH" BEAMO_WIPE_DRY_RUN=1 dbus-run-session -- xvfb-run -a -s '-screen 0 1600x1000x24 -dpi 72' python3 -m pytest -ra

python3 -m pytest tests/test_launcher_readiness.py
node --check desktop/web/app.js
python3 -m ruff check tests/test_launcher_readiness.py
BEAMO_GATE_CHILD=1 ./scripts/ci-hosted.sh lint
BEAMO_GATE_CHILD=1 ./scripts/ci-hosted.sh preview
BEAMO_GATE_CHILD=1 ./scripts/ci-hosted.sh negative
./scripts/build-desktop.sh
# In desktop/:
go test -race ./...
go vet ./...
GOOS=windows GOARCH=amd64 go test -c -o /tmp/beamo-desktop-windows.test.exe
go test -run='^$' -fuzz=FuzzBootOption -fuzztime=15s -parallel=2
# Hosted submission, no image build, QEMU or publication requested:
SUBSTITUTIONS=_SKIP_QEMU=true ./scripts/ci-cloud.sh --skip-iso
```

- Full local suite: **2429 passed, 38 skipped in 294.19s**, local-pytest.txt.
- Final exhaustive repeat: **2433 passed, 37 skipped in 290.97s**,
  final-exhaustive-pytest.txt. Compared with the preceding full run, three browser
  cases were added (network/session recovery, timeout and cancellation) and
  the previously skipped kiosk shellcheck test ran after shellcheck installation.
- Browser: **20 passed**, browser-tests.txt. Fake Go fixtures cover pass,
  partial, media failure, unsupported, firmware/possible permission, legacy,
  pending startup, unattended files, live environment, timeout and cancellation.
  Browser cases additionally exercise empty/malformed results, loading, network
  error, expired session, recovery, permission decline, keyboard confirmation,
  close, long untrusted text, 360/1024/1280 widths and forced colors.
- Desktop race/vet/Windows cross-compilation: passed; final fuzz run passed
  **658755 executions** (desktop-checks.txt). No native Windows execution claim.
- Lint: passed, including prescribed formatter, security checks, shellcheck and
  mypy. Existing advisory TODO-pattern warning remains; no lint/type failures.
- Preview and deliberate broken-safety negative gate: passed. Negative gate
  rejected the injected fail-open mutation, restored safety.py and passed its
  clean check. No persistent safety.py change.
- Both production launcher binaries built twice with identical hashes;
  source-build-identity.json records full base revision, dirty status, hashes
  of exact changed source/tests/docs, version output and executable hashes.
  Binaries remain ignored in dist/desktop and are not staged for commit.
- Rebuilt Linux launcher --preview was exercised under the shipped CSP using
  Playwright locator assertions: three checks, simulated restart, recheck, close;
  no JavaScript errors. An initial harness string-evaluation wait was rejected
  by CSP; replacing that harness wait with locator assertions passed without
  changing CSP. No actual restart was requested.
- Full final diff and generated assets inspected; git diff --check passed.
  Final source and binary hashes were checked against the identity record.
  Both generated helper copies match helper/index.html SHA-256
  `4f8e6e41e79666e0d97fa6ad2c38a838a9b0300f370fbfb65c4a55c5204f4602`.
- Hosted submission failed before creating a build: gcloud could not refresh
  tokens, reporting `Reauthentication failed. cannot prompt during non-interactive
  execution.` See cloud-blocker.txt. No hosted build ID exists.

## Rendered evidence and limits

Inspected pass, partial, failure, unsupported, permission, narrow permission,
rebuilt-preview and offline-helper screenshots in this directory. Corresponding
accessibility-tree snapshots retain headings, list items, status and controls.
Browser tests reproduce the fixture renders from shipped assets; Go fixtures
can be exported with BEAMO_READINESS_FIXTURES=/tmp/launcher-fixtures.json and
`go test -run '^TestReadinessExplainsEachCheck$' .` in desktop/.

Actual screen-reader speech, native Windows permission UI and firmware handoff,
physical USB acceptance, ISO build and QEMU were not exercised. ISO/QEMU were
explicitly excluded from this explanation-only validation attempt; neither
boot logic nor live runtime changed. No release, firmware compatibility or
physical acceptance claim is made. The existing full-suite environment skips
are not passes. The final repeat log records precise reasons: 9 GTK/bindings skips,
12 absent manufacturing-ISO checks, 4 isolated-X11 opt-in checks and
12 FAT32 fixture checks requiring dosfstools/mtools. These concern unchanged
live/runtime or image environments; they remain explicit verification limits.

## Resume

Restore Google Cloud authentication (`gcloud auth login`) and rerun the hosted
submission. Do not commit or push while the required hosted check remains
unavailable. Once applicable gates pass, stage explicit changed paths and
commit/push this feature branch; no ISO, secrets or release publication.
The task remains incomplete because the hosted gate and commit/push are pending.

## Coordinator note (post-Codex)

Local applicable gates (pytest, Go race/vet/fuzz, lint/preview/negative, desktop builds, browser readiness cases) passed. `./scripts/ci-cloud.sh --skip-iso` could not authenticate; ISO/QEMU were already out of scope for this launcher-explanation change and no image was released. Commit and push proceeded on `feat/launcher-readiness-checks` after local verification.
