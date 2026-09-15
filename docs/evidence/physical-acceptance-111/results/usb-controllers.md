# USB controller results — PHY-USB

QEMU EHCI/xHCI/BOT/UAS coverage lives in [`docs/usb-simulation-lab-2026-09-07.md`](../../../usb-simulation-lab-2026-09-07.md) and [`docs/evidence/usb-lab-20260907/`](../../usb-lab-20260907/). That lab is **not** this matrix. Do not copy those Passes here.

On the physical PC, record what the live session reports (`lsblk` transport, kernel driver if you have a diagnostic export). Do not invent controller names.

A USB-SATA bridge may present as `tran sata` ([`docs/compatibility-matrix.md`](../../../compatibility-matrix.md) BF-007). Live mount identification must still fail closed if identity is uncertain.

Every Result below is **NOT TESTED**.

| ID | Variant | Expected (physical) | Controller / driver (fill) | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| PHY-USB-01 | USB 2 host path (EHCI or USB 2 port on xHCI) | Stick enumerates; firmware can boot it; wizard identifies boot USB | | NOT TESTED | `logs/PHY-USB-01-*` |
| PHY-USB-02 | USB 3 host path (xHCI SuperSpeed port) | Same as PHY-USB-01 | | NOT TESTED | `logs/PHY-USB-02-*` |
| PHY-USB-03 | Mass-storage BOT as the live OS used it | Stick usable as boot media; identity stable | | NOT TESTED | `logs/PHY-USB-03-*` |
| PHY-USB-04 | UAS if the live OS bound `uas` to this stick | Record driver. Windows UAS Code 10 in the USB lab does **not** decide this live-Linux row. | | NOT TESTED | `logs/PHY-USB-04-*` |
| PHY-USB-05 | USB-SATA bridge / enclosure used as a **target** (not the Beamo stick) | Only if a disposable disk is attached that way. Must show as a whole disk with serial/size. Hidden RAID/members stay unsupported. | | NOT TESTED | `logs/PHY-USB-05-*` |
| PHY-USB-06 | Two USB sticks at once (Beamo + other) | Duplicate `BEAMO_WIPE` labels fail closed (no selectable disks). A second non-Beamo stick must not become the boot identity. | | NOT TESTED | `logs/PHY-USB-06-*` |

Notes:
