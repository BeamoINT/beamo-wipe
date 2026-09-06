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

Windows 11 fallback: Settings → System → Recovery → Advanced startup.
Windows 10: Settings → Update & Security → Recovery → Advanced startup.
Then choose Restart now → Use a device → pick this USB, if it is listed.

Plug into a **USB-A or USB-C** port on the PC, not a keyboard hub if you
can avoid it. Then restart and tap the key above.

**Not for Apple Silicon Macs. Not for Chromebooks.** Some Intel Macs may
show this USB; many will not.

## After it boots

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
