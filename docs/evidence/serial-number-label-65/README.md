# Backlog #65 — label serial numbers explicitly

Base: `origin/main` at `67d1f8177a7a8b37a6faaa934873a8ad7e01d48f`.
Branch: `feat/serial-number-label`.

Fake lsblk and DryRunRunner only. No real disk, no nwipe, no ISO.

## Baseline (measured on 67d1f81)

`identity.SERIAL_LABEL` and `copy.SERIAL_LABEL` were `Serial`. Announcements
said `Serial: S4EVNX0N123456`. Tk/gallery showed a `Serial` chip next to the
value. Comparison, Other detected devices, reports, and SHARE.txt used
`Serial:`. Hardware ID was already `Hardware ID`. Missing serials used
`Serial not reported` as the value.

New tests failed: `assert SERIAL_LABEL == "Serial number"`.

## Acceptance

1. Present serials are prefixed with **Serial number** on pick, confirm, method,
   review, progress, results, reports, comparison, console, and gallery.
2. Absent or whitespace-only serials keep the **Serial number** label and
   `Serial not reported`.
3. Duplicated serials keep the label plus the duplicate warning.
4. Non-ASCII and long serials keep the prefix and the full value.
5. Hardware ID fallback is not relabeled Serial number.
6. Selection eligibility is unchanged.

## Implementation

One customer string: `copy.SERIAL_LABEL = "Serial number"`, imported by
`identity.py`. Inventory comparison, reports, and the gallery payload use that
constant. Tk/GTK/console already render `view.id_label`. Helper has no disk
serials.

## Verification

- `tests/test_serial_number_label.py` failed on the original label; passes after.
- Identity/result-summary/serial-comparison/copy: passed.
- `BEAMO_GATE_CHILD=1 ./scripts/ci-hosted.sh lint` — PASS.
- Preview web/console/helper — PASS.
- Negative safety gate — PASS.
- Wheel contains `SERIAL_LABEL = "Serial number"`.
- Screenshots: `web-pick-1280.png`, `web-pick-390.png`, `web-confirm-1280.png`.

Full local `./scripts/test-all.sh`: **2583 passed, 513 skipped, 5 failed**. The
five failures are the same environment leftovers (`gi` missing, stale gitignored
START-HERE.html, Microsoft URL 403, drifted live-build chroot).

Tk/GTK skip without DISPLAY/`gi`. ISO, QEMU, and physical hardware were not run.

## Out of scope

ISO build, QEMU, physical hardware, publication.
