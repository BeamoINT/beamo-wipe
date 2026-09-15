# Keyboard results — PHY-KB

Related software matrix: [`docs/compatibility-matrix.md`](../../../compatibility-matrix.md) §8 (KB-01…KB-08). Those rows are Tk/console tests and QEMU QMP keys. They are not a human keyboard Pass.

Shipped layout is US QWERTY (`packaging/live/config/includes.chroot/etc/default/keyboard`). The wizard may apply us/fr/de for this X session only.

Every Result below is **NOT TESTED**.

| ID | Variant | Related | Expected (physical) | Keyboard (fill) | Result | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| PHY-KB-01 | Built-in laptop keyboard | KB-01 | Keys reach the wizard: splash, owner box, pick list Up/Down, token, method 1/2/3 | | NOT TESTED | `photos/PHY-KB-01-*` |
| PHY-KB-02 | External USB keyboard, no built-in | KB-01 | Same as PHY-KB-01 | | NOT TESTED | `photos/PHY-KB-02-*` |
| PHY-KB-03 | Held Enter across a screen change | KB-03 | Must not fire Erase when the countdown ends while Enter is still down | | NOT TESTED | `logs/PHY-KB-03-*` |
| PHY-KB-04 | Escape / Back | KB-06 | Esc returns where the wizard allows; leaving last-chance clears the countdown | | NOT TESTED | `logs/PHY-KB-04-*` |
| PHY-KB-05 | Firmware boot-menu key on this PC | FW-06 | The labeled key opens the firmware menu (see firmware sheet) | | NOT TESTED | `photos/PHY-KB-05-*` |
| PHY-KB-06 | Speech hotkey S at the Beamo menu | — | Press S while the menu is showing; accessible view starts. Menu waits about five seconds if you do nothing. | | NOT TESTED | `logs/PHY-KB-06-*` |
| PHY-KB-07 | Layout us / fr / de in the wizard | — | Record which layout you selected; session only, restart returns to US | | NOT TESTED | `photos/PHY-KB-07-*` |

Notes:
