# Monitor results — PHY-MON

Related software matrix: [`docs/compatibility-matrix.md`](../../../compatibility-matrix.md) §7 (DISP-01…DISP-07). Those rows are Xvfb 72 DPI, interpolation, or documented degraded/untested. They are not panel Passes.

Live Xorg does not force VESA on every GPU (`packaging/live/config/includes.chroot/etc/X11/xorg.conf.d/10-beamo.conf`). Display blanking is 10 minutes; that is not sleep ([`docs/live-session-power.md`](../../../live-session-power.md)).

Every Result below is **NOT TESTED**.

| ID | Variant | Related | Expected (physical) | Panel / output (fill) | Result | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| PHY-MON-01 | Built-in laptop/desktop panel at or above 1024×740 | DISP-01, DISP-02, DISP-03 | Wizard fits; primary action visible; pick list can scroll | | NOT TESTED | `photos/PHY-MON-01-*` |
| PHY-MON-02 | External HDMI (or DisplayPort) | DISP-04 | Wizard on the external screen; content not stretched into unreadability | | NOT TESTED | `photos/PHY-MON-02-*` |
| PHY-MON-03 | External VGA / DVI / adapter | DISP-04 | Same as PHY-MON-02 if the PC has that output; otherwise Excluded | | NOT TESTED | `photos/PHY-MON-03-*` |
| PHY-MON-04 | Dual display (lid + external) | — | Record which screen shows the wizard. Do not claim mirroring. | | NOT TESTED | `photos/PHY-MON-04-*` |
| PHY-MON-05 | 800×600 or similar short panel | DISP-05 | Degraded: may need scroll; primary action still reachable from the keyboard | | NOT TESTED | `photos/PHY-MON-05-*` |
| PHY-MON-06 | HiDPI / scaled firmware panel | DISP-06 | Record DPI/scale. HiDPI is not a claimed supported mode; clipping is Fail only against an advertised claim, not against this row’s “record what you saw.” | | NOT TESTED | `photos/PHY-MON-06-*` |
| PHY-MON-07 | Idle blanking (~10 min), key/mouse unblank | — | Panel blanks; a key or click restores the wizard. This is not suspend. | | NOT TESTED | `logs/PHY-MON-07-*` |
| PHY-MON-08 | No mouse attached | DISP-07 | X still starts (`AllowMouseOpenFail`). Keyboard can drive the wizard. | | NOT TESTED | `photos/PHY-MON-08-*` |

Notes:
