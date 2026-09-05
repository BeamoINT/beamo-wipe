# SPDX-License-Identifier: GPL-3.0-or-later
"""User-facing strings. 8th-grade English. No forbidden claims."""

from beamo_wipe.inventory import EMPTY_STEPS
from beamo_wipe.outcomes import VIEWS
from beamo_wipe.models import Disk, DiskKind
from beamo_wipe.methods import METHODS
from beamo_wipe.storage_limits import OVERWRITE_LIMITS

APP_NAME = "Beamo Wipe"

# --- Screen titles (happy path talks like a person) ------------------------

TITLE_WHAT = "Here's what happens"
TITLE_OWNER = "Is this your computer?"
TITLE_PICK = "Which disk should we erase?"
TITLE_CONFIRM = "Make sure this is the right disk"
TITLE_METHOD = "Choose an erase method"
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

EMPTY_DISKS = EMPTY_STEPS

SSD_FOOTER = OVERWRITE_LIMITS + " Not a formal certificate."

WORKING_PULSE = "Leave the USB in. Do not turn the PC off."

DONE_OK = VIEWS["verified"].message

DONE_FAIL = VIEWS["engine_failed"].announcement

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

METHOD_LEAD = "Compare overwrite and read-back passes."

LAST_LEAD = "If this is the wrong disk, go back."

METHOD_CARDS = {
    method: {
        "title": spec.title,
        "blurb": spec.overwrite_description,
        "pace": spec.verification_description,
        "key": str(index),
    }
    for index, (method, spec) in enumerate(METHODS.items(), 1)
}

ADVANCED_LEAD = (
    "These are the nwipe names. For technicians. The other screens stay simple."
)

REPORT_HELP_TITLE = "Need a report?"
REPORT_WANTED = "I want to save a report"
REPORT_VOLATILE = (
    "Any unsaved report is lost when this live session shuts down or loses power."
)
REPORT_HELP_SECTIONS = (
    "Saving a report is optional. You need a separate removable FAT32 USB device, "
    "with one writable, unmounted volume. It must be different from the Beamo boot USB and "
    "the disk you erase. exFAT, NTFS, FAT12 and FAT16 are not supported. "
    "Beamo Wipe does not format or repair report media.",
    "Keep the report USB unplugged while choosing the erase target, confirming, "
    "and erasing. Only after the erase has stopped and the result screen offers "
    "Save report to USB, insert exactly one report USB, then choose Save report to USB. "
    "Leave the Beamo boot USB and selected erase disk connected.",
    "If you already inserted the report USB before erasing, remove only that "
    "report USB. Leave the boot USB and erase disk connected. Choose Check disks "
    "again, then choose and confirm the erase target again. Do not guess which "
    "disk to unplug or erase.",
    REPORT_VOLATILE + " This checkbox remembers only your preference for this "
    "session. It does not choose media, save a report, or prevent shutdown. "
    "A report is available only if the operation produced eligible evidence. "
    "Erase reports include disk identifiers; review them before sharing.",
    "Wait for the saved and safe-to-remove message before removing the report USB. "
    "If saving fails, follow the displayed error and retry while this session is "
    "still running. Never remove report media while saving.",
    "If the wipe cannot start, Diagnostic report has a separate flow: keep the "
    "report USB unplugged for Prepare and insert it only when prompted. "
    "Diagnostics are not erase evidence and do not establish that an erase ran.",
)
REPORT_HELP_TEXT = "\n\n".join(REPORT_HELP_SECTIONS)
REPORT_INSERT = (
    "No erase is running. Leave the boot USB and selected disk connected. "
    "Insert one separate FAT32 USB, then choose Save report to USB. "
    "The report includes disk identifiers."
)
ADVANCED_LOG_NOTE = (
    "Keep the separate FAT32 report USB unplugged until the erase has stopped "
    "and Save report to USB is offered. Then insert it before choosing Save. "
    "Leave the boot USB and selected disk connected. "
    + REPORT_VOLATILE + " Open Need a report? for requirements and safe removal."
)


def report_aftercare(*, can_save: bool, status: str, message: str) -> str:
    """No insertion prompt unless the existing evidence gate allows saving."""
    if status == "saved":
        return message
    detail = message or (REPORT_INSERT if can_save else "Report export is unavailable.")
    return detail + " " + REPORT_VOLATILE


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
BTN_SAVE_REPORT = "Save report to USB"

PREVIEW_BANNER = "PREVIEW on this computer — fake disks — nothing is erased"

HINT_DEFAULT = "Enter continues.  Esc goes back."
HINT_PICK = "Click a disk, or use Up/Down.  Enter continues.  Esc goes back."
HINT_OWNER = "Space checks the box.  Enter continues when it is checked."
HINT_METHOD = "Press 1, 2, or 3 to choose. L: storage limits. Enter continues."
HINT_CONFIRM = "Type exactly what we ask for, then Enter."
HINT_LAST_CHANCE = "Esc goes back.  Enter erases after the countdown."
HINT_BLOCKED = "Enter shuts down.  Esc goes back."
HINT_DONE = "Save the report first if you need it. Enter shuts down."
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
    serial = disk.serial or NO_CODE
    return (
        f"This will erase {disk.display_name}, {disk.size_phrase}, {serial}. "
        "You cannot get the files back."
    )


def pick_subtitle() -> str:
    return "Click the name and size that match this PC."
