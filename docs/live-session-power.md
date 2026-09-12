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
