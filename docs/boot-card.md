# Beamo Wipe — boot card (print one side)

**Beamo Wipe** — this USB erases a disk with **nwipe** (open source).
You must own this PC and disk, or have written permission.

This does **not** run from Windows. Restart and boot from this USB.

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

Windows 10/11 fallback: Settings → System → Recovery → Advanced startup
→ Restart now → Use a device → pick this USB.

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

If the computer says Secure Boot will not start the stick: this image is
unsigned, so that refusal is the firmware doing its job. Enter firmware
settings yourself (setup key: F2 Dell/Acer, Esc then F10 HP, F1 Lenovo,
Del ASUS/MSI/Gigabyte), set Secure Boot to Disabled under Security or
Boot, save and exit, then pick the USB from the boot menu. You can turn
Secure Boot back on afterwards. We do not ship Secure Boot bypass tools.

Source and license: **https://github.com/BeamoINT/beamo-wipe**
(print a QR to that README, not a store page).
