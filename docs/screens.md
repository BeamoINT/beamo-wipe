# Screens (matches the product brief)

| # | Name | Purpose |
| --- | --- | --- |
| 0 | Splash | Beamo Wipe. This USB restarts into a wipe tool. It will not run from Windows. 3 seconds on the live USB (skippable). Preview waits for a key or Continue. |
| 1 | What this is | Three bullets: nwipe front-end; erase forever; x86_64 USB boot only, not Apple Silicon, not Chromebooks. I understand / Shut down (Close preview in `./preview`). |
| 2 | Owner | Required checkbox. No check, no continue. |
| 3 | Pick a disk | Model, type, size GB, serial, path, bus. Nothing is chosen until you click (or Up/Down). Continue stays off until then. Boot USB last, marked, not selectable. Same-size disks warn to use the serial. Identify failure blocks. Empty state if no other disks. |
| 4 | Confirm | Type-to-confirm size or last 4 of serial. Continue disabled until match. |
| 5 | How thorough | Everyday (default) / Extra thorough / Quick zero, each with a wait-time note. SSD footer. Advanced link. |
| 6 | Last chance | 5 second delay on Erase. Shows model, size, and serial. |
| 7 | Working | Progress or pulse plus method name. Disk identity stays on screen. |
| 8 | Done | Success or failure copy. Never “secure” on failure. Preview: Close preview / Run again. |
| 9 | Advanced | Raw nwipe method list, log path. Technicians only. |

Keyboard: Tab, Enter, Escape, Up/Down on the disk list, 1–2–3 on thoroughness.

Local preview: `./preview` (Tk) or `./preview --web` (browser). Neither erases disks.
