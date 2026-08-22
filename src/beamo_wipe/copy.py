# SPDX-License-Identifier: GPL-3.0-or-later
"""User-facing strings. 8th-grade English. No forbidden claims."""

from beamo_wipe.models import Disk, DiskKind, MethodId

APP_NAME = "Beamo Wipe"

# --- Screen titles (happy path talks like a person) ------------------------

TITLE_WHAT = "Here's what happens"
TITLE_OWNER = "Is this your computer?"
TITLE_PICK = "Which disk should we erase?"
TITLE_CONFIRM = "Make sure this is the right disk"
TITLE_METHOD = "How thorough"
TITLE_ADVANCED = "Advanced"
TITLE_LAST = "Last chance to stop"
TITLE_WORKING = "Erasing now"
TITLE_DONE_OK = "Finished"
TITLE_DONE_FAIL = "The erase did not finish"
TITLE_BLOCKED = "Stop"
TITLE_EMPTY = "No disk to erase"

# --- Splash: they already booted. Do not lecture. --------------------------

SPLASH_TAGLINE = (
    "You already started from this USB. Next you will pick a disk to erase."
)

WHAT_LEAD = "Nothing starts until you say so."

WHAT_BULLETS = (
    "You will pick a disk. Everything on it will be erased. "
    "You cannot get the files back.",
    "This is for regular Windows PCs that start from this USB. "
    "Not Apple Silicon Macs. Not Chromebooks.",
)

# Closed-by-default Show more. Help first; nwipe by name only for honesty.
SECURE_BOOT_HINT = (
    "If this USB does not show up on another computer, you may need to allow "
    "USB start in that computer's settings."
)

ENGINE_LINE = "This uses nwipe, free software that erases disks."

WHAT_MORE = SECURE_BOOT_HINT + " " + ENGINE_LINE

OWNER_CHECKBOX = (
    "I own this computer and these disks, or I have written permission to erase them."
)

OWNER_LEAD = "Check the box, then continue."

BOOT_USB_BANNER = "This is the Beamo USB — do not erase"
BOOT_DISC_BANNER = "This is the Beamo boot disc — do not erase"

IDENTIFY_ERROR = (
    "We cannot tell which disk is this USB. Unplug extra USB sticks and start again."
)

REDISCOVER_ERROR = "Could not check the disks again. Erase did not start."

EMPTY_DISKS = (
    "We cannot find another disk. Shut down, plug in the drive you want to erase, "
    "and start from this USB again."
)

SSD_FOOTER = "On an SSD, leftover data can depend on the drive."

WORKING_PULSE = "Leave the USB in. Do not turn the PC off."

DONE_OK = "Done. You can shut down and take out the USB."

DONE_FAIL = (
    "The erase did not finish. Files may still be on the disk. "
    "You can try again, or use another computer."
)

NOT_LIVE_ERROR = (
    "Beamo Wipe only erases disks after you start the computer from this USB. "
    "It will not erase a disk from Windows. "
    "Run ./preview to see the screens on this computer, or start from the USB."
)

DONE_OK_PREVIEW = "Preview finished. Nothing on this computer was erased."
DONE_FAIL_PREVIEW = (
    "Preview of a failed erase. Nothing on this computer was erased."
)

SAME_SIZE_HINT = (
    "Two disks are the same size. Look at the characters under the name "
    "so you pick the right one."
)

RECOMMENDED_TAG = "Recommended"

CONFIRM_LEAD = "Type what we ask for, then continue."

CONFIRM_MATCH_WAIT = "Type it exactly, then you can continue."
CONFIRM_MATCH_OK = "That matches. You can continue."

COUNTDOWN_CAPTION = "seconds until you can press Erase"
COUNTDOWN_READY = "You can press Erase now."

METHOD_LEAD = "Everyday is usually right."

LAST_LEAD = "If this is the wrong disk, go back."

METHOD_CARDS = {
    MethodId.EVERYDAY: {
        "title": "Everyday",
        "blurb": "Good for selling or recycling a home PC. Usually the right choice.",
        "pace": "Often a few hours. Leave it until Finished.",
        "key": "1",
    },
    MethodId.EXTRA: {
        "title": "Extra thorough",
        "blurb": (
            "Does the erase more times. Much slower. Use if a workplace "
            "asked for more than a normal erase."
        ),
        "pace": "Several hours, sometimes longer. Leave it until Finished.",
        "key": "2",
    },
    MethodId.QUICK_ZERO: {
        "title": "Quick zero",
        "blurb": "The fastest option. Not as thorough on some SSDs.",
        "pace": "Faster. Still wait for Finished.",
        "key": "3",
    },
}

ADVANCED_LEAD = (
    "These are the nwipe names. For technicians. The other screens stay simple."
)

ADVANCED_LOG_NOTE = (
    "To save a log, plug in a second USB that is not the disk you erased "
    "and copy the log file there."
)

ADVANCED_LOG_LABEL = "Log file (never on the disk you erase): "

BTN_UNDERSTAND = "I understand"
BTN_SHUTDOWN = "Shut down"
BTN_CLOSE_PREVIEW = "Close preview"
BTN_RUN_AGAIN = "Run again"
BTN_CONTINUE = "Continue"
BTN_BACK = "Back"
BTN_ERASE = "Erase now"
BTN_ADVANCED = "Advanced (technicians)"
BTN_MORE = "Show more"
BTN_LESS = "Show less"

PREVIEW_BANNER = "PREVIEW on this computer — fake disks — nothing is erased"

HINT_DEFAULT = "Enter continues.  Esc goes back."
HINT_PICK = "Click a disk, or use Up/Down.  Enter continues.  Esc goes back."
HINT_OWNER = "Space checks the box.  Enter continues when it is checked."
HINT_METHOD = "Press 1, 2, or 3 to choose.  Enter continues."
HINT_CONFIRM = "Type exactly what we ask for, then Enter."
HINT_LAST_CHANCE = "Esc goes back.  Enter erases after the countdown."
HINT_BLOCKED = "Enter shuts down.  Esc goes back."
HINT_DONE = "Enter shuts down."
HINT_WORKING = "Leave this USB in until you see Finished."
HINT_SPLASH = "Press any key to continue."

NO_CODE = "no serial"


def kind_label(kind: DiskKind) -> str:
    """Happy-path chip: name people know. NVMe is a kind of SSD."""
    if kind == DiskKind.HDD:
        return "Hard disk"
    if kind in (DiskKind.SSD, DiskKind.NVME):
        return "SSD"
    return ""


def confirm_type_size(token: str) -> str:
    return f"Type these numbers so we know it is the right disk: {token}"


def confirm_type_four(token: str) -> str:
    return f"Type these 4 characters so we know it is the right disk: {token}"


def confirm_type_chars(token: str) -> str:
    return f"Type these characters so we know it is the right disk: {token}"


def confirm_warning(disk: Disk) -> str:
    return (
        f"Every file on {disk.display_name}, {disk.size_phrase}, will be erased. "
        "You cannot get them back."
    )


def erase_now_label(disk: Disk) -> str:
    return (
        f"This will erase {disk.display_name}, {disk.size_phrase}. "
        "You cannot get the files back."
    )


def pick_subtitle() -> str:
    return "Click the name and size that match this PC."
