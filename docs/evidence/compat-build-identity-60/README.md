# #60 — Match compatibility guidance to the USB build

**Status:** In progress (implementation follows this baseline).
**Branch:** `feat/match-compat-to-usb-build` @ `0f9208111b2dd02b7237a9f133932dc01f546b36` off `origin/main` `4c26217877047abe244bd3ef9266a1ced1db5491`
**PR:** https://github.com/BeamoINT/beamo-wipe/pull/44
**Date (UTC):** 2026-09-15
**Safety:** Fake disks / dry-run only. No `nwipe` against a real disk. No manufactured ISO in this session.

## Problem

Customers opening this USB see startup and compatibility text that is not tied to
the image they are holding. Build identity is already injected into the live
squashfs as `/usr/share/beamo-wipe/build-identity.json`, but:

- `helper/index.html` / `START-HERE.html` show no USB build/version.
- The desktop launcher footer shows the wrapper version only (`development` until
  ldflags), not the USB image `build_id` / status.
- Operator docs still mix current-media facts with development-image history
  (unsigned-image language vs signed Debian EFI on this image).

The customer must not be asked to interpret the compatibility-matrix changelog
to know what *this* USB supports.

## Baseline (before product edits)

Recorded on this checkout, fake devices only:

| Gate | Result | File |
| --- | --- | --- |
| Focused pytest (identity, helper, copy, matrix, diagnostics, live image, launcher readiness, USB readback) | **186 passed, 12 skipped, 0 failed** in 13.43s | `baseline-pytest.txt` |
| `cd desktop && go test ./...` | **ok** | `baseline-go.txt` |

Source gaps at `4c26217` (inspected, not yet edited):

- Helper has no `#this-usb` identity card and no “not a manufactured USB image” stub.
- Desktop web has `#version` only; no dedicated build-id fields.
- Live app `--version` is wrapper version only; support JSON already carries injected identity when the live file exists.

Skipped environments: manufactured ISO / USB `.img` / QEMU / physical PCs. Jack has not authorized an ISO release.

## Measurable acceptance criteria

1. **Reproducible injection.** One packaging path writes the existing
   `build-identity.json` keys (`source_commit`, `source_sha256`, `build_id`,
   `source_dirty`) at image build time. The same payload is copied onto the
   FAT-visible USB root and substituted into offline helper HTML. Repeating the
   writer with the same inputs yields byte-identical JSON. Hosted production
   still refuses `build_id=local` and dirty source without `ALLOW_DIRTY`.
2. **Honest local/dev stub.** Git-tracked `helper/index.html` (opened from a
   checkout or `--helper`) is labeled **not a manufactured USB image**. Desktop
   preview / missing JSON uses the same honest labeling. Never implied to be a
   release stick.
3. **Offline visibility.** After injection, helper/`START-HERE.html` shows
   plain-language identity first and technical IDs in dedicated fields
   (version, release build, source commit, build status). Desktop launcher help
   and footer show the same fields from the USB JSON when present, or the stub
   when absent. No network, no `<script>` in the helper.
4. **Support export.** Wipe evidence, result summary, and startup diagnostics
   keep the existing identity fields. Diagnostic README names the customer
   identity line. Schema of `diagnostic.json` is unchanged.
5. **Guidance matches this build.** Helper, desktop help, and live “What”
   copy describe **this** image’s supported story (x64 Windows/Linux USB boot,
   signed Debian EFI, no Apple Silicon / Chromebooks, no Secure Boot bypass).
   They do not dump matrix history (`BF-00x`, `0.1.0` ISO hashes, changelog).
   Older media already defined in-repo: desktop still accepts a USB layout
   **without** `build-identity.json` (pre-identity sticks); guidance may say
   older sticks can differ; no new platforms are claimed.
6. **Fail-closed unchanged.** Boot-USB exclusion, confirm gates, nwipe flags,
   and media-layout required files (`START-HERE.html`, squashfs,
   `desktop-build.json`, `BOOTX64.EFI`) stay as they are. Identity mismatch is
   labeled, not used to invent a restart path.
7. **Tests.** New regressions fail if identity is missing/mismatched, if the
   source helper loses the stub, if injected helper still says “not packaged”,
   or if customer surfaces drift from the canonical current-build story.
   Existing helper Win10/Win11/BitLocker/offline tests still pass.

Done only when 1–7 are evidenced below. Notion stays In progress until then.

## Verification (after implementation)

| Gate | Result | File |
| --- | --- | --- |
| Focused pytest (identity, helper, copy, matrix, diagnostics, live image, launcher, USB readback) | **216 passed, 12 skipped, 0 failed** in 14.33s | `final-pytest.txt` |
| `cd desktop && go test ./...` | **ok** | `final-go.txt` |
| `python3 -m ruff check` on touched Python | All checks passed | `ruff.txt` |
| Unpackaged `PYTHONPATH=src python3 -m beamo_wipe --version` | Honest stub; technical IDs “not packaged” | `version-unpackaged.txt` |
| AT-SPI/Orca (`dbus-run-session` + Xvfb 72 DPI) | **2 passed** (`test_atspi_exposes_quick_zero_result_to_external_client`, `test_orca_announces_every_result`) | Hosted-style wrap; bare pytest without the session bus fails those two as expected |

Full `python3 -m pytest` on this VM without `dbus-run-session` reported those two AT-SPI failures and otherwise passed. Re-run under `dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72"` is green for them.

### Acceptance mapping

1. **Injection:** `scripts/build-iso.sh` still writes `build-identity.json`, then `inject_helper_html` fills helper + START-HERE, and copies the JSON to the FAT-visible binary include. Writer remains `write_injected`. Tests: `test_iso_builder_copies_then_injects_helper`, `test_inject_production_helper_replaces_stub`.
2. **Stub:** Git helper contains `SOURCE_STUB`. Desktop preview/missing JSON: “not from a manufactured USB image”. App `--version` without injection: “This session is not a manufactured USB image.”
3. **Offline visibility:** Helper `#this-usb` card + dedicated `dl.build-ids`. Desktop help `#identity-*` fields filled from API. No helper `<script>`.
4. **Support:** Diagnostic README includes `sentence_from_application`. Evidence JSON schema unchanged.
5. **This-build story:** `compat_story.py` phrases pinned in helper, desktop help, and `WHAT_BULLETS`. History-dump phrases banned on those surfaces. Older media: Go `TestMissingBuildIdentityDoesNotRefuseMedia`.
6. **Fail-closed:** Media required files unchanged. Identity mismatch is labeled (`TestUSBIdentityMismatchIsLabeledNotRefused`).
7. **Tests:** `tests/test_compat_story.py`, `desktop/identity_test.go`, helper/copy updates.

### Skipped

- Manufactured ISO / USB `.img` / QEMU / physical PCs — Jack has not authorized an ISO. Injection is unit-tested against the builder’s copy+inject functions, not a built image.

## Notion

Keep **In progress** until a manufactured image is built if Jack wants ISO-level proof. Local acceptance for identity injection, offline helper/desktop visibility, support line, and current-build copy is met. Coordinator: paste `NOTION-HANDOFF.md`. MCP Notion tools were not available in this Grok CLI session.

## Intentional surface differences

| Surface | Identity | Compatibility story |
| --- | --- | --- |
| Helper / START-HERE (offline, no JS) | Injected HTML + FAT `build-identity.json` | Full current-build startup guidance |
| Desktop launcher | Reads FAT JSON at runtime; ldflags version/commit as a cross-check | Same current-build story; readiness checks stay pre-restart only |
| Live wizard (Tk Show more / gallery) | Customer sentence from `load_build()`; technical IDs in support export | Same platform/Secure Boot sentences; console/accessible keep shorter WHAT text and point to support export for IDs |
| Support export | Existing JSON identity fields | Not a customer boot guide |

## Not in scope

- Building or publishing an ISO/USB image
- Changing discovery, nwipe flags, or desktop restart authorization
- Rewriting `docs/compatibility-matrix.md` history tables
- Physical acceptance (#111)
