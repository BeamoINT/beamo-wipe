# Modern minimal UI refresh

Shared visual system for Tk, the web gallery, the boot helper, and the
GTK accessibility view. Navy mark `#0A1B34` is unchanged. Red stays on
destructive actions and failures. Disk identity, exclusions, and
warnings remain fully visible.

## What changed

- Cooler ink/muted/border palette, 12px corners, pill actions
- Header names only the current step (`Confirm · Step 4 of 8`)
- Confirm/method/last-check leads in plain language
- One power panel, method limits as a quiet note, no repeated last-check line
- Pick cards nest partitions without kernel paths; working keeps one progress card
- Done preview no longer repeats the announcement line
- Method cards say “check the last overwrite”; nested cards drop “unsupported device”
- Identity card says “This disk”
- Helper opens with the same three-step path as the wizard
- Shared checkbox, scrollbar, reader, and progress controls replace native Tk chrome
- Method and keyboard keycaps sit on the right; compare/report use the check icon
- WCAG 2.1 AA text and non-text contrast still pass

## Screenshots

Headless Chrome on `web-preview/index.html` and `helper/index.html`
(`--virtual-time-budget=8000`). Tk pixels are covered by
`tests/test_tk_runtime.py` and `tests/test_ui_rework.py` because
`screencapture` is TCC-blocked on this Mac.

Fake disks only. No image published.
