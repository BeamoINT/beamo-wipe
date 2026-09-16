# Screens

Every interface uses the same Wizard authorization and validated result model.

| Screen | Purpose |
| --- | --- |
| Splash / Keyboard / What | Splash explains that nothing starts automatically. Keyboard offers only the shipped US QWERTY, French AZERTY, and German QWERTZ layouts plus a typing-check box that is never saved. What explains ownership, irreversible erasure, backup copies, OS-disk consequences, wall-power reminder, display blanking, and supported PCs. |
| Owner | Require the ownership or written-permission acknowledgement. |
| Pick a disk | Physical disks are primary cards. Partitions and other technical components nest under their parent when parentage is known. Keep eligible targets separate from read-only Other detected devices. Show identity and deterministic exclusion reasons. No excluded row offers a bypass. Empty or uncertain discovery gives safe support steps. |
| Confirm | Show the irreversible-action warning, exact device identity, and partition-evidence preparation for the selected disk. Require the displayed confirmation token. |
| Choose an erase method | Show the operations below and the device-specific storage notice. SSD and unknown-device warnings explain inaccessible, remapped, over-provisioned and controller-managed storage; additional overwrite passes do not fix those limits. |
| Supported storage limits | Full offline limits, reached directly from method selection. Back returns to the chosen method. |
| Review before erasing | Emphasize selected disk and plain method operation above technical pass details. Show partition-evidence preparation and the irreversible-action warning. A small countdown marks a fresh five-second review period: zero only enables Erase now and never starts erasure. Require explicit activation. |
| Working | Keep device identity, the method summary, and progress visible. Remind the owner to leave the USB in and keep wall power connected. Choose **Stop erase** (Tk/GTK button or Escape; plain console `CANCEL` + Enter; curses Esc) to review a warning: stopping cannot restore files already erased. **Keep erasing** dismisses the confirmation. Confirm with **Yes, stop erasing** (plain console `STOP` + Enter; curses S). Progress polling continues during confirmation, and completion takes precedence over stale confirmation actions. **Stopping erase** means exit and cleanup are still pending. **Stopped by you** is a confirmed interruption, not a completed erase. **Stop could not be confirmed** stays on Working with a prominent warning because the disk may still be erasing. Interruption and inability to confirm a stop remain distinct outcomes. Shut down is not offered while an erase may still be running. Progress is percent text plus bar plus an indeterminate slide before the engine reports a number; percent never shows 100% early. |
| Finished | Use validated evidence and the canonical explanation in `outcomes.py`. Separate **Erase status** and **Report status** areas identify the erase result and the report copy independently. The erase badge uses the canonical outcome; a confirmed user stop still reads **Stopped by you** in the erase summary. Report status uses neutral information or an amber warning, never the erase-success check or red failure badge. Report copy checking is not disk read-back verification. The screen shows elapsed time, the method summary, the next step, the disk summary with Show more, and the guarded report instruction. Successful outcomes add that only the validated selected disk was processed and that reinstalling an operating system is a separate task. Failures, cancellation and indeterminate results do not claim a disk was processed. Quick zero completion explicitly says verification was not performed. Footer, live session: **Save report to USB** (enabled only when the evidence gate allows saving), **Shut down** (disabled while exporting or saving evidence), and **Retry evidence save** when evidence saving failed. Footer, preview: **Close preview** and **Run again**. Console equivalents are the `SAVE` / `RETRY` / `SHUTDOWN` prompts; the screen-reader view exposes the same actions as native buttons. |
| Advanced | Technician information and the report workflow guidance. |
| Shut down without saving? | Shown when a report was requested but no current verified export is confirmed. Keep session open returns; explicit discard authorizes shutdown. [State and recovery rules](report-shutdown.md). |

## Method operations

- Everyday: 1 overwrite pass: random data. 1 separate read-back verification pass after the final overwrite.
- Three overwrites: 3 overwrite passes: a pattern, its inverse, then random data. 1 separate read-back verification pass after the final overwrite.
- Quick zero: 1 overwrite pass: zeros. Verification is not performed. No read-back pass.

Before erasure, **Check disks again** (F5) first shows that it clears the
selected disk, ownership acknowledgement, typed confirmation, method, and
countdown, and that preparation starts again from the beginning. Back keeps
those answers. Confirming then performs fresh discovery and boot
identification and requires the full flow again. A failed refresh leaves no
stale target selectable. Refresh is disabled once starting or running.
Returning to a disk never automatically selects or authorizes it.
The checking screen paints immediately and discovery runs off the UI thread,
so repaint and input continue during the scan; pressing F5 again while
checking is ignored until the scan lands, so only one scan ever runs.

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
On the Last chance screen the interfaces differ by design: Tk starts erasure
only from the focused, countdown-enabled Erase control (Enter, Space, or
click); the curses console erases on Enter once the countdown lapses with Esc
as the way back; the sequential console requires typing `ERASE`.

On Linux, F8 before erasure opens the GTK screen-reader view after clearing
prior authorization through refresh. Use Tab, Shift+Tab, Space and Orca reading
commands; see [screen-reader operation](screen-reader.md).

Local previews use fake devices and never erase disks. The browser gallery is
a preview; the shipped graphical views are native windows.

The shipped live supervisor also has a [terminal recovery menu](kiosk-recovery.md)
after repeated startup failures or a normal interface close. It is outside the
Python wizard so missing graphical/Python dependencies cannot hide it. Browser
and native previews retain the wizard's own diagnostic screens; the offline
helper explains the live-only recovery choices and accessibility limits.

### Erase and report status (#96)

Every completion view separates erase status from report status. Report save,
check, and retry messages never replace the erase outcome. A saved receipt means
only that the report copy was checked and the report USB safely unmounted; it does
not confirm erase success. Existing evidence validation remains conservative:
when evidence preparation fails, completion cannot be confirmed, even if the
process reported completion. Retry does not run the erase again.

Tk places the report panel directly below the erase summary, before scrollable
disk details and check warnings. The GTK screen-reader interface exposes explicit
ATK headings and focusable report text; the canonical erase announcement retains
arrival focus. Console uses text headings without relying on color. The browser
and native previews show the same two areas but explicitly state that no report
was saved; the gallery does not simulate report export or offer a real save action.

### Stop controls and fallback differences

Tk/GTK window close during an erase opens the same confirmation. Escape in that confirmation keeps erasing. Confirmation uses a separate control and safe arrival focus; repeated initiating clicks or keys cannot confirm a stop. In the plain console, Ctrl-C opens confirmation; repeated CANCEL does not confirm. EOF or a broken terminal still requests an immediate system stop because input is unavailable. UI failure also keeps the existing system-stop recovery. These emergency paths cannot offer interactive confirmation.

The browser preview simulates confirmation, stopping, and stopped states; no disk is touched. Its sample erase may finish while confirmation is open. Deep links `#s=stop_confirm&disk=0`, `#s=stopping&disk=0`, `#s=stopped&disk=0`, and `#s=stop_unconfirmed&disk=0` show the states; stop-unconfirmed is a static failure example, not an engine test. Native preview results retain their explicit “nothing erased” evidence contract. A power or process loss never implies a completed erase or restores files; recovered evidence remains authoritative.
