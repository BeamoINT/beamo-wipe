# Live-session power policy

This is the operating-system policy for the Beamo Wipe live USB. It does not
control firmware. A held power button, a firmware lid action, or pulling the
cord can still stop an erase.

## Reminder

If the computer has a battery, plug it into wall power before erasing. A power
cut stops the erase. Unsaved reports are lost.

## Display blanking versus sleep

| Event | Intended OS behavior | Notes |
| --- | --- | --- |
| Idle | Display may blank after 10 minutes | Xorg `BlankTime`. A key or mouse click unblanks. This is not suspend. |
| DPMS standby/suspend/off | Not requested | Xorg `StandbyTime`, `SuspendTime`, and `OffTime` are 0. |
| systemd idle action | Ignore | `IdleAction=ignore` |
| Sleep / hibernate keys | Ignore | logind `HandleSuspendKey` / `HandleHibernateKey` |
| Lid close | Ignore at logind | Firmware on some laptops still sleeps. Not claimed without a hardware receipt. |
| Short power-button press | Ignore | Use **Shut down** in the wizard. |
| Held power button | Firmware | Outside this USB. May cut power during an erase. |
| Wizard **Shut down** | `systemctl poweroff` | Blocked while Checking, Working, Stopping, refresh, export, or evidence save. |
| Automatic sleep during erase | Refused | `AllowSuspend=no`, masked `suspend.target`, and a sleep/idle inhibit while nwipe runs. |

Cancellation stays on Working until the engine stop is confirmed. Unconfirmed
stops stay fail-closed (`stop_unconfirmed`). Genuine power loss is not hidden:
session recovery does not resume an erase, and unsaved evidence is lost.

## Files

- `packaging/live/config/includes.chroot/etc/systemd/logind.conf.d/beamo-kiosk.conf`
- `packaging/live/config/includes.chroot/etc/systemd/sleep.conf.d/beamo-kiosk.conf`
- `packaging/live/config/includes.chroot/etc/X11/xorg.conf.d/10-beamo.conf`
- `packaging/live/config/includes.chroot/usr/local/bin/beamo-wipe` (`xset` wake path)
- `src/beamo_wipe/sleep_inhibit.py` (does not wrap nwipe; does not inhibit shutdown)

## Evidence

Source tests pin the files above. Hosted QEMU inspects the squashfs copies.
Lid close and firmware power-button hold require physical hardware receipts
and are not implied by QEMU. See
[the dated receipts](evidence/live-session-power-20260910.md).

## Laptop guidance and power readings

Keep wall power connected and keep the lid open. The introduction, final review,
Checking, Working and Stopping screens show power information. The preview uses
explicitly labelled fake readings; its Fake power selector lets reviewers change
power during an operation without restarting it. The static offline helper cannot
read power status. Console input prompts show the latest sampled status when
printed; unlike Tk, GTK and the running console loop, a blocking plain-text input
prompt does not update until input returns.

The live wizard reads Linux `/sys/class/power_supply/*/uevent` in one background
worker. Device-scoped supplies are excluded. AC is never inferred from battery
charge or charging status. Percentages must be integers from 0 to 100 and the
battery must report present. Missing, malformed or unreadable data stays unknown.
Multiple batteries show the lowest available charge and disclose missing charge
readings. No system battery reported does not certify that the computer lacks one.
The driver may omit attributes; see the [Linux power supply documentation](https://docs.kernel.org/power/power_supply_class.html).

Readings refresh every five seconds while the UI runs; after ten seconds without
a timely sample the displayed information becomes unknown. A stalled driver
cannot block the UI or create an unbounded number of workers. Failed reads replace
old readings; a later successful read recovers without restarting the wizard.
Reported charge at or below 20% shows a low-battery warning, including on AC.
A charger can be connected but insufficient or faulty. These are reported
readings, not a guarantee of available runtime or successful sleep inhibition.

Power readings are advisory: they do not start, cancel, pause, resume, shut down,
or change authorization or disk selection. Use Stop erase, confirm the stop, and wait for the
result before shutting down. OS lid and short-button policy remains as above;
keep the lid open even though logind is configured to ignore it. Firmware power
cuts, physical lid behavior, thermal limits and real battery accuracy still need
receipts from explicitly dedicated hardware. No such hardware claim follows from
fixture, rendered, source-policy or QEMU tests.

Stopping cannot restore files already erased. Keep erasing dismisses the stop confirmation. If the stop could not be confirmed, the erase may still be running; keep the disk and USB connected.
