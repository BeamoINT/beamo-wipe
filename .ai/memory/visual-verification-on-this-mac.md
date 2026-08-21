# Visual verification of the wizard on this Mac

`screencapture` fails here ("could not create image from display") — the
terminal lacks macOS Screen Recording (TCC) permission, so Tk windows cannot
be screenshotted programmatically.

Use the two sanctioned paths instead:

- **Tk screens:** `tests/test_tk_runtime.py` drives the real wizard on fake
  disks at 1280x820 and 1024x740 (clipping, off-window, keyboard-only flow,
  focus). For ad-hoc renders, drive `make_demo_wizard` + `TkWizard` like those
  tests do and call `app._draw()` / `app.root.update()`.
- **Pixels:** `./preview --web` (regenerate with `BEAMO_WIPE_NO_OPEN=1`), then
  headless Chrome on the gallery deep links, e.g.
  `chrome --headless=new --screenshot=/tmp/x.png --window-size=1280,1160
  "file:///.../web-preview/index.html#s=confirm&disk=0&typed=1"`.
  The gallery is a pinned 1:1 mirror of the Tk design system
  (`tests/test_ui_system.py` enforces token/component sync).

The full-suite Tk tests are real GUI windows: an occasional focus race on
macOS can flake `test_keyboard_only_flow_reaches_working`. Re-run before
assuming a regression; three clean passes is the practical bar.
