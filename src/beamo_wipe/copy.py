# SPDX-License-Identifier: GPL-3.0-or-later
"""User-facing strings. 8th-grade English. No forbidden claims."""

from beamo_wipe.models import Disk, MethodId

APP_NAME = "Beamo Wipe"

SPLASH_TAGLINE = (
    "This USB will restart your computer into a wipe tool. "
    "It will not run from Windows."
)

# Small quiet line at the foot of the splash. Factual: the pinned engine.
SPLASH_META = "Guided front-end for nwipe v0.42"

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

OWNER_LEAD = (
    "Check the box only if this is your computer, or you have written permission."
)

BOOT_USB_BANNER = "This is the Beamo USB — do not erase"
BOOT_DISC_BANNER = "This is the Beamo boot disc — do not erase"

IDENTIFY_ERROR = (
    "Cannot tell which disk is this USB. Unplug extra USB drives and reboot."
)

REDISCOVER_ERROR = "Could not re-read disks. Erase did not start."

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
    "Run ./preview to see the screens on this computer, or boot the live USB."
)

DONE_OK_PREVIEW = "Preview finished. Nothing on this computer was erased."
DONE_FAIL_PREVIEW = (
    "Preview of a failed wipe. Nothing on this computer was erased."
)

SAME_SIZE_HINT = (
    "Two disks have the same size. Read the serial number. "
    "Do not pick by size alone."
)

RECOMMENDED_TAG = "Recommended"

CONFIRM_MATCH_WAIT = "This must match exactly before you can continue."
CONFIRM_MATCH_OK = "Matches. You can continue."

COUNTDOWN_CAPTION = "seconds until the Erase button unlocks"
COUNTDOWN_READY = "The Erase button is ready."

METHOD_CARDS = {
    MethodId.EVERYDAY: {
        "title": "Everyday",
        "blurb": "Good for selling or recycling a home PC. Usually the right choice.",
        "pace": "Often one to a few hours on a large hard disk. Leave it until Finished.",
        "key": "1",
    },
    MethodId.EXTRA: {
        "title": "Extra thorough",
        "blurb": (
            "More passes. Much slower. Use if a workplace asked for more "
            "than a normal wipe."
        ),
        "pace": "Several hours is common. Can take much longer. Leave it until Finished.",
        "key": "2",
    },
    MethodId.QUICK_ZERO: {
        "title": "Quick zero",
        "blurb": "Fills the disk with zeros. Fastest. Weaker on some SSDs.",
        "pace": "Faster than Everyday. Still wait for the Finished screen.",
        "key": "3",
    },
}

ADVANCED_LEAD = (
    "Raw nwipe method names. Technicians only. The happy-path screens stay simple."
)

ADVANCED_LOG_NOTE = (
    "To save a log, plug in a second USB that is not the target disk "
    "and copy the log file there."
)

BTN_UNDERSTAND = "I understand"
BTN_SHUTDOWN = "Shut down"
BTN_CLOSE_PREVIEW = "Close preview"
BTN_RUN_AGAIN = "Run again"
BTN_CONTINUE = "Continue"
BTN_BACK = "Back"
BTN_ERASE = "Erase now"
BTN_ADVANCED = "Advanced (technicians)"

PREVIEW_BANNER = "PREVIEW on this computer — fake disks — nothing is erased"

HINT_DEFAULT = "Enter continues.  Esc goes back."
HINT_PICK = "Click a disk, or use Up/Down.  Enter continues.  Esc goes back."
HINT_OWNER = "Space checks the box.  Enter continues when it is checked."
HINT_METHOD = "Press 1, 2, or 3 to choose.  Enter continues."
HINT_CONFIRM = "Type exactly what the prompt asks for, then Enter."
HINT_LAST_CHANCE = "Esc goes back.  Enter erases after the countdown."
HINT_BLOCKED = "Enter shuts down.  Esc goes back."
HINT_DONE = "Enter shuts down."
HINT_WORKING = "Leave this USB plugged in until the finished screen."
HINT_SPLASH = "Press any key to continue."


def confirm_warning(disk: Disk) -> str:
    return (
        f"This will erase every file on {disk.display_name}, {disk.size_phrase}. "
        "This cannot be undone."
    )


def erase_now_label(disk: Disk) -> str:
    serial = disk.serial or "no serial"
    return f"Erase {disk.display_name} {disk.size_phrase} ({serial}) now."


def pick_subtitle() -> str:
    return (
        "Click the disk you want to erase. Look at size and serial. "
        "Nothing is chosen until you click."
    )
