# #78 Support short and small displays

Fake disks only. No image published.

## Baseline (`origin/main` `edd2da3`)

`minsize` is already 800×600 and the body can scroll on some screens, but
1280×720 is treated as a tall layout (`short` only below 680px). The default
window is 1280×820, which does not fit a 720p panel. The gallery shell still
has `min-height: 740px`. Docs still call 1024×740 the minimum and 800×600
degraded.

## Acceptance

1. 1280×720 is a short, compact layout. 800×600 stays the window minimum.
2. Opening geometry is clamped to the physical screen, never taller than the
   panel, never smaller than 800×600.
3. Footer actions stay on-window at 800×600 and 1280×720. Body content may
   scroll. PageUp/PageDown move the body canvas. Identity, warnings, and
   destructive copy stay in the widget tree (reachable, not dropped).
4. Gallery preview does not force a 740px-tall shell on short viewports;
   the footer stays visible.
5. Keyboard-only access is unchanged. No safety copy is hidden.

## Verification

- `python3 -m pytest tests/test_layout.py tests/test_adaptive_layout.py`
- `test_screen_fits_without_clipping` at 800×600, 1280×720, 1024×740, 1280×820
- Hosted `lint` / `preview` / `negative` PASS
- Gallery screenshots `method-800x600.png`, `last-800x600.png`, `method-1280x720.png`

Tk pixels: `screencapture` is TCC-blocked; Tk covered by adaptive layout tests.

## Intentional difference

Console 80×24 already wraps; this task is Tk + gallery. GTK already has no
minimum window size. Helper is a boot page, not the wizard.
