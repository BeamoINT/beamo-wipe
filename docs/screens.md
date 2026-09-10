# Screens

Every interface uses the same Wizard authorization and validated result model.

| Screen | Purpose |
| --- | --- |
| Splash / Keyboard / What | Splash explains that nothing starts automatically. Keyboard offers only the shipped US QWERTY, French AZERTY, and German QWERTZ layouts plus a typing-check box that is never saved. What explains ownership, irreversible erasure, backup copies, OS-disk consequences, wall-power reminder, display blanking, and supported PCs. |
| Owner | Require the ownership or written-permission acknowledgement. |
| Pick a disk | Keep eligible targets separate from read-only Other detected devices. Show identity and deterministic exclusion reasons. No excluded row offers a bypass. Empty or uncertain discovery gives safe support steps. |
| Confirm | Show the irreversible-action warning, exact device identity, and partition-evidence preparation for the selected disk. Require the displayed confirmation token. |
| Choose an erase method | Show the operations below and the device-specific storage notice. SSD and unknown-device warnings explain inaccessible, remapped, over-provisioned and controller-managed storage; additional overwrite passes do not fix those limits. |
| Supported storage limits | Full offline limits, reached directly from method selection. Back returns to the chosen method. |
| Last chance to stop | Show identity, partition-evidence preparation, irreversible-action warning and canonical method summary. Require a fresh five-second countdown and explicit Erase now action. |
| Working | Keep device identity and progress visible. Remind the owner to leave the USB in and keep wall power connected. Confirmed cancellation, interruption and inability to confirm a stop remain distinct. Shut down is not offered while an erase may still be running. |
| Finished | Use validated evidence and the canonical explanation in `outcomes.py`. Successful outcomes add that only the validated selected disk was processed and that reinstalling an operating system is a separate task. Failures, cancellation and indeterminate results do not claim a disk was processed. Quick zero completion explicitly says verification was not performed. Provide the guarded separate-USB report workflow where available. |
| Advanced | Technician information and the report workflow guidance. |
| Shut down without saving? | Shown when a report was requested but no current verified export is confirmed. Keep session open returns; explicit discard authorizes shutdown. [State and recovery rules](report-shutdown.md). |

## Method operations

- Everyday: 1 overwrite pass: random data. 1 separate read-back verification pass after the final overwrite.
- Three overwrites: 3 overwrite passes: a pattern, its inverse, then random data. 1 separate read-back verification pass after the final overwrite.
- Quick zero: 1 overwrite pass: zeros. Verification is not performed. No read-back pass.

Before erasure, **Check disks again** (F5) performs fresh discovery and boot
identification, clears the selected target and every prior acknowledgement,
confirmation, method and countdown, and requires the full flow again. A failed
refresh leaves no stale target selectable. Refresh is disabled once starting or
running. Returning to a disk never automatically selects or authorizes it.

The keyboard screen is required after splash. Only US QWERTY, French AZERTY,
and German QWERTZ are offered. A successful layout change clears typed
confirmations, the ownership acknowledgement, the selected disk, and last-chance
authorization, and requires that flow again. A failed or unknown layout leaves
the previous layout and is shown as an error; it does not silently substitute
another map. The typing-check box is not a password, is not logged, and is not
written to evidence. A kiosk restart returns to the shipped US QWERTY default.

The graphical wizard uses real layouts at 800×600 and 1024×600 as well as
1024×740 and larger. Short windows may scroll the body; identity, warnings,
and footer actions stay reachable. Type enlarges slightly on large windows.
Tk scaling stays pinned so X DPI does not change the layout.

Tk and the keyboard console support Tab, Enter, Escape, disk-selection arrows,
1–2–3 for keyboard layouts and methods. L opens full limits from method selection. The 80×24
console offers O for the read-only excluded inventory. The sequential console
accepts `CHECK DISKS AGAIN` at its pre-erase prompts.

On Linux, F8 before erasure opens the GTK screen-reader view after clearing
prior authorization through refresh. Use Tab, Shift+Tab, Space and Orca reading
commands; see [screen-reader operation](screen-reader.md).

Local previews use fake devices and never erase disks. The browser gallery is
a preview; the shipped graphical views are native windows.
