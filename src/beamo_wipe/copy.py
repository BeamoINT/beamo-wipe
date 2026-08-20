# SPDX-License-Identifier: GPL-3.0-or-later
"""User-facing strings. 8th-grade English. No forbidden claims."""

from beamo_wipe.models import Disk, MethodId

APP_NAME = "Beamo Wipe"

SPLASH_TAGLINE = (
    "This USB will restart your computer into a wipe tool. "
    "It will not run from Windows."
)

WHAT_BULLETS = (
    "This is a guided front-end for nwipe, free open-source disk erasure software.",
    "You are about to erase a disk forever. Files cannot be undone.",
    "This PC must be an x86_64 machine that can boot from USB. "
    "Not Apple Silicon Macs. Not Chromebooks.",
)

ENGINE_LINE = (
    "The erasure engine is nwipe. Beamo did not write that engine. "
    "There is no warranty."
)

SECURE_BOOT_HINT = (
    "If the USB does not appear, you may need to allow USB boot in this "
    "PC’s firmware settings."
)

OWNER_CHECKBOX = (
    "I own this computer and these disks, or I have written permission to erase them."
)

BOOT_USB_BANNER = "This is the Beamo USB — do not erase"
BOOT_DISC_BANNER = "This is the Beamo boot disc — do not erase"

IDENTIFY_ERROR = (
    "Cannot tell which disk is this USB. Unplug extra USB drives and reboot."
)

EMPTY_DISKS = (
    "No other disks found. Power off, connect the drive you want to wipe "
    "(SATA/NVMe), and boot this USB again."
)

SSD_FOOTER = (
    "On SSDs, the drive’s own controller decides what is left. "
    "This is not a lab certificate."
)

WORKING_PULSE = "Still working — do not unplug."

DONE_OK = "Finished. You can shut down and remove the USB."

DONE_FAIL = (
    "The wipe did not finish. The disk may still have data. "
    "Try again or use another machine."
)

NOT_LIVE_ERROR = (
    "Beamo Wipe only erases disks from the bootable USB environment. "
    "It will not wipe a disk from inside a running operating system. "
    "Use --demo to preview the screens, or boot the live USB."
)

METHOD_CARDS = {
    MethodId.EVERYDAY: {
        "title": "Everyday",
        "blurb": "Good for selling or recycling a home PC. Usually the right choice.",
        "key": "1",
    },
    MethodId.EXTRA: {
        "title": "Extra thorough",
        "blurb": (
            "More passes. Much slower. Use if a workplace asked for more "
            "than a normal wipe."
        ),
        "key": "2",
    },
    MethodId.QUICK_ZERO: {
        "title": "Quick zero",
        "blurb": "Fills the disk with zeros. Fastest. Weaker on some SSDs.",
        "key": "3",
    },
}

BTN_UNDERSTAND = "I understand"
BTN_SHUTDOWN = "Shut down"
BTN_CONTINUE = "Continue"
BTN_BACK = "Back"
BTN_ERASE = "Erase now"
BTN_ADVANCED = "Advanced (technicians)"


def confirm_warning(disk: Disk) -> str:
    return (
        f"This will erase every file on {disk.display_name}, {disk.size_phrase}. "
        "This cannot be undone."
    )


def erase_now_label(disk: Disk) -> str:
    return f"Erase {disk.display_name} {disk.size_phrase} now."


def pick_subtitle() -> str:
    return "Choose the disk you want to erase. Look at size and serial."
