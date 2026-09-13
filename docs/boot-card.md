# Beamo Wipe — boot card (print one side)

**Beamo Wipe** — this USB erases a disk with **nwipe** (open source).
You must own this PC and disk, or have written permission.

For the new desktop-readable USB image: open **Start Beamo Wipe.exe** on
Windows, or **Start Beamo Wipe Linux** on a supported Linux desktop. Approve
the operating system's permission prompt. The application checks readiness
and offers **Restart into Beamo Wipe** when supported. Save your work first.
If the application cannot open or offer a restart, use the boot menu below.

**Erasing still requires booting this USB.** Inserting it or opening the
application does not erase anything. This card describes the development
image; it does not change the contents of previously sold sticks.

## Open the boot menu (typical keys)

| PC | Boot menu key |
| --- | --- |
| Dell | F12 |
| HP | F9 or Esc |
| Lenovo | F12 |
| ASUS | F8 or Esc |
| Acer | F12 |
| MSI | F11 |
| Gigabyte | F12 |

Windows 11 fallback: Settings → System → Recovery → Advanced startup →
Restart now → Use a device (UEFI).
Windows 10: Settings → Update & Security → Recovery → Advanced startup →
Restart now → Use a device (UEFI).
Those keys and menus vary by PC. Open START-HERE.html on the USB for the
full steps.

If you might start this Windows installation again, confirm you can reach
the BitLocker recovery key **before** changing firmware, boot order, or
Secure Boot. Those changes can trigger BitLocker recovery. Do not disable
Secure Boot as a routine step.

Plug into a **USB-A or USB-C** port on the PC, not a keyboard hub if you
can avoid it. Then restart and tap the key above.

**Not for Apple Silicon Macs. Not for Chromebooks.** Some Intel Macs may
show this USB; many will not.

## After it boots

When the Beamo Wipe menu appears, pick **Beamo Wipe: start the erase guide**
(or **troubleshoot startup** if the PC does not start normally). Opening the
guide erases nothing by itself.

The menu also offers **Beamo Wipe: speech for screen readers** — press **S**
as soon as the menu appears. On UEFI computers a short two-tone beep plays
when the menu is showing; the older BIOS menu does not beep. The menu waits
five seconds, then starts the ordinary guide; if that happens, press **F8**
in the guide to switch to the spoken view. Choosing either entry erases
nothing.

1. Read the first screen. This is nwipe with a guide on top.
2. Check the owner box.
3. Pick the disk by **size and serial**. The Beamo USB is marked and
   cannot be selected.
4. Type the confirm number. Wait five seconds. Erase.

If the stick never appears: try another port, disable fast boot, or allow
USB boot in firmware.

The development image includes signed Debian EFI components. Secure Boot
still depends on the computer's trust settings and revocation updates. If
firmware rejects the USB, record its exact message and use the computer
manufacturer's guidance or contact support. The application does not change
Secure Boot settings. Older sticks may contain a different boot image.

Source and license: **https://github.com/BeamoINT/beamo-wipe**
(print a QR to that README, not a store page).
