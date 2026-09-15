# Firmware results — PHY-FW

Related software matrix: [`docs/compatibility-matrix.md`](../../../compatibility-matrix.md) §4 (FW-01…FW-06). Those rows are QEMU/fixture **Supported** or documented unsupported-by-design. They are not physical Passes.

Expected live loaders: BIOS `syslinux`, UEFI `grub-efi` (`packaging/live`). Signed Debian EFI components still depend on the PC’s trust store ([`docs/boot-card.md`](../../../boot-card.md), [`docs/claims.md`](../../../claims.md)).

Every Result below is **NOT TESTED**. Fill Machine / firmware from the sticker and setup screen; do not guess.

| ID | Variant | Related | Expected (physical) | Machine / firmware (fill) | Result | Evidence (`photos/` or `logs/`) |
| --- | --- | --- | --- | --- | --- | --- |
| PHY-FW-01 | Legacy BIOS | FW-01 | USB appears in the firmware menu; Beamo menu then wizard is the first UI; boot USB is not a wipe target | | NOT TESTED | `photos/PHY-FW-01-*` |
| PHY-FW-02 | UEFI, Secure Boot off | FW-02, FW-04 | Same as PHY-FW-01 via the UEFI USB entry | | NOT TESTED | `photos/PHY-FW-02-*` |
| PHY-FW-03 | UEFI, Secure Boot on, no Beamo key enrolled | FW-03 | Firmware rejects the USB or does not list it. Wizard never starts. Record the exact message. Do not bypass. | | NOT TESTED | `photos/PHY-FW-03-*` |
| PHY-FW-04 | UEFI, Secure Boot explicitly disabled on lab firmware | FW-04 | After disable on **lab** hardware only, USB boots as PHY-FW-02 | | NOT TESTED | `photos/PHY-FW-04-*` |
| PHY-FW-05 | CSM / BIOS compatibility on a UEFI PC | FW-05 | USB boots through the compatibility path if the firmware offers it; wizard first UI | | NOT TESTED | `photos/PHY-FW-05-*` |
| PHY-FW-06 | Dell boot menu | FW-06 | F12 opens the boot menu; USB can be chosen | | NOT TESTED | `photos/PHY-FW-06-*` |
| PHY-FW-07 | HP boot menu | FW-06 | F9 or Esc opens the boot menu; USB can be chosen | | NOT TESTED | `photos/PHY-FW-07-*` |
| PHY-FW-08 | Lenovo boot menu | FW-06 | F12 opens the boot menu; USB can be chosen | | NOT TESTED | `photos/PHY-FW-08-*` |
| PHY-FW-09 | ASUS / Acer / MSI / Gigabyte boot menu | FW-06 | Key from the boot card (F8/Esc, F12, F11, F12) opens the menu; USB can be chosen. Record the vendor. | | NOT TESTED | `photos/PHY-FW-09-*` |
| PHY-FW-10 | Fast Boot / USB boot disabled in firmware | — | USB missing from the menu is a firmware setting, not a Beamo bug. Record the setting you changed on **lab** hardware. | | NOT TESTED | `photos/PHY-FW-10-*` |
| PHY-FW-11 | Signed Debian EFI vs revocation / trust updates | — | Record firmware’s Secure Boot / revocation state. App does not change Secure Boot. If rejected, keep PHY-FW-03 language. | | NOT TESTED | `photos/PHY-FW-11-*` |
| PHY-FW-12 | BitLocker recovery warning | — | If this PC might boot Windows again, confirm the recovery key is reachable **before** firmware changes. Record that you checked. | | NOT TESTED | `logs/PHY-FW-12-*` |

Notes (what you saw; leave blank until a run):
