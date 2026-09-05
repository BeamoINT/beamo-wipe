# Screens

Every interface uses the same Wizard authorization and validated result model.

| Screen | Purpose |
| --- | --- |
| Splash / What | Explain ownership, irreversible erasure and supported PCs. Nothing starts automatically. |
| Owner | Require the ownership or written-permission acknowledgement. |
| Pick a disk | Keep eligible targets separate from read-only Other detected devices. Show identity and deterministic exclusion reasons. No excluded row offers a bypass. Empty or uncertain discovery gives safe support steps. |
| Confirm | Show the irreversible-action warning and exact device identity. Require the displayed confirmation token. |
| Choose an erase method | Show the operations below and the device-specific storage notice. SSD and unknown-device warnings explain inaccessible, remapped, over-provisioned and controller-managed storage; additional overwrite passes do not fix those limits. |
| Supported storage limits | Full offline limits, reached directly from method selection. Back returns to the chosen method. |
| Last chance to stop | Show identity, irreversible-action warning and canonical method summary. Require a fresh five-second countdown and explicit Erase now action. |
| Working | Keep device identity and progress visible. Confirmed cancellation, interruption and inability to confirm a stop remain distinct. |
| Finished | Use validated evidence and the canonical explanation in `outcomes.py`. Quick zero completion explicitly says verification was not performed. Provide the guarded separate-USB report workflow where available. |
| Advanced | Technician information and the report workflow guidance. |

## Method operations

- Everyday: 1 overwrite pass: random data. 1 separate read-back verification pass after the final overwrite.
- Three overwrites: 3 overwrite passes: a pattern, its inverse, then random data. 1 separate read-back verification pass after the final overwrite.
- Quick zero: 1 overwrite pass: zeros. Verification is not performed. No read-back pass.

Before erasure, **Check disks again** (F5) performs fresh discovery and boot
identification, clears the selected target and every prior acknowledgement,
confirmation, method and countdown, and requires the full flow again. A failed
refresh leaves no stale target selectable. Refresh is disabled once starting or
running. Returning to a disk never automatically selects or authorizes it.

Tk and the keyboard console support Tab, Enter, Escape, disk-selection arrows,
and 1–2–3 for methods. L opens full limits from method selection. The 80×24
console offers O for the read-only excluded inventory. The sequential console
accepts `CHECK DISKS AGAIN` at its pre-erase prompts.

On Linux, F8 before erasure opens the GTK screen-reader view after clearing
prior authorization through refresh. Use Tab, Shift+Tab, Space and Orca reading
commands; see [screen-reader operation](screen-reader.md).

Local previews use fake devices and never erase disks. The browser gallery is
a preview; the shipped graphical views are native windows.
