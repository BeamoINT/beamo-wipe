# Production completion handoff — 2026-09-12

Status: **hosted qualification in progress after authentication refresh**.
Author: Codex. Branch: `feat/qemu-three-method-journeys`.
Starting HEAD: `cd806f403d3fe8c105da5e4f53a5b1c7a93100b3`.
The shared checkout and index remain preserved. Qualification commits live
in a separate clean clone. No merge, release, or production change was made.
The last completed (failed) hosted attempt used source
`620039dab010b0f65c274ff5c020bfbca768298e`, build
`14a359e6-fb3d-48d0-8c45-284a3b844fd6`.

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
| Full suite, `DISPLAY=:0 python3 -m pytest -ra --junitxml=…` | **2,260 passed, 17 skipped**, 196.68 seconds |
| Final QEMU repetition and hosted wiring tests (including the subsequently added repetition regression) | **20 passed** |
| Focused evidence/QEMU/signing regression batch | **44 passed** |
| Rendered UI regression batch | **233 passed, 1 skipped** |
| Full Ruff, security selectors, compileall, ShellCheck | Passed |
| mypy | Passed, 39 source files; untyped function bodies retain existing default scope |
| Go launcher `go test ./...` and `go vet ./...` | Passed locally, Go 1.26.8 on macOS |
| Web, console, and helper previews | Passed with fake disks and no automatic browser opening |
| Negative boot-safety mutation | Passed in an isolated temporary copy: broken guard failed, restored guard passed |
| `git diff --check` | Passed |

The full-suite skips are one missing Linux `gi` accessibility runtime, three
Linux kiosk fullscreen cases, one physical-key injection case requiring an
isolated X server, and twelve
regular-file FAT32 cases requiring dosfstools/mtools. These are unmet local
platform checks, not proof that the hosted equivalents pass. The ignored
live-image Python staging was refreshed from source for source-layout tests;
no ISO was built on this Mac.

Temporary detailed receipts (may expire):

- `/private/tmp/beamo-wipe-production-closeout.log`, SHA-256
  `eacde0f41012741ec40451abb0bcc41a17ea4eeb3ca76de11b4fa85fa6e4a0b6`.
- `/private/tmp/beamo-wipe-production-closeout.xml`, SHA-256
  `57ac965dd6888ccf88d7c2f9f662372ebac6fee7a4b980a9d0edfa9f35dc5daa`.

- `/private/tmp/beamo-wipe-production-final.log`, SHA-256
  `46d1661aaa48a58eb1fc593082ec7b50f2c3115496c03be16e2f86bfb2a0975f`.
- `/private/tmp/beamo-wipe-production-final.xml`, SHA-256
  `6d3b2cd070d75d990109dda9597f75f21794201f8edceae89330921adb7a20fa`.
- `/private/tmp/beamo-wipe-negative-final.log`, SHA-256
  `aa2d119abb3373e1d70d4f75130e50a59c0e793034b030ba3addf665604f1e87`.

Historical pre-login working-tree snapshot digest, including tracked and nonignored untracked files
but excluding this report:
`ea7ffe5a0a9e9cf7ef82ac3b84ecf15e99e3176720befe51d9a3ad8275c7aefb`.
Computed as SHA-256 of compact UTF-8 JSON containing sorted `[path, SHA256]`
pairs for regular files from `git ls-files -c -o --exclude-standard -z`.
This identifies the local work only; it is not a clean release commit.

## Authorization and qualification boundaries

The first continuation stopped at expired Google authentication. The user
refreshed the authorized login, and Cloud Build submissions now work. The
individual attempts and their measured outcomes are recorded below.

The operator refreshed the authorized login on 2026-09-12. The continuation
prepared an isolated, source-identified verification snapshot without
disturbing the shared index. Continue the complete secret-free Cloud Build
gate and investigate any amd64 ISO, accessibility, filesystem, nwipe, or QEMU
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

## Hosted continuation after login refresh

The shared checkout/index remains preserved. Verification commits live in
`/private/tmp/beamo-wipe-qualification-9lrqf315`, with the canonical origin URL
and clean source state. These commits have not yet been pushed.

- `b3d6fb95c54e84d6aea7e64982304546122ec21f`, build
  `abbfbd29-0d5c-4c0e-8504-92e69dadf64a`: lint, preview and desktop gates
  passed; Linux Python gate reported 2,310 passed, 15 skipped and 10 failures.
  Report-help controls exceeded Linux display width and a helper test assumed
  preexisting generated ISO staging. Fixed wrapping/minimum reader width in
  Tk and GTK; the helper test now executes the real staging copy commands in
  disposable directories. Focused local rendered checks: 78 passed; corrected
  helper staging test: 1 passed.
- `456f716`, build `6608d97a-cd2f-4b22-8808-7607d8b542dc`: **2,320 Python
  tests passed, 15 skipped**, with lint, preview, native Linux launcher,
  Windows cross-compilation, launcher fuzzing, negative safety, and ISO gates
  passing. ISO size 563,085,312 bytes; SHA-256
  `4a21a4803f3e70e3fd5ffa9630228cf859e106c1af50134dac862e06a3f8131f`.
  QEMU inspection stopped before erasure on a verifier false negative:
  Syslinux's `^troubleshoot` hotkey markup did not match the plain-text grep.
  Reproduced using the actual shell gate and menu fixture, then corrected;
  the regression also proves a missing troubleshooting entry still fails.
- `bf16a0a`, build `33b9e211-bde1-4367-ae2b-199a7c7a893b`: **2,321 Python
  tests passed, 15 skipped**; all preceding gates and ISO construction passed.
  The image menu, package/permission, crash-cleanup and fake-disk safety checks
  passed. All three pinned nwipe methods passed twice on isolated loops.
  The first BIOS guest timed out before the keyboard screen. Investigation
  found that the inherited template used `MENU HELP`, which changes a boot
  entry into a help-file action; it now uses `TEXT HELP` / `ENDTEXT` for inline
  documentation, with an image-level guard and regression. See
  [Syslinux menu documentation](https://kernel.googlesource.com/pub/scm/boot/syslinux/syslinux/+/ae853e99a7aed22cb28b387e1e3cb32dbf1ab8fa/doc/menu.txt).
  Safe startup marker coverage was also expanded; raw serial data remains
  private. These fixes passed 56 focused tests, ShellCheck, and Ruff.
- `b717379`, build `569fe476-922a-470d-9cdf-ac93e374bbea`: full gate submitted
  with publication disabled. **2,322 Python tests passed, 15 skipped** and all
  pre-QEMU gates passed. The image checks and six direct engine checks passed.
  BIOS then reached kiosk startup but stalled in the new Tk startup screen:
  its completion callback was defined but never scheduled. Two bounded real
  Tk regressions reproduced both successful and failed workers being ignored.
  Scheduling the callback fixed both; 97 startup/refresh tests and 112 evidence,
  QEMU-diagnostic and report-workflow tests passed, with lint/type/shell checks.
- `07e9fd3`, build `bdee61c6-658b-41d7-80f6-7c5f21c23ee0`: **2,324 Python
  tests passed, 15 skipped**, all pre-QEMU gates passed, and all six direct
  engine checks passed. BIOS completed the Everyday wizard, whole-target
  overwrite readback, and report export/readback/unmount. Host verification
  then rejected the newer completion schema introduced by the inherited
  owner-summary/privacy work. Updated the strict schema and declarations;
  executable regressions now run the host verifier against production bundles
  for all three methods, with and without privacy copies, and reject a
  tampered declaration. Safe progress markers and final artifact digests now
  reach build logs. Subsequent reruns are recorded below.
- `73e039c`, build `3e643a6a-2771-4fa7-9f88-29eb5357e9f7`: cancelled
  immediately after submission to include a newly reproduced cleanup failure.
  Five disposable shell regressions proved that failed loop detachment or
  unmount could previously return success. Cleanup now preserves failure and
  signal status and fails qualification on teardown errors; all 12 failure/
  success and original-exit-status combinations pass. Attached target image
  preservation remains verified.

Builds are available in Google Cloud Build, project `beamo-wipe`, using the
IDs above. A successful ISO build alone is not completed wipe qualification.

- `620039dab010b0f65c274ff5c020bfbca768298e`, build
  `14a359e6-fb3d-48d0-8c45-284a3b844fd6`: **2,341 Python tests passed,
  15 skipped**, with all pre-QEMU gates and six direct engine checks passing.
  Both full Everyday journeys passed target readback, report schema/wording/
  checksums, clean FAT, and unmount checks. The first Three overwrites guest
  stopped before erasure with repeated disk-screen redraws and no key-release
  acknowledgement. A bare-X11 native Linux regression reproduced the kiosk
  using content-sized 800x680 geometry on a 1024x768 display because no window
  manager honored the fullscreen hint. Explicit display geometry now fixes
  both startup and wizard windows. The fullscreen stability and real X11
  key-release/repeat checks pass. The full native Linux Tk/startup batch
  passed 177 tests; startup/fullscreen checks additionally passed at 800x600
  and 1600x1000 (5 per display). The disposable ARM Linux container exercised
  only fake disks and was removed. Full amd64 qualification must be rerun.

The first post-fullscreen local run aborted inside macOS Tk when the new
Linux-kiosk fullscreen test requested a native macOS fullscreen window. That
case now runs only on an explicitly isolated Linux X server, where it passed
at both tested resolutions. The local full suite is rerunning with those
platform skips explicit. This is not macOS fullscreen acceptance.

Final local suite after the fullscreen correction: **2,260 passed, 17 skipped**,
196.68 seconds. Ruff, mypy (39 source files), and diff checks pass.
- `/private/tmp/beamo-wipe-kiosk-closeout.log` SHA-256: `7fabff43eab76945afc4ab5e6c7ac09008f65f6d9ee25333635cdb235391a48f`.
- `/private/tmp/beamo-wipe-kiosk-closeout.xml` SHA-256: `f179eb02e96133577b218fc2dff3ab733f756e2a435962d8290041158a2f15d9`.
