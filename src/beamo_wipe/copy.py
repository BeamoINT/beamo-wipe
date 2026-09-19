# SPDX-License-Identifier: GPL-3.0-or-later
"""User-facing strings. 8th-grade English. No forbidden claims."""

from beamo_wipe import inventory as _inventory
from beamo_wipe import outcomes as _outcomes
from beamo_wipe import storage_limits as _limits

# Live re-exports of translated values owned by other modules. Refreshed
# by _apply_language so C.VIEWS etc. always match the active language.
VIEWS = _outcomes.VIEWS
STOP_WARNING = _outcomes.STOP_WARNING
EMPTY_STEPS = _inventory.EMPTY_STEPS
OVERWRITE_LIMITS = _limits.OVERWRITE_LIMITS
from beamo_wipe.models import (
    CONTENTS_DATA,
    CONTENTS_SYSTEM,
    CONTENTS_UNKNOWN,
    CONTENTS_WINDOWS,
    Disk,
    DiskKind,
)
from beamo_wipe.methods import METHODS

APP_NAME = "Beamo Wipe"

# Read-only wayfinding: these labels never act as navigation controls.
JOURNEY_LABELS = ("Start", "Owner", "Disk", "Confirm", "Method", "Review", "Erase", "Result")
SELECTED_DISK = "This disk"
SERIAL_LABEL = "Serial"
REVIEW_CHECK = "Check the disk and method before you erase."
SPLASH_ROADMAP = "Choose a disk  →  Confirm its identity  →  Review and erase"

# --- Screen titles (happy path talks like a person) ------------------------

TITLE_KEYBOARD = "Check your keyboard"
TITLE_WHAT = "Here's what happens"
TITLE_OWNER = "Is this your computer?"
TITLE_PICK = "Which disk should we erase?"
TITLE_CONFIRM = "Is this the right disk?"
TITLE_METHOD = "Choose an erase method"
TITLE_ADVANCED = "Advanced"
TITLE_LAST = "Review before erasing"
TITLE_WORKING = "Erasing now"
TITLE_DONE_OK = "Finished"
TITLE_DONE_FAIL = "The erase did not finish"
TITLE_BLOCKED = "Stop"
TITLE_EMPTY = "No disk to erase"

# Problem-specific blocked headings. TITLE_BLOCKED stays the fallback for
# errors no release has mapped yet; mapped errors always name the problem.
BLOCKED_HEADING_IDENTIFY = "We could not identify the Beamo USB"
BLOCKED_HEADING_BOOT_SELECTABLE = "The Beamo USB appeared as a disk to erase"
BLOCKED_HEADING_BOOT_ALIAS = "The Beamo USB appeared under two names"
BLOCKED_HEADING_STARTUP = "Startup was blocked"
BLOCKED_HEADING_REDISCOVER = "Could not check the disks again"

TITLE_REFRESH = "Check disks again?"

# --- Splash: they already booted. Do not lecture. --------------------------

SPLASH_TAGLINE = (
    "You already started from this USB. Next you will pick a disk to erase."
)

KEYBOARD_LEAD = (
    "Choose the layout that matches the keys you see. "
    "Then type a few characters to check."
)
KEYBOARD_LIMITS = (
    "Only US QWERTY, French AZERTY, and German QWERTZ. "
    "The change lasts until this USB restarts. "
    "It does not change firmware or BIOS keyboards."
)
KEYBOARD_CHECK_LABEL = "Type here to check. This is not a password and is not saved."
KEYBOARD_CHECK_HINT = "Try letters that differ on your keyboard, then a number."
KEYBOARD_UTILITY = "Keyboard layout"

WHAT_LEAD = "Nothing starts until you say so."

WHAT_BULLETS = (
    "Check that you have the copies you need. You will pick a disk. "
    "Everything on that disk will be erased. You cannot get the files back.",
    "If that disk holds an operating system, erasing it also removes "
    "Windows or Linux, applications, files, and recovery partitions on that disk.",
    "For 64-bit Intel/AMD Windows or Linux PCs that start from this USB. "
    "Not Apple Silicon Macs. Not Chromebooks.",
)

POWER_REMINDER = (
    "If this computer has a battery, plug it into wall power before you erase. "
    "Keep the lid open. "
    "A power cut stops the erase."
)

POWER_KEEP = "Laptop: keep wall power connected and keep the lid open."
POWER_EVENTS = (
    "This live USB asks Linux to ignore lid closure and a short power-button press, "
    "and disables sleep. Firmware or a held power button can still stop the erase. "
    "Use Stop erase to stop; wait for the result before shutting down. "
    "A power cut can leave the disk partly erased and lose unsaved reports. "
    "An interrupted erase does not resume automatically."
)

POWER_BLANKING = (
    "The screen may go dark. Press a key or move the mouse to bring it back. "
    "That is the display, not sleep."
)

PREPARE_WINDOWS = (
    "This selected disk shows Windows partitions. Erasing it also removes "
    "Windows, applications, files, and recovery partitions on this disk."
)
PREPARE_SYSTEM = (
    "This selected disk shows operating-system partitions. Erasing it also removes "
    "the operating system, applications, files, and recovery partitions on this disk."
)
PREPARE_DATA = (
    "This selected disk does not show operating-system partitions. "
    "Erasing it still removes every file on this disk."
)
PREPARE_UNKNOWN = (
    "Erasing this selected disk removes every file on it, including any "
    "operating system, applications, files, and recovery partitions on this disk."
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

# Startup stages. Plain customer language; stages describe work in progress
# and never claim a safety check has passed. The exclusion of the boot USB
# is verified by discovery itself, never by these lines.
STARTUP_TITLE = "Starting Beamo Wipe"
STARTUP_TITLE_HINT = "Getting ready."
STARTUP_STAGE_BOOT_USB = "Checking the boot USB"
STARTUP_STAGE_BOOT_USB_HINT = (
    "Learning which disk is this USB stick, so it is never offered for erasure."
)
STARTUP_STAGE_FINDING = "Finding disks"
STARTUP_STAGE_FINDING_HINT = "Listing the disks connected to this computer."
STARTUP_STILL_WORKING = (
    "Still working — this can take a minute on older machines."
)

OWNER_LEAD = "Check the box, then continue."

BOOT_USB_BANNER = "Beamo USB — protected, cannot be erased"
BOOT_DISC_BANNER = "Beamo boot disc — protected, cannot be erased"

# Severity words: the non-color channel. Every renderer labels warnings,
# errors, limits, protection, and saved copies with these exact words so
# the severities stay distinguishable in monochrome, in plain text, and
# to screen readers. The single localization source; never retype them.
SEVERITY_WARNING = "Warning"
SEVERITY_ERROR = "Error"
SEVERITY_LIMITS = "Limits"
SEVERITY_PROTECTED = "Protected"
SEVERITY_SAVED = "Saved"

IDENTIFY_ERROR = (
    "We cannot tell which disk is this USB. Unplug extra USB sticks and start again."
)

REDISCOVER_ERROR = "Could not check the disks again. Erase did not start."

SUPPORT_LEAD = "For help, visit {short} or scan the code with your phone."
SUPPORT_TEXT = "For help, visit {short}."
SUPPORT_CODE_LABEL = "Support code"
SUPPORT_SAVE_LABEL = "Save code"
SUPPORT_BUILD_LABEL = "Build"
SUPPORT_CODE_HINT = (
    "Read these exact values to support if a report cannot be saved."
)


def support_lead() -> str:
    """Support destination for screens showing the QR code."""
    from beamo_wipe.support_contact import SUPPORT_SHORT

    return SUPPORT_LEAD.format(short=SUPPORT_SHORT)


def support_text() -> str:
    """Support destination for text-only surfaces (offline fallback)."""
    from beamo_wipe.support_contact import SUPPORT_SHORT

    return SUPPORT_TEXT.format(short=SUPPORT_SHORT)


def support_identity_text(identity: object) -> str:
    """Owner-facing support code and build lines, plus a short hint."""
    from beamo_wipe.support_code import SupportIdentity

    if not isinstance(identity, SupportIdentity):
        return ""
    return identity.lines() + "\n" + SUPPORT_CODE_HINT


def _build_blocked_headings() -> dict[str, str]:
    # Local imports: safety and app both import this module.
    from beamo_wipe import safety
    from beamo_wipe.app import STARTUP_BLOCKED

    return {
        IDENTIFY_ERROR: BLOCKED_HEADING_IDENTIFY,
        safety.BOOT_APPEARED_SELECTABLE: BLOCKED_HEADING_BOOT_SELECTABLE,
        safety.BOOT_APPEARED_ALIAS: BLOCKED_HEADING_BOOT_ALIAS,
        STARTUP_BLOCKED: BLOCKED_HEADING_STARTUP,
        REDISCOVER_ERROR: BLOCKED_HEADING_REDISCOVER,
    }


# Built lazily: keys are the current-language messages, and app/safety may
# still be importing when this module loads. Rebuilt on language change.
BLOCKED_HEADINGS: dict[str, str] = {}


def blocked_heading_for(error: object) -> str:
    """Problem-specific blocked heading, or "" when the error is unmapped."""
    if not BLOCKED_HEADINGS:
        BLOCKED_HEADINGS.update(_build_blocked_headings())
    if not error:
        # Callers render IDENTIFY_ERROR for empty errors; match that body.
        return BLOCKED_HEADING_IDENTIFY
    if not isinstance(error, str):
        return ""
    return BLOCKED_HEADINGS.get(error, "")


def blocked_title(error: object, *, recovered: bool = False) -> str:
    """Blocked-screen heading shared by every renderer."""
    if recovered:
        return SESSION_RECOVERY_TITLE
    return blocked_heading_for(error) or TITLE_BLOCKED

EMPTY_DISKS = _inventory.EMPTY_STEPS

SSD_FOOTER_SUFFIX = " Not a formal certificate."

SSD_FOOTER = _limits.OVERWRITE_LIMITS + SSD_FOOTER_SUFFIX

WORKING_PULSE = (
    "Leave the USB in. Keep wall power connected if this computer has a battery. "
    "Keep the lid open. "
    "Do not turn the PC off."
)

DONE_OK = _outcomes.VIEWS["verified"].message

DONE_FAIL = _outcomes.VIEWS["engine_failed"].announcement

NOT_LIVE_ERROR = (
    "Beamo Wipe only erases disks after you start the computer from this USB. "
    "It will not erase a disk from Windows or an installed Linux system. "
    "Run ./preview to see the screens on this computer, or start from the USB."
)

DONE_OK_PREVIEW = "Preview finished. Nothing on this computer was erased."
DONE_FAIL_PREVIEW = (
    "Preview of a failed erase. Nothing on this computer was erased."
)

SAME_SIZE_HINT = (
    "Two disks are the same size. Compare their serial or hardware ID before choosing."
)

RECOMMENDED_TAG = "Recommended"

CONFIRM_LEAD = "Type what we ask for, then continue."

CONFIRM_MATCH_WAIT = "Type it exactly, then you can continue."
CONFIRM_MATCH_OK = "That matches. You can continue."

COUNTDOWN_CAPTION = "seconds until Erase is available."
COUNTDOWN_READY = "Nothing has started. Choose Erase now to erase this disk."

METHOD_LEAD = "Pick how thoroughly to overwrite the disk."

LAST_LEAD = (
    "Check the selected disk and method. The countdown never starts erasure."
)
AUTHORIZATION_STALE = "The disk or method changed. Confirm again."

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
REPORT_HELP_NEED = (
    "What you need\n"
    "Saving a report is optional. You need a separate removable FAT32 USB device, "
    "with one writable, unmounted volume. It must be different from the Beamo boot USB and "
    "the disk you erase. exFAT, NTFS, FAT12 and FAT16 are not supported. "
    "Beamo Wipe does not format or repair report media."
)
REPORT_HELP_INSERT = (
    "When to insert the report USB\n"
    "Keep the report USB unplugged while choosing the erase target, confirming, "
    "and erasing. Only after the erase has stopped and the result screen offers "
    "Save report to USB, insert exactly one report USB, then choose Save report to USB. "
    "Leave the Beamo boot USB and selected erase disk connected."
)
REPORT_HELP_PLUGGED = (
    "If the report USB is already plugged in\n"
    "If you already inserted the report USB before erasing, remove only that "
    "report USB. Leave the boot USB and erase disk connected. Choose Check disks "
    "again, then choose and confirm the erase target again. Do not guess which "
    "disk to unplug or erase."
)
REPORT_HELP_CONTAINS = (
    "What the report contains\n"
    "{volatile} This checkbox remembers only your preference for this "
    "session. It does not choose media or save a report. If you request a report "
    "and no verified export has completed, Shut down asks before discarding it. "
    "A report is available only if the operation produced eligible evidence. "
    "The original report (result.json and RESULT.txt) includes disk identifiers. "
    "A sharing copy (SHARE.json and SHARE.txt) omits serials, hardware IDs, "
    "device paths, and engine logs. Do not use the sharing copy where full "
    "identity evidence is required. To share, copy only SHARE.json and SHARE.txt."
)
REPORT_HELP_REMOVE = (
    "Removing the report USB\n"
    "Wait for the saved and safe-to-remove message before removing the report USB. "
    "If saving fails, follow the displayed error and retry while this session is "
    "still running. Never remove report media while saving."
)
REPORT_HELP_START = (
    "If the wipe cannot start\n"
    "If the wipe cannot start, Diagnostic report has a separate flow: keep the "
    "report USB unplugged for Prepare and insert it only when prompted. "
    "Diagnostics are not erase evidence and do not establish that an erase ran."
)
REPORT_HELP_STAGES = (
    "Saving in stages\n"
    "1. Insert the report USB, only when the result screen asks. "
    "2. Check the USB: exactly one new FAT32 USB is accepted. "
    "3. Save the report to that USB. "
    "4. Verify the copy by reading it back. "
    "5. Safe removal: only the saved message makes the report USB safe to remove. "
    "Never remove report media while saving."
)
REPORT_HELP_SECTIONS = (
    REPORT_HELP_NEED,
    REPORT_HELP_INSERT,
    REPORT_HELP_PLUGGED,
    REPORT_HELP_CONTAINS.format(volatile=REPORT_VOLATILE),
    REPORT_HELP_REMOVE,
    REPORT_HELP_START,
    REPORT_HELP_STAGES,
)
REPORT_HELP_TEXT = "\n\n".join(REPORT_HELP_SECTIONS)
REPORT_SHARE_REDACTED = (
    "Also save a labeled sharing copy without serials, hardware IDs, device paths, "
    "or engine logs. It is not identity evidence. The original report is kept."
)

REPORT_INSERT = (
    "No erase is running. Leave the boot USB and selected disk connected. "
    "Insert one separate FAT32 USB, then choose Save report to USB. "
    "The original report includes disk identifiers. A sharing copy, if saved, is not identity evidence."
)
REPORT_MEDIA_WHAT = (
    "Want a report afterwards? You will need a separate FAT32 USB stick with "
    "one volume (any size). Keep it unplugged until the result screen asks "
    "for it. A USB that is already plugged in cannot be used for the report. "
    "Open Need a report? for the full requirements."
)
REPORT_MEDIA_WANTED = (
    "Report requested: keep the report USB unplugged until the result screen "
    "asks for it. Extra plugged-in USBs can confuse the disk list. If the "
    "report USB is already plugged in, unplug only that USB, then choose "
    "Check disks again."
)
ADVANCED_LOG_LEAD = (
    "Keep the separate FAT32 report USB unplugged until the erase has stopped "
    "and Save report to USB is offered. Then insert it before choosing Save. "
    "Leave the boot USB and selected disk connected. "
)
ADVANCED_LOG_TAIL = " Open Need a report? for requirements and safe removal."
ADVANCED_LOG_NOTE = ADVANCED_LOG_LEAD + REPORT_VOLATILE + ADVANCED_LOG_TAIL


POST_ERASE_BOOT = (
    "If this was the disk your computer starts from, the computer may not "
    "start normally now. To use that computer again, you may need to install "
    "an operating system first."
)
REPORT_STATUS_TITLE = "Report status"
REPORT_STATUS_NOTICE = "Saving or checking a report does not change the erase result."
REPORT_PREVIEW = "Preview only. No report was saved."


EXPORT_STAGE_INSERT = "Insert the report USB"
EXPORT_STAGE_CHECK = "Check the USB"
EXPORT_STAGE_SAVE = "Save the report"
EXPORT_STAGE_VERIFY = "Verify the copy"
EXPORT_STAGE_REMOVE = "Safe removal"
EXPORT_STAGES = (
    EXPORT_STAGE_INSERT,
    EXPORT_STAGE_CHECK,
    EXPORT_STAGE_SAVE,
    EXPORT_STAGE_VERIFY,
    EXPORT_STAGE_REMOVE,
)
EXPORT_GUIDE_WORKING = (
    "This can take a couple of minutes on a slow USB stick. "
    "Do not remove any USB until the result appears."
)
EXPORT_GUIDE_RETRY = (
    "If the report USB is still plugged in, choose Save report to USB again. "
    "Otherwise insert one first, then try again. "
    "If it fails again, use a different USB stick."
)


def export_stage_lines(status: str) -> str:
    """Numbered export stages with done/now marks. Never guess the middle.

    Check, save and verify run inside one unobservable export call, so
    while saving all three read as current together.
    """
    from beamo_wipe import progress as _progress

    if status == "saved":
        marks = (_progress.STAGE_DONE_MARK,) * 4 + (_progress.STAGE_NOW_MARK,)
    elif status == "saving":
        marks = (
            _progress.STAGE_DONE_MARK,
            _progress.STAGE_NOW_MARK,
            _progress.STAGE_NOW_MARK,
            _progress.STAGE_NOW_MARK,
            "",
        )
    elif status == "idle":
        marks = (_progress.STAGE_NOW_MARK,) + ("",) * 4
    else:
        marks = ("",) * 5
    return "\n".join(
        f"{index}. {stage}{mark}"
        for index, (stage, mark) in enumerate(zip(EXPORT_STAGES, marks), 1)
    )


def report_aftercare(*, can_save: bool, status: str, message: str) -> str:
    """Stages plus one current-step line. No insertion prompt unless the
    existing evidence gate allows saving. Errors stay stage-free so a
    failed attempt can never read as progress."""
    if status == "saved":
        return export_stage_lines(status) + "\n" + message
    if status == "saving":
        return (
            export_stage_lines(status)
            + "\n"
            + message
            + " "
            + EXPORT_GUIDE_WORKING
            + " "
            + REPORT_VOLATILE
        )
    if status == "error":
        from beamo_wipe.support_export import next_step_for, next_step_needs_support

        step = next_step_for(message)
        detail = message + (" " + step if step else "")
        if next_step_needs_support(message):
            detail += " " + support_text()
        return detail + " " + EXPORT_GUIDE_RETRY + " " + REPORT_VOLATILE
    detail = message or (REPORT_INSERT if can_save else REPORT_EXPORT_UNAVAILABLE)
    if message or not can_save:
        return detail + " " + REPORT_VOLATILE
    return export_stage_lines(status) + "\n" + detail + " " + REPORT_VOLATILE


REPORT_EXPORT_UNAVAILABLE = "Report export is unavailable."

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
BTN_REFRESH = "Check disks again"
BTN_REFRESH_UTILITY = "Check disks again (F5)"

PREVIEW_BANNER = "PREVIEW on this computer — fake disks — nothing is erased"

HINT_KEYBOARD = "1, 2, or 3 chooses a layout. Type in the check box. Enter continues."
HINT_DEFAULT = "Enter continues.  Esc goes back."
HINT_PICK = "Click a disk, or use Up/Down.  Enter continues.  Esc goes back."
HINT_OWNER = "Space checks the box.  Enter continues when it is checked."
HINT_METHOD = "Press 1, 2, or 3 to choose. Enter continues."
HINT_CONFIRM = "Type exactly what we ask for, then Enter."
HINT_LAST_CHANCE = "Esc goes back.  Enter erases after the countdown."
HINT_LAST_CHANCE_TK = "Esc goes back.  Tab to Erase, then Enter after the countdown."
HINT_BLOCKED = "Enter requests shutdown. Esc goes back."
HINT_REFRESH = "Esc keeps your answers. Enter checks disks again."
REFRESH_LEAD = (
    "This clears the selected disk, the ownership acknowledgement, the typed "
    "confirmation, the erase method, and the countdown. Preparation starts "
    "again from the beginning."
)
REFRESH_UTILITY_NOTE = "Check disks again (clears preparation)"
HINT_DONE = "Enter requests shutdown."
SHUTDOWN_TITLE = "Shut down without saving?"
SHUTDOWN_LOSS = (
    "You asked to save a report, but no verified export of the current report "
    "has been confirmed. Shutting down will lose any unsaved report held in memory. "
    "It cannot be recovered after shutdown or power loss."
)
SHUTDOWN_KEEP = "Keep session open"
SHUTDOWN_DISCARD = "Shut down without saving"
SHUTDOWN_HINT = "Nothing is saved automatically."
MEDIA_STEPS_TITLE = "Which USB can be removed, and when"
MEDIA_STEP_REPORT = (
    "Report first: choose Keep session open, save the report, and wait for "
    "the saved message. Only then may the report USB be removed. Shutting "
    "down without saving loses the unsaved report."
)
MEDIA_STEP_STAY = (
    "Leave the Beamo USB and the erased disk plugged in while this session runs."
)
MEDIA_STEP_BEAMO_OFF = (
    "The Beamo USB is safe to remove only after the computer is fully off. "
    "Removing it earlier ends this session immediately."
)
MEDIA_STEP_RESTART = (
    "If you restart instead of shutting down, leave the Beamo USB plugged in "
    "to come back here. Anything unsaved is still lost."
)
MEDIA_STEP_UNSURE = (
    "If more than one USB is plugged in, or anything was unplugged and "
    "plugged back in, do not guess which is which. Shut down first, then "
    "sort the USB sticks while the computer is off."
)
MEDIA_STEP_ANOTHER = (
    "Leave the Beamo USB plugged in: the next erase runs from it. Do not "
    "remove any USB while preparing or erasing."
)


def media_steps(*, stay_in_session: bool = False) -> str:
    """Ordered removal steps. Safe order: report, stay, Beamo, restart, unsure."""
    steps = [MEDIA_STEP_REPORT, MEDIA_STEP_STAY]
    steps.append(MEDIA_STEP_ANOTHER if stay_in_session else MEDIA_STEP_BEAMO_OFF)
    steps.extend((MEDIA_STEP_RESTART, MEDIA_STEP_UNSURE))
    return "\n".join(f"{index}. {step}" for index, step in enumerate(steps, 1))


HINT_WORKING = "Leave this USB in until the result appears."
HINT_SPLASH = "Press any key to continue."

NO_CODE = "Serial not reported"


def kind_label(kind: DiskKind) -> str:
    """Happy-path chip: name people know. NVMe is a kind of SSD."""
    if kind == DiskKind.HDD:
        return KIND_HDD
    if kind in (DiskKind.SSD, DiskKind.NVME):
        return "SSD"
    return ""


KIND_HDD = "Hard disk"
CONFIRM_TYPE_SIZE = "Type these numbers so we know it is the right disk: {token}"
CONFIRM_TYPE_FOUR = "Type these 4 characters so we know it is the right disk: {token}"
CONFIRM_TYPE_CHARS = "Type these characters so we know it is the right disk: {token}"
CONFIRM_WARNING_TEXT = "Every file on {title}, {size}, will be erased. You cannot get them back. {prep}"
ERASE_NOW_TEXT = "This will erase {title}, {capacity}, {id}. You cannot get the files back."
PICK_SUBTITLE = "Match the name, size and serial or hardware ID. Choose only the disk you intend to erase."


def confirm_type_size(token: str) -> str:
    return CONFIRM_TYPE_SIZE.format(token=token)


def confirm_type_four(token: str) -> str:
    return CONFIRM_TYPE_FOUR.format(token=token)


def confirm_type_chars(token: str) -> str:
    return CONFIRM_TYPE_CHARS.format(token=token)


def prepare_selected(disk: Disk) -> str:
    """Consequence of erasing this disk, from partition evidence only."""
    contents = getattr(disk, "contents", CONTENTS_UNKNOWN)
    if contents == CONTENTS_WINDOWS:
        return PREPARE_WINDOWS
    if contents == CONTENTS_SYSTEM:
        return PREPARE_SYSTEM
    if contents == CONTENTS_DATA:
        return PREPARE_DATA
    return PREPARE_UNKNOWN


def confirm_warning(disk: Disk) -> str:
    from beamo_wipe.identity import display_title

    return CONFIRM_WARNING_TEXT.format(
        title=display_title(disk), size=disk.size_phrase, prep=prepare_selected(disk)
    )


def erase_now_label(disk: Disk, peers=()) -> str:
    from beamo_wipe.identity import present_disk

    view = present_disk(disk, peers)
    return ERASE_NOW_TEXT.format(title=view.title, capacity=view.capacity, id=view.id_value)


def pick_subtitle() -> str:
    return PICK_SUBTITLE

DISK_HELP_BUTTON = "I'm not sure which disk"
DISK_HELP_TITLE = "Let's identify the disk first"
DISK_HELP_STOP = "Stop and shut down"
DISK_HELP_TEXT = """You do not need to choose now. No disk is selected while you read this help.

The disk you want to erase may be inside this computer, an external disk, or a disk from another computer. Do not choose a disk just because it is listed here.

Compare the name or model, capacity, and serial or hardware ID with a trusted label or record for the disk you intend to erase. Use Show more in the disk list for technical details where available.

If disks look alike or have the same capacity, compare their serial or hardware ID. Size alone is not enough. If identity is missing, duplicated, or does not match your record, do not guess. Ask someone you trust to help identify the disk.

Technical detail: names such as /dev/sda can change between starts. A USB connection can be an external target or the Beamo boot USB; the connection type alone does not identify a disk. The Beamo boot USB remains protected.

Still unsure? Stop and shut down before checking labels or changing connections. Wait until the computer is fully off. Keep the Beamo boot USB for restarting. Do not disconnect hardware while this session is running.

Back returns to the disk list with no disk selected. Continue only when you can identify the intended disk with confidence. You will still need to select it, type its confirmation, and wait through the final safety countdown."""

STOP_TITLE = "Stop this erase?"
STOP_ASK = "Stop erase"
STOP_CONFIRM = "Yes, stop erasing"
STOP_KEEP = "Keep erasing"
STOP_LEAD_SUFFIX = " Files may still remain on the disk. The erase continues until you confirm."
STOP_LEAD = _outcomes.STOP_WARNING + STOP_LEAD_SUFFIX
STOPPING_TEXT = "The disk may still be erasing. Keep the disk and Beamo USB connected while we confirm it has stopped."

BTN_ERASE_ANOTHER = "Erase another disk"
ANOTHER_TITLE = "Continue without saving this report?"
ANOTHER_LOSS = (
    "This report has not been saved to a report USB. Starting a new session "
    "closes this result and its report controls. Keep this session open to save "
    "the report, or continue without saving. You will need to choose a disk "
    "and complete every confirmation again. Keep the Beamo USB connected."
)
ANOTHER_DISCARD = "Continue without saving"
ANOTHER_HINT = "Remove the report USB first. Keep the Beamo USB connected."

# Sound check (screen-reader path only). Plain customer language; the
# technical sink name travels as each choice's screen-reader description.
SOUND_CHECK_BUTTON = "Sound check"
SOUND_CHECK_TITLE = "Sound check"
SOUND_PLAY_TEST = "Play speech test"
SOUND_LOUDER = "Louder"
SOUND_QUIETER = "Quieter"
SOUND_MUTE = "Mute"
SOUND_UNMUTE = "Unmute"
SOUND_CLOSE = "Close"
SOUND_TEST_PHRASE = (
    "This is the Beamo Wipe sound check. If you can hear this, your sound is working."
)
SOUND_TEST_PLAYED = "The test played. If you heard it, sound reaches this output."
SOUND_TEST_FAILED = (
    "The speech test did not play. Follow the recovery steps below and try again."
)
SOUND_ACTION_FAILED = "That change did not work. Try again."
SOUND_DIALOG_LEAD = "Choose where sound should play, then play the speech test."
SOUND_SELECTED = "selected. Play the speech test to check it."
SOUND_VOLUME = "Volume"
SOUND_MUTED_STATE = "muted"
SOUND_VOLUME_UNKNOWN = "Volume unknown"
SOUND_VOLUME_LOW = "The volume is low. Use Louder and test again."
SOUND_NO_OUTPUT = (
    "No sound output was found. The speech test cannot play. "
    "Follow the recovery steps below."
)
SOUND_OFF_LIVE = (
    "Sound check is available on the live USB. This preview cannot reach sound devices."
)
SOUND_ORCA_MISSING = (
    "The screen reader (Orca) is not running. The check below still works, "
    "but nothing will be spoken until Orca returns."
)
SOUND_RECOVERY = (
    "If you hear nothing: check that speakers or headphones are plugged in, "
    "then choose each output in turn and play the speech test. Make sure sound "
    "is not muted and the volume is up. Unplug extra USB sound devices and try "
    "again. If sound comes from the wrong place, choose a different output. "
    "If nothing works, shut down, check the connections, and start from the USB "
    "again. Ask someone you trust for help if you need it."
)
SOUND_TOGGLE_OFF = "Sounds: off"
SOUND_TOGGLE_ON = "Sounds: on"
SOUND_HEAR = "Hear sounds"
SOUND_HEAR_AGAIN = "Hear again"
SOUND_PLAYING_FINISHED = "Playing the finished sound."
SOUND_PLAYING_ATTENTION = "Playing the attention sound."
SOUND_PLAY_FAILED = (
    "That sound did not play. Check the sound output and try again."
)
SOUND_MUTED_SKIP = "Sound is muted, so nothing played."
SOUND_NO_OUTPUT_PLAY = "No sound output was found, so nothing played."
SOUND_OUTCOME_OFF_LIVE = (
    "Outcome sounds play on the live USB. This preview stays silent."
)

# Console-only chrome (CON_): terse key hints for the 80-column fallback.
# Key names stay English everywhere: keyboards print them. Typed words
# (ERASE, STOP, CHECK DISKS AGAIN, ...) stay English literals at the call
# sites and never enter these templates.
CON_INPUT_PREFIX = "> "
CON_DIAGNOSTIC = "D: Diagnostic report (not erase evidence)"
CON_REPORT_HELP = "R: Need a report? (optional)"
CON_REFRESH = "F5: {note}"
CON_KEYBOARD = "K: Keyboard layout"
CON_READ_ONLY = "Read only. Up/Down, PgUp/PgDn: read. Esc: back."
CON_PRESS_ANY_KEY = "Press any key."
CON_KEYBOARD_FOOTER = "1/2/3: layout. F2: language. Type to check. Enter continues."
CON_WHAT_FOOTER = "Enter: I understand    S: shut down"
CON_READ_MORE = "Up/Down: read more"
CON_OWNER_FOOTER = "Space to check. Enter continues only when checked. Esc: back"
CON_PICK_NAV = "Up/Down then Enter. PgUp/PgDn page. Esc back."
CON_DISK_HELP = "U: {label}"
CON_COMPARE = "Compare disks (C): read only."
CON_BOOT_IDENTITY = "{line} (B: identity)"
CON_OTHER_DEVICES = "Other detected devices (O): read reasons; not selectable."
CON_SHUTDOWN_BACK = "Enter: shut down    Esc: back"
CON_CONFIRM_FOOTER = "Up/Down: read more    F5: {note}"
CON_METHOD_FOOTER = "L: limits. A: Advanced. 1/2/3: choose. Enter: continue."
CON_DISK_HELP_STOP = "Arrows/Pg: read. Esc: back. S: {label}"
CON_READ_BACK = "Up/Down, PgUp/PgDn: read. Esc: back."
CON_REPORT_HELP_FOOTER = (
    "Arrows/Pg: read. Space: report preference. S: sharing copy. Esc: back."
)
CON_LAST_WAIT = "Wait {seconds}s"
CON_LAST_ERASE = "Enter to erase."
CON_BACK_READ_MORE = "Esc: back    Up/Down: read more"
CON_WORKING_STOP = "K / Esc / Enter: keep erasing. S: confirm stop."
CON_WORKING_IDLE = "Esc: stop erase (cancel)"
CON_CHECKING = "Please wait. Controls are unavailable during this check."
CON_STOPPING = "The disk may still be erasing. Keep this USB connected."
CON_REFRESHING = "Please wait. Previous selections have been cleared."
CON_REFRESH_ENTER = "Enter: check disks again"
CON_REFRESH_ESC = "Esc: keep your answers"
CON_SHUTDOWN_KEEP = "Enter/Esc: keep session open"
CON_SHUTDOWN_DISCARD = "D: {action} (type confirmation)"
CON_DIAG_SAVE = "save diagnostic report"
CON_DIAG_PREPARE = "prepare baseline"
CON_DIAG_LINE = "R: {action}    Esc: back    S: shut down"
CON_DONE_PREVIEW = "Enter: run again    C: close"
CON_DONE_SAVE = "R: save report to one FAT32 USB    Enter: shut down"
CON_DONE_RETRY = "E: retry evidence save    Enter: shut down"
CON_DONE_SHUTDOWN = "Enter: shut down"
CON_DONE_READ = "Up/Down, PgUp/PgDn: read aftercare."
CON_DONE_ANOTHER = "{action}    A: erase another disk"
CON_BACK = "Esc: back"
CON_REFRESH_HINT_CONFIRM = (
    "Type CHECK DISKS AGAIN to continue. Type BACK to keep your answers."
)
CON_REFRESH_HINT = "Type CHECK DISKS AGAIN to refresh. This clears preparation."
CON_DIAGNOSTIC_HINT = "Type DIAGNOSTIC for a diagnostic report (not erase evidence)."
CON_REPORT_HINT = "Type REPORT for Need a report? (optional)."
CON_INPUT_UNAVAILABLE = "Console input unavailable. Shutdown was not authorized."
CON_REFRESH_PROMPT = "Type CHECK DISKS AGAIN to continue, or BACK to keep your answers: "
CON_SHUTDOWN_TYPE = "Type {word} to discard; Enter keeps session open: "
CON_DIAG_TYPE = "Type {action}, BACK, or SHUTDOWN: "
CON_PRESS_ENTER = "Press Enter… "
CON_PRESS_ENTER_CONTINUE = "Press Enter to continue… "
CON_OWNER_PROMPT = "Type YES if that is true: "
CON_PRESS_ENTER_SHUTDOWN = "Press Enter to shut down… "
CON_ELIGIBLE_DISKS = "Eligible disks"
CON_PICK_PROMPT = "Number of disk to erase, or U for help: "
CON_DISK_HELP_PROMPT = "BACK: disk list. STOP: {label}: "
CON_METHOD_PROMPT = "Choice [1], L for storage limits, A for Advanced: "
BUSY_CHECKING_TITLE = "Checking disk"
BUSY_STOPPING_TITLE = "Stopping erase"
BUSY_REFRESHING_TITLE = "Checking disks again"
BUSY_CHECKING_MESSAGE = (
    "Confirming disk identity and boot USB exclusions. "
    "Please wait; controls are unavailable during this check."
)
BUSY_REFRESHING_MESSAGE = "Previous selections and confirmations have been cleared."
CON_COUNTDOWN = "Wait {seconds}…"
CON_ERASE_PROMPT = "Type ERASE to start: "
CON_STOP_CONFIRM = "Type STOP then Enter to confirm; KEEP then Enter to keep erasing."
CON_STOP_REVIEW = "Type CANCEL then Enter to review stopping."
CON_SOUND_OFF = "O: Sounds off"
CON_SOUND_ON = "O: Sounds on"
CON_SOUND_HEAR = "H: Hear sounds"
CON_SOUND_HEAR_AGAIN = "H: Hear again"
CON_SOUND_WORDS_WORKING = (
    "Type SOUNDS then Enter for on/off; HEAR then Enter to hear both sounds."
)
CON_SOUND_WORDS_DONE = (
    "Type SOUNDS then Enter for on/off; HEAR then Enter to hear it again."
)
CON_STOPPING_NOW = "Stopping erase. "
CON_RUN_AGAIN = "Enter to run again, or q to close… "
CON_DONE_RETRY_PROMPT = "Type RETRY to save evidence again, or SHUTDOWN: "
CON_DONE_SAVE_PROMPT = "Type SAVE to save the report, or SHUTDOWN: "
CON_DONE_SHUTDOWN_PROMPT = "Type SHUTDOWN: "
CON_DONE_ANOTHER_PROMPT = "Or type ANOTHER to erase another disk: "
CON_YES = "yes"
CON_NO = "no"
CON_REPORT_CHOICE = (
    "YES to want a report, SHARE for a redacted copy, NO to clear, BACK to return: "
)
CON_MORE_ENTER = "Enter for more… "
CON_PRESS_ENTER_BACK = "Press Enter to go back… "
CON_MORE_ABOVE = "More above. Use Up and Down."
CON_MORE_BELOW = "More below. Use Up and Down."
CON_MORE_DISKS_ABOVE = "More disks above. Use Up and Down."
CON_MORE_DISKS_BELOW = "More disks below. Use Up and Down."
CON_OWNER_CHECK = "{mark}  Space to check. Enter continues only when checked."
CON_DIAG_CONFIRM = "Type {action} for diagnostic report, then Enter (anything else cancels):"
CON_TYPE_OR_RETURN = "Type {word}; anything else returns:"
CON_SAVE_TYPE = "Type SAVE and press Enter: "
CON_PROTECTED_BOOT_MEDIA = "Protected boot media"

# Step strip, shared by the Tk header and the web gallery.
STEP_OF = "Step {n} of {total}"
STEP_PREFIX = "Step "
STEP_IDENTIFY = "Identify the disk"
STEP_OWNERSHIP = "Ownership"

# Labels shared by the Tk wizard, the screen-reader view, and the gallery.
SCREEN_READER_VIEW = "Screen-reader view (F8)"
DIAGNOSTIC_TITLE = "Diagnostic report"
PICK_COUNT_ONE = "{count} disk available"
PICK_COUNT_MANY = "{count} disks available"
PICK_SELECTED_ONE = "1 selected"
PICK_CHOOSE = "Choose one disk"
SESSION_RECOVERY_TITLE = "Session recovery"
NO_OUTCOME_RECORDED = "No operation outcome is recorded in this report."
SAVE_DIAGNOSTIC_REPORT = "Save diagnostic report"
BTN_PREPARE = "Prepare"
REPORT_MEDIA_NOTE = "Optional. Read before inserting report media."
HINT_READ_RETURN = "Enter or Esc returns. Nothing is saved here."
HINT_READ_KEYS = "Up/Down or Page Up/Page Down to read. Esc returns."
HINT_ESC_NO_SELECTION = "Esc returns with no disk selected."
HINT_ESC_METHOD = "Esc returns to method selection."
POWER_KEEP_CONNECTED = "Keep the disk and Beamo USB connected."
ERASE_PROGRESS_LABEL = "Erase progress"
RETRY_SAVE = "Retry evidence save"
NO_WIPE_YET = "(no wipe yet)"
ACCESSIBLE_TITLE = "Beamo Wipe — screen-reader view"
ACCESSIBLE_NOT_SELECTED = "not selected"
ACCESSIBLE_NO_TARGET = "No target selected"
ACCESSIBLE_REFRESHED = "Checking disks again. Previous confirmations have been cleared."
ACCESSIBLE_UNCONFIRMED = "The current screen could not be confirmed. Contact support."
STARTING_TITLE = "Beamo Wipe — starting"
STARTUP_STATE_DONE = "Done"
STARTUP_STATE_WAITING = "Waiting"
STARTUP_STATE_WORKING = "Working…"

CONFIRM_KEYBOARD_LINE = "Keyboard: {layout} · Language: {language}"

# Language selection. Option names are endonyms: identical in every language.
TITLE_LANGUAGE = "Choose your language"
LANGUAGE_LEAD = "Pick the language for every screen, report, and help page."
LANGUAGE_HINT = "1, 2, or 3 chooses a language. Enter continues."
LANGUAGE_NAME_EN = "English"
LANGUAGE_NAME_FR = "Français"
LANGUAGE_NAME_DE = "Deutsch"

# Web gallery scaffolding (preview only). Wizard content arrives via payload.
GALLERY_TITLE = "Beamo Wipe — screen preview"
GALLERY_NOTE = (
    "This is a <strong>preview</strong>. It does not erase disks. "
    "Click through like the USB wizard.\n"
    "The real window (same Tk screens as the live USB): <code>./preview</code>\n"
    "&nbsp;·&nbsp; <a href=\"{helper}\">Boot-menu helper</a>"
)
GALLERY_HAPPY = "Happy path"
GALLERY_EMPTY = "No other disks"
GALLERY_BLOCKED = "Cannot identify USB"
GALLERY_FAIL = "Failed wipe"
GALLERY_FAKE_POWER = "Fake power"
GALLERY_POWER_UNKNOWN = "Unknown"
GALLERY_POWER_AC = "Wall power connected"
GALLERY_POWER_BATTERY = "On battery"
GALLERY_POWER_LOW = "Low battery"
GALLERY_POWER_DESKTOP = "No battery reported"
GALLERY_ERASE_STEPS = "Erase steps"
GALLERY_PREVIEW_POWER = "Preview power (not a hardware reading). "
GALLERY_CLOSE_TAB = "Preview only. Close this tab when you are done."


def _apply_language() -> None:
    """Rebuild every derived string from the current language's constants."""
    global EMPTY_DISKS, SSD_FOOTER, DONE_OK, DONE_FAIL, METHOD_CARDS, STOP_LEAD
    global WHAT_MORE, REPORT_HELP_SECTIONS, REPORT_HELP_TEXT, ADVANCED_LOG_NOTE
    global VIEWS, STOP_WARNING, EMPTY_STEPS, OVERWRITE_LIMITS, EXPORT_STAGES
    global BLOCKED_HEADINGS
    BLOCKED_HEADINGS = _build_blocked_headings()
    VIEWS = _outcomes.VIEWS
    STOP_WARNING = _outcomes.STOP_WARNING
    EMPTY_STEPS = _inventory.EMPTY_STEPS
    OVERWRITE_LIMITS = _limits.OVERWRITE_LIMITS
    EMPTY_DISKS = EMPTY_STEPS
    SSD_FOOTER = _limits.OVERWRITE_LIMITS + SSD_FOOTER_SUFFIX
    DONE_OK = _outcomes.VIEWS["verified"].message
    DONE_FAIL = _outcomes.VIEWS["engine_failed"].announcement
    METHOD_CARDS = {
        method: {
            "title": spec.title,
            "blurb": spec.overwrite_description,
            "pace": spec.verification_description,
            "key": str(index),
        }
        for index, (method, spec) in enumerate(METHODS.items(), 1)
    }
    STOP_LEAD = _outcomes.STOP_WARNING + STOP_LEAD_SUFFIX
    WHAT_MORE = SECURE_BOOT_HINT + " " + ENGINE_LINE
    REPORT_HELP_SECTIONS = (
        REPORT_HELP_NEED,
        REPORT_HELP_INSERT,
        REPORT_HELP_PLUGGED,
        REPORT_HELP_CONTAINS.format(volatile=REPORT_VOLATILE),
        REPORT_HELP_REMOVE,
        REPORT_HELP_START,
        REPORT_HELP_STAGES,
    )
    REPORT_HELP_TEXT = "\n\n".join(REPORT_HELP_SECTIONS)
    ADVANCED_LOG_NOTE = ADVANCED_LOG_LEAD + REPORT_VOLATILE + ADVANCED_LOG_TAIL
    EXPORT_STAGES = (
        EXPORT_STAGE_INSERT,
        EXPORT_STAGE_CHECK,
        EXPORT_STAGE_SAVE,
        EXPORT_STAGE_VERIFY,
        EXPORT_STAGE_REMOVE,
    )

