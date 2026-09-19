# #79 Add a user-controlled text-size setting

Fake disks only. No image published.

## Baseline (`origin/main` `edd2da3`)

Tk pins `tk scaling 1.0` so X DPI cannot enlarge type and clip the
layout. There is no user control. People who need larger type cannot
choose it. Font pixel sizes follow window compact/large only.

## Acceptance

1. Keyboard screen offers Standard, Large, and Extra large before any
   disk choice. Default is Standard (current sizes).
2. The choice persists for this USB session (in memory). Refresh, keyboard
   layout, and authorization reset do not clear it. A new session starts
   at Standard.
3. Tk keeps `tk scaling 1.0`. User size is a multiplier on pixel fonts,
   not a DPI change.
4. Footer actions stay on-window at 800×600 with Extra large. Body may
   scroll. Identity and warnings stay in the tree.
5. Later screens expose a Text size utility that cycles the same three
   sizes. GTK and gallery match. Console 80×24 cannot grow glyphs.
6. Unknown size values are refused. Font floors stay in place if metrics
   differ.

## Verification

- `python3 -m pytest tests/test_text_size.py tests/test_layout.py tests/test_adaptive_layout.py::test_extra_large_text_keeps_actions_at_800x600`
- Hosted `lint` / `preview` / `negative` PASS

Tk pixels: `screencapture` is TCC-blocked.

## Intentional difference

Console stays 80×24. Helper is a boot page. Live USB does not write the
choice to disk (kiosk tmpfs; session memory only).
