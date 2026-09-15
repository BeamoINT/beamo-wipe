# Notion Details append — #60 (paste this)

**Status: In progress.** Local acceptance for identity + current-build guidance is met. Do not mark Done if Jack requires a manufactured ISO as the only proof of injection on media.

Continued with **Grok 4.6 high** via the T3-wired Grok CLI.

### Baseline

- Repo: `beamo-wipe`
- Starting `main`: `4c26217877047abe244bd3ef9266a1ced1db5491` — `fix: gallery HTML-escape pin matches boot-card serial rendering`
- Branch: `feat/match-compat-to-usb-build` (independent from current main; #42/#113 and #43/#59 left alone)
- Implementation commit: `0f9208111b2dd02b7237a9f133932dc01f546b36` — `feat: match compatibility guidance to the USB build (#60)`
- PR: https://github.com/BeamoINT/beamo-wipe/pull/44
- Focused baseline: 186 passed, 12 skipped (`docs/evidence/compat-build-identity-60/baseline-pytest.txt`); desktop `go test` ok

### What landed

- Canonical current-USB story in `src/beamo_wipe/compat_story.py` (not the matrix changelog).
- ISO builder injects the existing `build-identity.json` into offline helper/`START-HERE.html` and copies the JSON onto the FAT-visible USB root.
- Git helper is labeled **not a manufactured USB image**. Desktop launcher help/footer shows USB identity or the same honest stub. App `--version` and live Show more show a customer sentence; technical IDs stay in dedicated fields / support export.
- Compatibility copy on helper, desktop help, and the What screen matches this image (x64 Windows/Linux, signed Debian EFI, no Apple Silicon/Chromebooks, no Secure Boot bypass). Older sticks may differ; desktop still accepts media **without** `build-identity.json`.
- `docs/claims.md`, boot card, and runbook current-build Secure Boot language aligned. Matrix remains operator history.

### Verification

- Focused pytest: 216 passed, 12 skipped (`final-pytest.txt`)
- `cd desktop && go test ./...`: ok
- Ruff on touched Python: all checks passed
- AT-SPI/Orca: 2 passed under `dbus-run-session` + Xvfb 72 DPI
- Unpackaged `--version`: honest stub (`version-unpackaged.txt`)
- No `nwipe` on a real disk. No ISO built.

### What Jack still must do (if Done requires media proof)

1. Authorize a manufactured ISO/USB image and confirm START-HERE.html plus `build-identity.json` on the FAT root match the squashfs identity.
2. Keep this card **In progress** until that image exists if that is the Done bar. Local product/tests for this ticket are complete.
3. No ISO release from this work.

### Confirmations

- Fail-closed disk-safety language unchanged.
- Identity mismatch is labeled, not used to invent a restart path.
- Notion remains **In progress** unless Jack treats local injection tests as sufficient for Done.
- MCP Notion tools were not available in this Grok CLI session.

Coordinator: paste this block into the #60 page Details.
