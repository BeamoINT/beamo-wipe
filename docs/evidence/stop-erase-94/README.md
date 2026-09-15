# Stop erase task #94 — baseline handoff

Source: main 9210aa32f1598936b752f4662ed926b1f3b60044.
Branch: feat/stop-erase-unmistakable, created from that source with a clean checkout.
No feature branches merged. No implementation changes, commits, or pushes.

Read AGENTS.md and .ai/memory/MEMORY.md plus product constraints and visual verification notes. Inspected Wizard stop claims, runner-result handling, progress presentation, shared outcomes, Tk, GTK accessibility, console fallback, browser gallery, and related regression tests.

Baseline command:
```sh
dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest
```
The required baseline gate reported failures; implementation is stopped under the user's explicit gate instruction. The final pytest output is recorded alongside this file when available.

Rendered current-source Tk and GTK views using make_demo_wizard and fake disks only. Regenerated the browser gallery using BEAMO_WIPE_NO_OPEN=1 ./preview --web and inspected it with Chromium. Screenshots alongside this file show the baseline. No wipe process was launched by this inspection.

Findings:
- Tk and GTK say Cancel erase and do not explain that stopping cannot restore erased files.
- Escape directly requests cancellation; there is no deliberate user confirmation.
- Browser working preview has no stop control.
- Existing controller claims already reject duplicate stop requests, wait for confirmed exit/cleanup, preserve actual late completion, and leave uncertain stops active with a warning.

Acceptance criteria established before implementation:
1. Explicit irreversible-data warning before requesting a stop and on interrupted/stopped outcomes.
2. User confirmation with a safe keep-erasing choice; repeated click/key input cannot accept the confirmation accidentally.
3. Prominent and distinct stopping, stopped, and stop-unconfirmed presentations in Tk, GTK, console, and preview; documented intentional differences.
4. Confirmation dismissals leave the current erase running and polling; completion during confirmation preserves the actual outcome and rejects stale actions.
5. Duplicate stop requests, process races, kill/cleanup failure, late completion, stale progress, and simulated abrupt power/process loss never yield invented success or a false stopped claim.
6. Reports preserve honest existing evidence contracts; no disk selection, engine flags, or boot exclusion regressions.
7. Add failing-before/passing-after regression tests, render affected interfaces, pass the required local suite, then inspect full diff before commit/push.

Skipped: implementation, new regression tests, post-change checks, ISO/QEMU/hardware environments, cloud builds, release/publishing. No real-disk nwipe was run.

Final gate result: exit 1; 2 failed, 2507 passed, 28 skipped in 384.35 seconds.
- tests/test_helper_boot_guidance.py::test_helper_renders_both_windows_paths_on_small_and_desktop_displays: Chrome did not finish rendering within 40 seconds; diagnostic output includes unavailable D-Bus/a11y sockets.
- tests/test_live_image.py::test_staged_chroot_package_matches_src: pre-existing staged gallery.py differs from src/beamo_wipe/gallery.py.

No gate failures were bypassed or repaired. Full failure details: pytest-result.txt.
