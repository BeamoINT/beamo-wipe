# Production completion handoff — 2026-09-12

Status: **local verification passed; hosted production verification blocked**.
Author: Codex. Branch: `feat/qemu-three-method-journeys`.
Starting HEAD: `cd806f403d3fe8c105da5e4f53a5b1c7a93100b3`.
This is a dirty working-tree result, not a release or a verified ISO.
The inherited staged and unstaged work remains in place; this continuation
did not stage, commit, push, merge, publish, or change production.

## Work completed locally

- Finished the inherited startup, asynchronous disk refresh, long disk identity,
  and final-review UI changes. Fixed stale synchronous test assumptions,
  leaked test windows, cross-interpreter checkbox variables, unnecessary text
  splitting, and an actual long-review clipping problem. Long final reviews
  now have a scrollbar; rendered tests verify that the final warning is visible
  when scrolled and that the safe footer action remains accessible.
- Connected execution receipts to the real hosted commands and retained logs.
  Tests use JUnit outcome counts; other required gates count one executed phase.
  Source/build identity, receipt slot identity, aggregate digests, duplicate
  receipts, and retained log hashes are checked. Image inventory comes from
  the mounted squashfs package database and configured apt sources.
- Separated preliminary artifact provenance from strict release verification
  to remove the circular dependency on QEMU evidence before an ISO exists.
  Finalization still requires every required gate to pass and rejects changed
  artifacts. A skipped phase cannot qualify a release.
- Completed the QEMU method journeys, including the new keyboard screen.
  Every method now runs twice on separate bounded fixtures. Corrected the
  parser against pinned nwipe v0.42 log syntax; it requires ordered write and
  verification phases. Full target readback rejects I/O errors and untouched
  prefill. Report checks bind method wording and source/build identity.
  QEMU argv rejects host device paths and requires networking disabled.
  Cleanup preserves backing files if verified loop detachment fails.
- Connected the publisher to actual per-method and repeat evidence filenames,
  required receipts and package inventory; hardened signing-key file identity
  checks. New publication remains blocked without an enrolled signing key.
- Resolved the inherited type errors without changing disk authorization rules.

## Measured local verification

| Check | Result |
| --- | --- |
| Full suite, `DISPLAY=:0 python3 -m pytest -ra --junitxml=…` | **2,238 passed, 14 skipped**, 157.93 seconds |
| Final QEMU repetition and hosted wiring tests (including the subsequently added repetition regression) | **20 passed** |
| Focused evidence/QEMU/signing regression batch | **44 passed** |
| Rendered UI regression batch | **233 passed, 1 skipped** |
| Full Ruff, security selectors, compileall, ShellCheck | Passed |
| mypy | Passed, 39 source files; untyped function bodies retain existing default scope |
| Go launcher `go test ./...` and `go vet ./...` | Passed locally, Go 1.26.8 on macOS |
| Web, console, and helper previews | Passed with fake disks and no automatic browser opening |
| Negative boot-safety mutation | Passed in an isolated temporary copy: broken guard failed, restored guard passed |
| `git diff --check` | Passed |

The full-suite skips are one missing Linux `gi` accessibility runtime, one
physical-key injection case requiring an isolated X server, and twelve
regular-file FAT32 cases requiring dosfstools/mtools. These are unmet local
platform checks, not proof that the hosted equivalents pass. The ignored
live-image Python staging was refreshed from source for source-layout tests;
no ISO was built on this Mac.

Temporary detailed receipts (may expire):

- `/private/tmp/beamo-wipe-production-final.log`, SHA-256
  `46d1661aaa48a58eb1fc593082ec7b50f2c3115496c03be16e2f86bfb2a0975f`.
- `/private/tmp/beamo-wipe-production-final.xml`, SHA-256
  `6d3b2cd070d75d990109dda9597f75f21794201f8edceae89330921adb7a20fa`.
- `/private/tmp/beamo-wipe-negative-final.log`, SHA-256
  `aa2d119abb3373e1d70d4f75130e50a59c0e793034b030ba3addf665604f1e87`.

Working-tree snapshot digest, including tracked and nonignored untracked files
but excluding this report:
`ea7ffe5a0a9e9cf7ef82ac3b84ecf15e99e3176720befe51d9a3ad8275c7aefb`.
Computed as SHA-256 of compact UTF-8 JSON containing sorted `[path, SHA256]`
pairs for regular files from `git ls-files -c -o --exclude-standard -z`.
This identifies the local work only; it is not a clean release commit.

## Blocking checks and next action

`./scripts/ci-cloud.sh --project beamo-wipe` cannot submit because the configured
Google account returns **Reauthentication failed; cannot prompt during
non-interactive execution**. The alternate saved personal account returns
**PERMISSION_DENIED** for this project. No hosted build ID was obtained for
these changes.

The operator must refresh the authorized login with `gcloud auth login`.
Then prepare an isolated, source-identified verification snapshot without
disturbing the shared index, run the complete secret-free Cloud Build gate,
and investigate any amd64 ISO, accessibility, filesystem, nwipe, or QEMU
failure until it passes. Record the exact source, build ID, image hashes,
all repeated journeys, report readbacks, and cleanup. Verification-only
Cloud Build artifacts are ephemeral; stdout and local worker diagnostics do
not imply a durable public evidence upload.

The inherited instruction to commit/push only after gates and not release or
publish remains in force. Publication additionally requires the separately
authorized release-key enrollment/custody setup: `packaging/release-keys/keys.json`
currently contains no production key. Signing tests use disposable keys.
No Windows 10/11, physical hardware, real-disk erasure, or new production
release acceptance is claimed by this local handoff.
