# Modern minimal UI refresh

Shared visual system for Tk, the web gallery, the boot helper, and the
GTK accessibility view. Navy mark `#0A1B34` is unchanged. Red stays on
destructive actions and failures. Disk identity, exclusions, and
warnings remain fully visible.

## What changed

- Cooler ink/muted/border palette, 12px corners, pill actions
- Completed vs current journey markers
- Helper cards are rounded surfaces on a quiet field
- WCAG 2.1 AA text and non-text contrast still pass

## Screenshots

Headless Chrome on `web-preview/index.html` and `helper/index.html`
(`--virtual-time-budget=8000`). Tk pixels are covered by
`tests/test_tk_runtime.py` and `tests/test_ui_rework.py` because
`screencapture` is TCC-blocked on this Mac.

Fake disks only. No image published.
