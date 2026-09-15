# Kiosk startup recovery

The live USB supervisor tries the graphical interface, then the keyboard text
interface if graphics fails. After three failed attempts it stops automatic
retries and shows **Beamo Wipe recovery** on the same terminal. A normal
interface close goes straight to recovery without spending the remaining
attempts. The counter lasts for the supervisor session, not a time window.

Type a number and press Enter:

1. **Try Beamo Wipe again** makes one graphical attempt, with text fallback.
2. **Use keyboard text screens** makes one console attempt.
3. **Technical details and logs** shows the attempt count, last exit codes,
   and whether the application log folder is available.
4. **Restart computer** requires typing `RESTART`.
5. **Shut down** requires typing `SHUTDOWN`.

An earlier erase may still be running or may be incomplete. Keep disks
connected. Recovery cannot identify disks, discover exclusions, or confirm an
erase or verification result. A retry opens the existing wizard and its
[same-boot session recovery](session-recovery.md); it does not start a new erase
or bypass confirmations. Power actions fail closed if `pgrep -x nwipe` finds an
engine or cannot complete its check. They do not stop an engine. Use the wizard
to review and stop an interrupted operation first. A successful systemd request
means the power action was accepted, not that the computer has powered off.

The supervisor does not read or export raw logs. Existing application logs in
`/tmp/beamo-wipe/` remain inside the service's private temporary directory during
manual retries. The folder can be missing when Python could not start; files
can be incomplete. Exit codes and the attempt count remain on the recovery
screen even then. These details are not erase evidence. Note them before
restarting; reboot and service teardown can lose temporary logs and reports.

## Interface and accessibility boundaries

This is a shipped Linux terminal interface implemented in the supervisor's
existing POSIX shell. It remains available without Python, Tk, GTK, or X.
The native and browser wizard previews keep their existing diagnostic and
session-recovery screens: they do not run this privileged live supervisor.
The offline helper explains the same recovery choices. No wizard disk identity,
exclusion, warning, or result is replaced by the generic recovery screen.

Recovery resets terminal input and cursor state left behind by a crashed console
UI. Its numbered choices require no pointing device and fit an 80-column,
25-row console. A selected accessible boot mode speaks the recovery message,
safety warning, options, details, and confirmations using the existing bounded
`espeak-ng` helper. This is spoken guidance, not an AT-SPI screen-reader tree.
If the speech tools fail or are absent, the text remains visible but cannot
promise independent nonvisual access. The console wizard itself remains
unspoken, as its fallback warning states.

Systemd uses `Restart=no`: it cannot reset the supervisor's retry budget.
`TTYVTDisallocate=no` leaves the final readable message visible when input
closes. EOF exits without another launch; stopping the service or delivering
TERM/HUP exits without launching a login shell. If the shell or kernel itself
cannot run, this recovery interface cannot be provided. It is not firmware or
physical-hardware recovery.

## Acceptance and regression evidence

Baseline main: `7bb744948b035acaf912a67195bee01e4781828f`.
Before implementation, local pytest passed 1,946 tests with 391 platform/artifact
skips. The new `test_crash_loop_stops_after_three_attempts` failed on that source:
with fake failed graphical/text commands, the supervisor never reached recovery
and exceeded the original two-second harness deadline. An independent bounded
trace then recorded 13 graphical launches and 12 console launches before the
test harness stopped the original loop. No disk commands were executed.

Measurable criteria, recorded before implementation in the task's local handoff:
three failed automatic attempts maximum; one launch per deliberate retry without
refilling the budget; stable recovery for launch/dependency failures; normal
exit and console fallback preserved; honest log availability; explicit cancellable
power choices with a fail-closed engine check; no erase command or bypass;
keyboard and spoken guidance with documented limits; no second systemd restart
loop; EOF and signals cannot restart the app. The numbered menu and details must
remain readable on supported small consoles. Full local and hosted ISO/QEMU
verification remains required before accepting the change.
