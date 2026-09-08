# Beamo Wipe interface refinement — 2026-09-08 UTC

The Tk wizard, browser preview, desktop launcher stylesheet, and offline boot
helper now share a quieter visual treatment. The source changes were developed
in an isolated snapshot of the existing working checkout, then applied only
after checking that each original file still matched its captured baseline.
Existing safety and bug-fix work was preserved. Nothing was published or released.

## Design

- White canvas, navy Beamo identity, amber step progress, and restrained blue
  actions (`#244A73`). Muted text is `#4C5B6B`, information surfaces `#F3F5F7`,
  and separators `#D8DFE6`. Existing destructive/error colors remain distinct.
- Smaller headings, explicit pixel font sizes, eight-pixel corners, flat cards,
  and no selection halos or decorative card shadows. Installed fonts keep the
  live wizard usable offline; no new runtime dependencies or remote assets.
- Content follows its heading instead of floating in the center of the page.
  Utility actions use one consistent secondary row above Back and Continue.
- Disk capacity and type have a stable right edge; full model and serial text
  wrap to their available width. They are never abbreviated or truncated.
- Show more / Show less works with Enter and Space, has visible focus, and
  preserves focus after rebuilding the view. Utility controls also honor Enter.
- Informational excluded-device inventory stays read-only in the picker’s
  scroll area, leaving space for selectable disks on short screens. Row geometry
  updates refresh the scroll bounds so keyboard selection remains visible.
- Browser layouts accommodate small screens and respect reduced motion.
  The launcher uses the same restrained palette and clearer restart panel.
  The boot helper uses readable sections instead of stacked shadow cards.

The alternate GTK screen-reader view retains its native system controls.
The erase engine, eligibility rules, boot protection, ownership/token gates,
countdown, and explicit final erase requirement were not changed by this work.

## Validation

- New native tests reproduced clipped long models/serials and the absence of a
  keyboard details control before implementation. All five initial new tests pass. An additional native regression passes for
  keyboard traversal to Save report without requesting shutdown.
- Local fake-device gate: **1,472 passed, 159 skipped, 2 deselected**. The skipped
  cases require GUI/platform facilities. The two deselected tests require
  `lb config` outputs, as documented in the project guide. This fresh snapshot
  did not reuse the shared checkout’s stale generated chroot package.
- Native macOS Tk 9 / Python 3.14 UI gate: **164 passed, 1 skipped** at 1024×740
  and 1280×820. The one skip requires an isolated X11 server for physical key
  injection. Two earlier runs had transient window/focus failures; the final
  complete unchanged-source run passed. See [native test output](evidence/ui-redesign-20260908/native-tests.txt).
- Browser review: 15 wizard states at widths 1280, 1024, and 390; all 45 checks
  had no horizontal page overflow or offscreen footer buttons, and no JavaScript
  errors. Details retained keyboard focus after Enter. The launcher and helper
  also passed width checks at 1024 and 390. Launcher API responses were synthetic;
  this was a rendering check, not a restart or firmware test.
- Changed Python files pass Ruff; shared palette contrast checks pass; the diff
  passes whitespace validation.
- Hosted Linux tests: **1,673 passed, 12 skipped, 2 deselected** in an isolated
  X11 session. Lint, preview, and negative safety checks passed.
- The initial hosted build `01ff75e3-3086-4214-b7ec-a4ea134ee253` passed all
  test phases, then stopped at ISO provenance generation because the isolated
  snapshot lacked `remote.origin.url`. The snapshot now carries the verified
  checkout origin metadata. The second build
  `609ff2b7-08cb-464f-a85e-2903dbffeabf` passed ISO/provenance generation, then
  exposed a QEMU driver assumption: one Tab from Shut down previously reached
  Save report, but the new accessible Show more control adds a Tab stop.
  A native traversal regression verifies the two-Tab path and intercepted report
  save without shutdown. The driver and its action-sequence regression now match.
  Final build [`da8f1338-7acb-4824-af55-9a3faf3217b4`](https://console.cloud.google.com/cloud-build/builds/da8f1338-7acb-4824-af55-9a3faf3217b4?project=beamo-wipe)
  finished **SUCCESS**. ISO/provenance, BIOS, UEFI, BIOS USB, UEFI USB, and
  enrolled Secure Boot USB checks passed. The shipped wizard zeroed only the
  disposable guest target and exported a report that passed clean-FAT,
  completion, checksum, read-only verification, and unmount checks.
  [Boot evidence](evidence/ui-redesign-20260908/hosted-boot-results.txt) and the
  [build receipt](evidence/ui-redesign-20260908/cloud-build.json) record the result.
  Publication was explicitly disabled; build binaries remained ephemeral. Temporary validation commit `25d823f` contains the UI, harness update,
  and pre-existing working changes. It is not a published repository revision.

[Source hashes](evidence/ui-redesign-20260908/source.json) verify that the ten
changed checkout files match the submitted validation snapshot. All 253 source
files in that snapshot also matched the working checkout at closeout. Source baseline:
`f7b6490036d62281e2133da642557cee6710f081` plus the captured working changes.

## Preview evidence

These screenshots show the browser mirror, not Linux boot-image screenshots:

- [Disk picker](evidence/ui-redesign-20260908/pick-preview.png)
- [Disk confirmation](evidence/ui-redesign-20260908/confirm-preview.png)
- [Method choices](evidence/ui-redesign-20260908/method-preview.png)
- [Desktop launcher with synthetic readiness](evidence/ui-redesign-20260908/launcher-preview.png)

No real disk was erased, no PC was restarted, and no physical USB or firmware
configuration was newly certified. Publication remains a separate action.
