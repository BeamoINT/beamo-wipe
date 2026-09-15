# Layout notes — guided boot help #59

Headless Chrome shots in this folder. No network. Helper is `file://`
`helper/index.html`. Desktop shots use a temp copy with `<details id="help"
open>` and local `style.css` so the chooser is visible without the launcher
process. Branch shots inject a temporary stylesheet that shows one panel;
that stylesheet is not shipped.

## Helper (START-HERE.html)

| Shot | Viewport | What it shows |
| --- | --- | --- |
| `helper-360.png` | 360×900 | Banner + stacked chooser. All four problems fit without sideways scroll. |
| `helper-1280.png` | 1280×900 | Chooser is a 2×2 grid, then the existing desktop-start copy. |
| `helper-360-trouble-usb.png` | 360×1400 | USB illustration (stick into the PC, hub marked with a red X) and numbered port steps. |
| `helper-360-trouble-key.png` | 360×1400 | Keyboard illustration (gold key) and “press as the computer starts”. |
| `helper-360-trouble-firmware.png` | 360×1400 | Lock + notepad. BitLocker warning is step 1. Caption: does not change Secure Boot. |
| `helper-360-trouble-launcher.png` | 360×1400 | Window with a warning mark and a document. Launcher does not erase. |

Chooser links are 2.75em tall, wrap, and use the existing 3px focus ring.
Panels use `em`/`%`/`min()` and `overflow-wrap: anywhere`. Unselected
panels stay in the file for print and for browsers without `:has()`;
supporting browsers show one branch after a chooser tap.

## Desktop launcher help

| Shot | Viewport | What it shows |
| --- | --- | --- |
| `desktop-help-360.png` | 360×900 | Help open under readiness. Chooser stacks. First two problems visible; the rest scroll. |
| `desktop-help-1024.png` | 1024×900 | 2×2 chooser. Panels hidden until a problem is chosen. |
| `desktop-help-360-firmware.png` | 360×1400 | Firmware branch with the same lock illustration and BitLocker-first steps. |

## Intentional differences

- Helper is the full offline USB page: kiosk recovery, Intel Mac Option key,
  Windows 10/11 cards, BitLocker card. No JavaScript.
- Desktop help is the same four branches for someone already in the launcher.
  It does not run on macOS, so it omits the Option key and points at
  `START-HERE.html` for kiosk recovery and the rest.
- Desktop CSP forbids forms and extra image files; illustrations are inline
  SVG in HTML, matching the helper.

## Not captured

Physical firmware, a real boot menu, or 200% OS text-size on a phone. CSS
uses `em`/`rem`/`%` and wrapping; Chrome `--force-device-scale-factor` is
DPI scale, not text-only zoom.
