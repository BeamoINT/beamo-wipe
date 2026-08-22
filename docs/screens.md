# Screens (matches the product brief)

| # | Name | Purpose |
| --- | --- | --- |
| 0 | Splash | Beamo Wipe. You already started from this USB. Next you pick a disk. Continue (any key). No footer lecture. |
| 1 | What this is | Two bullets: erase forever; regular Windows PCs from this USB, not Apple Silicon, not Chromebooks. Optional Show more (USB-start hint, then nwipe by name). I understand / Shut down (Close preview in `./preview`). |
| 2 | Owner | Required checkbox. No check, no continue. |
| 3 | Pick a disk | Model, type, size, serial. Click the name and size. Continue stays off until then. Boot USB last, marked, not selectable. Same-size disks warn to use the characters under the name. SSD note only after an SSD is chosen. Identify failure blocks. Empty state if no other disks. |
| 4 | Confirm | Type-to-confirm size or last 4 of serial (“these 4 characters”). Continue disabled until match. |
| 5 | How thorough | Everyday (default) / Extra thorough / Quick zero, each with a wait-time note. Advanced link. |
| 6 | Last chance | 5 second delay on Erase. Shows model, size, and serial. |
| 7 | Working | Progress or pulse plus method name. Disk identity stays on screen. |
| 8 | Done | Success or failure copy. Never “secure” on failure. Preview: Close preview / Run again. |
| 9 | Advanced | Raw nwipe method list, log path. Technicians only. |

Keyboard: Tab, Enter, Escape, Up/Down on the disk list, 1–2–3 on thoroughness.

Local preview: `./preview` (Tk) or `./preview --web` (browser). Neither erases disks.
