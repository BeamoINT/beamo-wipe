# #73 Explain that disk refresh resets preparation

Fake disks only. No image published.

## Baseline (`origin/main` `67d1f81`)

F5 / **Check disks again** calls `Wizard.refresh_disks()` immediately.
`begin_refresh` already clears the selected disk, ownership, typed
confirmation, method, and countdown, then rediscovery returns to **Here's
what happens**. The UI never shows that reset until after it has happened.
A held or repeated F5 can skip the wording entirely.

## Acceptance

1. Before any reset, the owner sees that refresh clears the selected disk,
   the ownership acknowledgement, the typed confirmation, the method, and
   the countdown, and that preparation starts again from the beginning.
2. Cancel / Esc / Back keeps every authorization and the previous screen.
3. Confirm then performs the existing complete reset. Failed rediscovery
   still leaves no stale target selectable.
4. Focus after a successful refresh is the first preparation step.
5. A second refresh in the same session shows the wording again.
6. F5 auto-repeat cannot skip the wording.
7. Tk, gallery, console, GTK, and docs stay aligned. `refresh_disks()`
   remains the actual reset for sequential callers and tests.

## Intentional difference

The helper page does not refresh disks. F8 screen-reader handoff still
runs a refresh after its own scan; this task only gates **Check disks
again (F5)**.

## Verification

- `python3 -m pytest tests/test_refresh_confirm.py` (wording, no reset until
  confirm, cancel keeps auth, failed confirm is fail-closed, repeat)
- `DISPLAY=:0 python3 -m pytest` — new tests passed. Pre-existing on this
  Mac: GTK `gi` missing, gitignored `support_export.py` chroot drift.
- `BEAMO_GATE_CHILD=1 ./scripts/ci-hosted.sh lint|preview|negative` PASS
- Gallery screenshot `refresh-confirm-1280.png` (fake disks)

Tk pixels: `screencapture` is TCC-blocked; Tk covered by runtime tests.
