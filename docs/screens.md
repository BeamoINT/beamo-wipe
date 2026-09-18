# Screens

Every interface uses the same Wizard authorization and validated result model.

| Screen | Purpose |
| --- | --- |
| Splash / Keyboard / What | Splash explains that nothing starts automatically. Keyboard offers only the shipped US QWERTY, French AZERTY, and German QWERTZ layouts plus a typing-check box that is never saved. What explains ownership, irreversible erasure, backup copies, OS-disk consequences, wall-power reminder, display blanking, and supported PCs. Between the bullets and the power panel, What states the report-media requirements up front: a separate FAT32 USB with one volume, kept unplugged until the result screen asks, with already-plugged media refused, and points to Need a report? for details. |
| Owner | Require the ownership or written-permission acknowledgement. |
| Pick a disk | Physical disks are primary cards. Partitions and other technical components nest under their parent when parentage is known. Keep eligible targets separate from read-only Other detected devices. Show identity and deterministic exclusion reasons. No excluded row offers a bypass. Empty or uncertain discovery gives safe support steps. When a report was requested, an info notice reminds the owner to keep the report USB unplugged until prompted, warns that extra USBs confuse the list, and gives the unplug-only-that-USB remedy; without a requested report no notice shows. |
| Confirm | Show the irreversible-action warning, exact device identity, and partition-evidence preparation for the selected disk. Require the displayed confirmation token. |
| Choose an erase method | Show the operations below and the device-specific storage notice. SSD and unknown-device warnings explain inaccessible, remapped, over-provisioned and controller-managed storage; additional overwrite passes do not fix those limits. |
| Supported storage limits | Full offline limits, reached directly from method selection. Back returns to the chosen method. |
| Review before erasing | Emphasize selected disk and plain method operation above technical pass details. Show partition-evidence preparation and the irreversible-action warning. A small countdown marks a fresh five-second review period: zero only enables Erase now and never starts erasure. Require explicit activation. |
| Working | Keep device identity, the method summary, and progress visible. Remind the owner to leave the USB in and keep wall power connected. Choose **Stop erase** (Tk/GTK button or Escape; plain console `CANCEL` + Enter; curses Esc) to review a warning: stopping cannot restore files already erased. **Keep erasing** dismisses the confirmation. Confirm with **Yes, stop erasing** (plain console `STOP` + Enter; curses S). Progress polling continues during confirmation, and completion takes precedence over stale confirmation actions. **Stopping erase** means exit and cleanup are still pending; the stopping and stop-confirmation screens keep the same disk identity and method summary visible instead of showing timing text alone. **Stopped by you** is a confirmed interruption, not a completed erase. **Stop could not be confirmed** stays on Working with a prominent warning because the disk may still be erasing. Interruption and inability to confirm a stop remain distinct outcomes. Shut down is not offered while an erase may still be running. Progress is percent text plus bar plus an indeterminate slide before the engine reports a number; percent never shows 100% early. Below the timing line, the working screen shows the full operation sequence derived from the chosen method (for example Overwrite 1 of 3, Overwrite 2 of 3, Overwrite 3 of 3, Read-back verification) with done/now markers, plus a current-step line (Step 2 of 4: Overwrite 2 of 3) that carries the live step percent scoped to its step (45% of this step), so 100% of one write cannot read as overall completion. The current step is located from live engine phase and pass counters cross-checked against the plan; missing or disagreeing reports show explicit uncertainty text instead of a guessed step. Verifying, Syncing, Retrying, and Finalizing phases add a one-line note explaining the transition and that the erase is not done until the result screen. The time-remaining line always names its state: a live estimate when six steady fresh samples with engine agreement exist on the last step, otherwise an honest reason such as estimating after more progress, waiting for the last step, retrying, syncing, paused updates, missing drive time data, disagreeing reports, or the finished last step awaiting the result. When progress updates go stale, the working screen adds how long it has been quiet, explains that a quiet screen does not mean the erase stopped, and gives safe next steps (keep the USB in and wall power connected, do not turn off, Stop erase stays available); it never recommends restarting, unplugging, or retrying the wipe. Outcome sounds are off by default and configurable here before the outcome: a Sounds off/on toggle plus Hear sounds (Tk buttons; curses O/H keys; plain console SOUNDS/HEAR words; screen-reader Sound-check dialog). Nothing plays until the outcome is final. |
| Finished | Use validated evidence and the canonical explanation in `outcomes.py`. The main heading is the specific erase outcome (verification passed, completed without verification, interrupted, or failed) — never a generic label. Failed, cancelled, and unconfirmed outcomes then show three labeled recovery sections in screen-reader order: **What happened** (the exact message), **What it means for your disk**, and **What to do next**. Technical details stay behind an on-demand control and never replace those three. Verified and unverified success keep the unlabeled next-step paragraph. The erase badge, message, and details stay independent of the **Report status** area, which identifies the report copy on its own. The erase badge uses the canonical outcome; a confirmed user stop still reads **Stopped by you** in the erase summary. Report status uses neutral information, an amber warning, or a distinct saved-copy treatment (a Saved label, a small in-panel check, report wording, and the safe-to-remove line) — never the erase-success badge or the red failure badge. Report copy checking is not disk read-back verification. The screen shows elapsed time, the method summary, the next step, the disk summary with Show more, and the guarded report instruction. Outcomes that refer the owner to support add the support destination (`beamosupport.com`) as text everywhere and a phone-scannable code on graphical surfaces; the readable report, its README, and the offline helper carry the same destination. The browser preview omits the block on its sample finished screens because those screens say nothing was erased and do not ask the owner to contact support. Successful outcomes add that only the validated selected disk was processed and that reinstalling an operating system is a separate task. Failures, cancellation and indeterminate results do not claim a disk was processed. Quick zero completion explicitly says verification was not performed. Footer, live session: **Save report to USB** (enabled only when the evidence gate allows saving), **Shut down** (disabled while exporting or saving evidence), and **Retry evidence save** when evidence saving failed. Footer, preview: **Close preview** and **Run again**. Console equivalents are the `SAVE` / `RETRY` / `SHUTDOWN` prompts; the screen-reader view exposes the same actions as native buttons. When sounds are on, the finished earcon plays once for a verified erase and the attention earcon plays once for any other final outcome (including unverified completion, interruption, and failures); muted, missing, or preview audio stays silent, and Hear again replays on demand. Unless the outcome proves nothing was erased, a conditional note follows the next step: if the erased disk was the one the computer starts from, the computer may not start normally and may need an operating system installed before reuse. The offline helper repeats this guidance in its after-erasing card. The report-status area guides export through five numbered stages (insert, check, save, verify, safe removal) with done/now marks and one current-step line instead of long paragraphs; check/save/verify read as current together because they run inside one export call, and failures show the precise error with retry guidance and no stage marks. Every media rejection names the problem and the next safe step (replug, different stick, retry-then-support, retry-then-shutdown, sort-while-off, wait); reasons that already carry instructions and the diagnostic screen share the same mapping. |
| Advanced | Technician information and the report workflow guidance. |
| Shut down without saving? | Shown when a report was requested but no current verified export is confirmed. Keep session open returns; explicit discard authorizes shutdown. Below the loss text, ordered removal steps state which media can be removed, which must stay, and that the Beamo USB is safe to remove only after the computer is fully off, plus restart and unsure-media rules; the erase-another variant keeps the Beamo USB for the next erase instead. [State and recovery rules](report-shutdown.md). |

## Method operations

- Everyday: 1 overwrite pass: random data. Then we check the last overwrite.
- Three overwrites: 3 overwrite passes: a pattern, its inverse, then random data. Then we check the last overwrite.
- Quick zero: 1 overwrite pass: zeros. This method does not check the overwrite.

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
ATK headings and focusable report text; arrival focus stays on the specific
erase heading (the announcement on success, the outcome message on failure). Console uses text headings without relying on color. The browser
and native previews show the same two areas but explicitly state that no report
was saved; the gallery does not simulate report export or offer a real save action.

### Error recovery sections (#107)

Every failure surface uses the same three customer sections, then technical
detail on demand: diagnostic, blocked, empty, keyboard/layout, last-chance,
working, finished, report-USB refusal, and evidence-save failure. Unknown
errors keep the original message, say the result is unconfirmed, and tell the
owner not to bypass protection. RESULT.txt adds the labeled fields after
Result for non-success outcomes only; Limitations is unchanged. Short Tk and
the 80×24 curses console join each label to its body on one line so **Report
status**, the post-erase start note, and report-USB next steps stay in the
first viewport; stacked labels plus on-demand technical details remain the
full-height Tk, GTK/Orca, gallery, helper, and plain-console layout. Curses
pages the Result code with report aftercare. The live USB supervisor recovery
menu is an intentional difference: it is outside the Python wizard, so its
**Technical details and logs** choice is not this three-section layout. The
offline helper explains both.

### Stop controls and fallback differences

Tk/GTK window close during an erase opens the same confirmation. Escape in that confirmation keeps erasing. Confirmation uses a separate control and safe arrival focus; repeated initiating clicks or keys cannot confirm a stop. In the plain console, Ctrl-C opens confirmation; repeated CANCEL does not confirm. EOF or a broken terminal still requests an immediate system stop because input is unavailable. UI failure also keeps the existing system-stop recovery. These emergency paths cannot offer interactive confirmation.

The browser preview simulates confirmation, stopping, and stopped states; no disk is touched. Its sample erase may finish while confirmation is open. Deep links `#s=stop_confirm&disk=0`, `#s=stopping&disk=0`, `#s=stopped&disk=0`, and `#s=stop_unconfirmed&disk=0` show the states; stop-unconfirmed is a static failure example, not an engine test. Native preview results retain their explicit “nothing erased” evidence contract. A power or process loss never implies a completed erase or restores files; recovered evidence remains authoritative.

### Support code when a report cannot be saved (#106)

Blocked, empty, diagnostic, last-chance start failures, graphical-unavailable What, and live Finished screens where the report was not saved show a **Support code** and **Build** line in monospace, plus a **Save code** when the on-screen refusal is a known export failure. The values are non-sensitive: no disk serial, path, or translated problem text. Labels follow the chosen language; the code (`BW-` family token) and build id never do. Progress copy (checking, verifying, saving) does not become a save code. Browser preview shows sample codes on blocked/empty only; its Finished screens stay preview and do not simulate a live export failure. Console and the screen-reader view use the same text, without a QR of the code. The offline helper tells the owner to read those on-screen lines. Kiosk recovery cannot generate them.
