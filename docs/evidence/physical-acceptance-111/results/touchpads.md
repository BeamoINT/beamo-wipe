# Touchpad and pointer results — PHY-TP

Live image uses `xserver-xorg-input-libinput`. X starts even if no pointer is found (`AllowMouseOpenFail`).

Desktop towers with no touchpad: mark PHY-TP-01 **Excluded** (reason: no touchpad) — that is not a Fail.

Every Result below is **NOT TESTED**.

| ID | Variant | Expected (physical) | Device (fill) | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| PHY-TP-01 | Built-in touchpad | Pointer moves; click selects a disk card; pad does not type random characters into the confirm box | | NOT TESTED | `photos/PHY-TP-01-*` |
| PHY-TP-02 | Touchpad disabled in firmware or Fn-key | Keyboard-only path still works (see PHY-KB-01). Record how you disabled it. | | NOT TESTED | `logs/PHY-TP-02-*` |
| PHY-TP-03 | USB mouse instead of a pad | Click selects; keyboard still works | | NOT TESTED | `photos/PHY-TP-03-*` |
| PHY-TP-04 | No pointer at all | Wizard still starts; Tab/Enter/Space complete the non-destructive screens | | NOT TESTED | `logs/PHY-TP-04-*` |

Notes:
