# Backlog #63 — simple disk inventory count

Base: `main` at `67d1f8177a7a8b37a6faaa934873a8ad7e01d48f`.
Branch: `feat/disk-inventory-count`.

All execution uses demo/fake lsblk JSON and DryRunRunner. No real disk, no nwipe, no ISO.

## Baseline (measured on 67d1f81 before the change)

Happy demo (`discovery_for_scenario("happy")`):

- 3 eligible disks: `/dev/nvme0n1`, `/dev/sda`, `/dev/sdd`
- Confirmed boot USB `/dev/sdb` (Beamo Wipe, BEAMOUSB001)
- 1 other device: `/dev/loop0` (unsupported)

Empty demo: 0 eligible, same protected USB, 1 other device (`/dev/loop0`).
Blocked demo: boot not identified, no selectable disks, no other-device inventory.

Picker copy before the change (Tk and gallery pick-tools only):

- `3 disks available · Choose one disk` / `N disks available · 1 selected`
- Did not say available to erase, did not name protected Beamo USB, did not count other devices, and did not distinguish an unidentified list from a successful empty scan.

GTK, curses, and plain console had no shared inventory count. The offline helper has no live disk inventory.

New tests against that revision failed at collection (`count_summary` did not exist). Gallery HTML contained `Choose one disk` and the JS ternary `selectable().length === 1 ? "disk available"`.

## Acceptance (measurable)

1. **Zero eligible:** `No disks available to erase · Beamo USB protected` (never `0 disk`). Empty demo also counts the loop device: `· 1 other device not available`.
2. **One eligible:** `1 disk available to erase · Beamo USB protected`.
3. **Many eligible:** `2 disks available to erase · Beamo USB protected` and happy demo `3 disks available to erase · Beamo USB protected · 1 other device not available`.
4. **Protected media:** USB uses `Beamo USB protected`; non-USB boot uses `Beamo boot disc protected`. Unidentified boot never claims either.
5. **Excluded devices:** root Other detected devices are counted with English plurals. Nested partitions do not inflate the count. Exclusion reasons remain in Other detected devices. No excluded path becomes selectable.
6. **Unknown results:** `Disk list could not be confirmed. No disk is available to erase.` when boot identity failed closed. Capacity/eligibility uncertainty on excluded devices adds `Some devices could not be fully identified` without hiding reasons.
7. **Refresh:** `refresh_disks()` replaces the count from the new discovery (happy → empty → blocked).
8. **Plurals:** 0/1/n for eligible disks and for other devices. Product copy is English only.
9. **Screen-reader:** spoken form uses sentence separators. GTK exposes a focusable label whose accessible name is the spoken summary.

## Implementation

Display-only. `inventory.count_summary(discovery)` reads `selectable_disks` and `other_devices`. It never changes eligibility, confirmation, or nwipe flags.

Wizard properties: `inventory_count` (visual, middle dots) and `inventory_count_announcement` (spoken, periods).

### Intentional UI differences

| Surface | Count |
| --- | --- |
| Tk | Wrapping muted line in pick-tools (with Show more) and on the empty screen; blocked screen appends the unknown summary under the existing error. |
| Gallery | Same words from the Python payload (`role="status"`). Static per preview scenario; Check disks again is not simulated. |
| GTK | Focusable label with the spoken form, before protected identity / Select buttons. |
| Curses / plain console | Same visual words after the subtitle / before Eligible disks. |
| Offline helper | Unchanged; no live inventory. |

Selection state is no longer mixed into the count (`Choose one disk` / `1 selected`). The selected card still shows the choice. Disk identity, exclusion reasons, and fail-closed errors stay visible.

## Verification

Fake disks only.

- `tests/test_inventory_count.py` plus copy/console/gallery/Tk/GTK regressions.
- Focused non-browser inventory suites: **60 passed**, 1 skipped.
- `BEAMO_GATE_CHILD=1 ./scripts/ci-hosted.sh lint` — **PASS** (blocking compile/ruff/shellcheck). Advisory ruff/mypy findings are pre-existing.
- `BEAMO_GATE_CHILD=1 ./scripts/ci-hosted.sh preview` — **PASS** (web, console, helper; fake disks). Generated `web-preview/index.html` contains the shared summaries and not `Choose one disk`.
- `BEAMO_GATE_CHILD=1 ./scripts/ci-hosted.sh negative` — **PASS**.
- `python3 -m pip wheel --no-deps` — wheel contains `count_summary`.
- Chrome headless screenshots of the gallery: `web-pick-1280.png`, `web-pick-390.png`, `web-empty-1280.png`, `web-blocked-1280.png`.

Full local `./scripts/test-all.sh` on this Mac: **2592 passed, 522 skipped, 5 failed**. The five failures are environmental or leftover artifacts, not this change:

- `test_gtk_comparison_disclosure_is_read_only` — `gi` is not installed here.
- `test_helper_and_iso_start_here_are_identical` — gitignored `packaging/live/config/includes.binary/START-HERE.html` is stale vs `helper/index.html` (helper was not edited).
- two Microsoft citation URL checks — HTTP 403.
- `test_staged_chroot_package_matches_src` — gitignored live-build `includes.chroot` copy is already drifted (first reported file `support_export.py`, not part of this task).

Tk/GTK runtime tests skip without DISPLAY/`gi`. Playwright gallery tests skip without Playwright Chromium. ISO, QEMU, and physical hardware were not run.

## Out of scope

ISO build, QEMU, physical hardware, publication, Notion live update.
