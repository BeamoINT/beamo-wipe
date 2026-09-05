# Screen-reader operation

Shutdown actions described below now request the shared shutdown decision:
when a report was requested but no current verified export is confirmed,
**Shut down without saving?** requires a separate choice. **Keep session open**
is the safe default. Tk Enter/Escape returns; Tab and Space select an action.
The screen-reader view exposes Keep first and both native buttons. See
[the state, console, and recovery rules](report-shutdown.md). No report survives
live-session shutdown or power loss unless it has been exported.

The live USB offers a GTK 3 view using standard AT-SPI controls and Orca.
Press F8 in the graphical wizard before erasure, or choose **Screen-reader
view (F8)**. This checks disks again and clears the selected target, ownership
acknowledgement, typed confirmation, method, and countdown. Complete the entire
authorization flow in the new view. Switching is unavailable while an erase is
starting or running. A failed refresh leaves no stale disk selectable.

Tab and Shift+Tab move focus; Space activates a focused control. The ownership
checkbox and typed confirmation still gate Continue. The Erase now button stays
disabled for the five-second countdown and never activates automatically.
F5 checks disks again before erasure. Escape goes back where allowed. Full
**Storage limits** are available from method selection and return to that method.
**Other detected devices** is read-only text; it never offers an erase action.

On screen changes, focus moves to the screen explanation. Finished announces
the canonical evidence outcome and safe next step. Quick zero completion says
“Erase completed; verification was not performed.” A verified completion checks
exposed storage only. No read-back result guarantees coverage of inaccessible,
remapped, over-provisioned, or controller-managed flash; extra overwrite passes
do not fix these limits. Failed or missing evidence remains unsuccessful or
indeterminate. Confirmed cancellation says “Stopped by you.”

The view starts Orca and PulseAudio on the live USB. Speech requires working
audio output. Native Tk 8.6 is not claimed to expose its custom canvas controls
to screen readers. The sequential `--plain-console` view is also available for
terminal environments with an independently configured reader.

For a safe Linux preview, install the GTK/Orca packages listed in the live
package list and run `./preview --accessible`. It uses fake devices. Preview
mode does not start host audio services or an external screen reader.

Regression checks use fake disks and process output, GTK at 800×600, an external
AT-SPI client, and real Orca speech-generation diagnostics. Run with a private
D-Bus session and Xvfb at 72 DPI, as described in [CI](ci.md). These checks do not
prove physical speaker output, braille hardware behavior, or compatibility with
every sound card. No test uses host disks or audio-device passthrough.
