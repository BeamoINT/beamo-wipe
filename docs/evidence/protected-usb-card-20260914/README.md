# Protected Beamo USB card — #61

Source baseline: `9210aa32f1598936b752f4662ed926b1f3b60044` (main and
origin/main matched after fetch). Independent branch:
`feat/protected-beamo-usb-card`; no launcher-readiness branch merged.
The implementation source is the commit containing this report.

## Baseline and acceptance criteria

Read AGENTS.md and all indexed `.ai/memory` notes, traced discovery → wizard →
Tk/GTK/console/gallery, and rendered the shipped Tk interface with demo disks.
The native picker omitted the boot USB; the browser inventory included it under
Other detected devices. `baseline-tk.png` records the native picker before editing.

Required outcomes established before implementation: a separate protected card
with model, capacity, connection and serial/hardware ID; no erase action; no
change to safety-owned eligible paths; fail closed with unidentified or
conflicting boot media; readable long identities at 1024×740 and 1280×820;
read-only console and accessible semantics; aligned preview and documentation.

Initial full baseline: 2 failed, 2411 passed, 37 skipped in 333.95 seconds.
The coordinator removed a stale gitignored START-HERE.html staging artifact.
Rerunning `tests/test_helper_boot_guidance.py` then produced 13 passed and one
Chrome render timeout. The coordinator explicitly authorized treating that
specific environmental timeout as nonblocking after one retry. It is excluded
by name from the final local gate; no test code was weakened for that exception.
Five new protected-card regressions were run before implementation and failed
on the original missing presentation properties.

## Implementation and intentional differences

- Tk reuses the existing protected `_disk_row` branch and shared wrapping
  identity widgets. The card precedes eligible disks inside the scrolling picker;
  the empty screen also scrolls so unusually long identities cannot hide actions.
  It has no click binding and is absent from `_pick_cards` and target navigation.
- GTK uses its existing focusable, noneditable, character-wrapping text reader
  ahead of Select buttons. The full protected wording and identity form its
  accessible name. This is intentionally a text reader rather than a button.
- The gallery uses the same protected copy and existing boot card, with a named
  region role and no selection handler. The existing display-only inventory
  filter moved unchanged from Wizard to inventory.py so the gallery can omit
  the confirmed boot device from Other detected devices too.
- Plain console prints the protected identity separately and without a target
  number. The small curses console shows protected status and B for a paged,
  read-only identity view; O continues to show other exclusions. This preserves
  room for eligible disk identities at 80×24. The legacy empty_detail property
  and empty-console detail remain available for compatibility.
- Additional excluded paths (including aliases of the boot device) keep their
  existing exclusion explanations; the card identifies the confirmed boot media.
  Optical media retain the separate “Beamo boot disc” wording.
- The offline helper intentionally has no live disk inventory and is unchanged.
  Packaging already installs these Python sources; no packaging or boot logic
  changes, ISO build, release, or publication are part of this presentation task.

Discovery, safety filtering, confirmation, execution and nwipe flags are unchanged.
All exercised disks were fake; no real-disk nwipe was run.

## Verification

Commands and results:

- Full suite: `dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" ./scripts/test-all.sh -k 'not test_helper_renders_both_windows_paths_on_small_and_desktop_displays'` — **2529 passed, 28 skipped, 1 deselected in 345.96 seconds**.
  The 28 repository skips cover optional/environment-specific checks; the sole
  explicit deselection is the coordinator-authorized system Chrome helper test.
- `BEAMO_GATE_CHILD=1 ./scripts/ci-hosted.sh lint` — passed twice, including
  compile, blocking shell/security lint, full Ruff and mypy. The existing
  release-manifest regex triggers the script's advisory TODO warning.
- `BEAMO_GATE_CHILD=1 ./scripts/ci-hosted.sh preview` — passed (web, console,
  helper generation; fake disks).
- `BEAMO_GATE_CHILD=1 ./scripts/ci-hosted.sh negative` — passed: the deliberately
  broken boot guard was rejected, safety.py was restored byte-for-byte, and
  the clean safety test passed. Ran separately from the full suite.
- Protected model/browser/inventory/console targeted run: 62 passed.
- Tk protected-card matrix: 8 passed (two window sizes, happy/empty, normal/long
  model and serial); no clipping or off-window controls, no click handlers on
  protected card descendants, no protected target in the navigation map.
- GTK/ATK runtime suite under the same Xvfb/DBus wrapper: 85 passed, including
  noneditable accessible identity and real Orca speech-output regressions.
- `git diff --check` — passed; full source/test/documentation diff reviewed.

The first implementation-wide run found stale gitignored Python staging:
1 failed, 2431 passed, 37 skipped, 1 deselected. Refreshed only Git-tracked Python
sources in the existing staging directory, matching the builder's copy loop;
`test_staged_chroot_package_matches_src` then passed. This neither built an ISO
nor refreshed its generated build identity; staged files are not a release
artifact. The full suite was rerun after staging and test dependencies were fixed.

Screenshots: `after-tk-happy.png`, `after-tk-empty.png` (1024×740, Xvfb 72 DPI),
`after-web.png` (1280×1160, Playwright Chromium), and `after-gtk.png`
(800×600 window on Xvfb). Native and browser images
were visually inspected. Browser tests additionally inspect region semantics,
click isolation, blocked/empty cases and long fields.

## Environment and remaining limits

The installed system Chrome stalls in the existing helper screenshot test.
Playwright's separate Chromium runtime rendered and tested this feature
successfully. Pillow and GTK introspection packages were installed in this
workspace environment for screenshots and real accessible-interface testing.
GTK/ATK runtime suite: 85 passed, including the existing Orca speech-output
integration test after installing the repository-prescribed Orca dependencies.
No physical USB, live ISO, physical speaker output, Cloud Build or KVM verification
is claimed; this task changes Python presentation, not ISO/x86 build machinery.
