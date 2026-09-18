# SPDX-License-Identifier: GPL-3.0-or-later
"""#101: actionable report-media rejection. Fake devices only."""

from __future__ import annotations

import pytest

from beamo_wipe import copy as C
from beamo_wipe import support_export as E
from beamo_wipe.models import Screen
from beamo_wipe.ui import console_wizard as console
from test_console_parity import _draw
from test_usb_report_workflow import _done_wizard as _eligible_wizard

SELF_CONTAINED = {
    E.USB_NOT_SINGLE.format(detail=E.USB_NONE_FOUND),
    E.USB_NOT_SINGLE.format(detail=E.USB_MANY_FOUND),
    E.BASELINE_KEEP_CONNECTED,
    E.DISK_CHANGED_PREPARE,
    E.BASELINE_PREPARE_FIRST,
    E.CANNOT_VERIFY_BOOT,
    E.USB_CHANGED_DISCOVERY,
    E.EXPORT_TIMEOUT,
    E.HELPER_FAILED,
}

ALL_REFUSALS = (
    E.USB_META_INCOMPLETE,
    E.USB_META_MALFORMED,
    E.USB_SIZE_INVALID,
    E.USB_MOUNT_META_INCOMPLETE,
    E.USB_MOUNT_META_MALFORMED,
    E.USB_DEVICE_PATH_UNSUPPORTED,
    E.DISCOVERY_MALFORMED,
    E.DISCOVERY_DUPLICATES,
    E.BASELINE_KEEP_CONNECTED,
    E.NEW_NOT_REMOVABLE,
    E.USB_NOT_SINGLE.format(detail=E.USB_NONE_FOUND),
    E.USB_NOT_SINGLE.format(detail=E.USB_MANY_FOUND),
    E.USB_MUST_BE_WRITABLE,
    E.USB_LAYOUT_MALFORMED,
    E.USB_LAYOUT_AMBIGUOUS,
    E.USB_NEED_ONE_VOLUME,
    E.USB_LAYOUT_UNSUPPORTED,
    E.USB_PARTITION_ORPHAN,
    E.USB_VOLUME_PATH_UNSUPPORTED,
    E.USB_VOLUME_WRITABLE,
    E.USB_VOLUME_SMALL,
    E.USB_FAT32_ONLY,
    E.USB_FAT32_NOT_12_16,
    E.EVIDENCE_MALFORMED,
    E.EVIDENCE_SCHEMA,
    E.EVIDENCE_NOT_FINISHED,
    E.EVIDENCE_NO_IDENTITY,
    E.EVIDENCE_WRONG_DISK,
    E.EVIDENCE_PROVENANCE,
    E.EVIDENCE_LOG_META,
    E.USB_GONE,
    E.USB_NOT_BLOCK,
    E.PROTECTED_LAYOUT_BAD,
    E.PROTECTED_IDENTITY_UNVERIFIED,
    E.REPORT_CHANGED_BEFORE_EXPORT,
    E.BASELINE_PREPARE_FIRST,
    E.BOOT_IDENTITY_UNAVAILABLE,
    E.NO_BASELINE,
    E.BOOT_ABSENT_BASELINE,
    E.UNSTABLE_BASELINE,
    E.CANNOT_VERIFY_BOOT,
    E.DISK_CHANGED_PREPARE,
    E.USB_CHANGED_DISCOVERY,
    E.DISK_IDENTITY_CHANGED,
    E.USB_IS_PROTECTED,
    E.EXPORT_TIMEOUT,
    E.HELPER_NO_START,
    E.HELPER_FAILED,
    E.HELPER_BAD_RECEIPT,
    E.RECEIPT_INVALID,
    E.RECEIPT_FAILURE_INVALID,
    E.REPORT_FILENAME_INVALID,
    E.REPORT_UNSAFE_FILE,
    E.REPORT_TOO_BIG,
    E.DIAG_NO_RAW_LOGS,
    E.SESSION_NAME_INVALID,
    E.REPORT_DIR_ALLOC,
    E.RECEIPT_DIR_INVALID,
    E.REPORT_FILES_CHANGED,
    E.REPORT_READBACK_FAILED,
    E.MOUNT_UNVERIFIED,
    E.MOUNTPOINT_AMBIGUOUS,
    E.USB_NOT_MOUNTED,
    E.MOUNT_IDENTITY_MISMATCH,
    E.MOUNT_IDENTITY_UNCHECKED,
    E.MOUNT_SOURCE_CHANGED,
    E.MOUNT_MISSING_OPTIONS,
    E.REQUEST_SIZE_INVALID,
    E.REQUEST_MALFORMED,
    E.REQUEST_CHECKSUM,
    E.LOG_STATUS_MALFORMED,
    E.LOG_PAYLOAD_MALFORMED,
    E.USB_BLOCK_CHANGED,
    E.USB_PARTITION_INVALID,
    E.USB_PARTITION_UNVERIFIED,
    E.EXPORT_RUNNING,
    E.USB_MOUNT_FAILED,
    E.USB_SYNC_FAILED,
    E.USB_UNMOUNT_FAILED,
    E.USB_REMOUNT_FAILED,
    E.USB_VERIFIED_UNMOUNT_FAILED,
    E.USB_STILL_MOUNTED,
    E.USB_CHANGED_BEFORE_MOUNT,
    E.PROTECTED_CHANGED,
    E.USB_ALIASES_PROTECTED,
    E.USB_IDENTITY_CHANGED_OPEN,
)


def test_every_refusal_maps_to_a_step_or_is_self_contained():
    for detail in ALL_REFUSALS:
        step = E.next_step_for(detail)
        if detail in SELF_CONTAINED:
            assert step == "", detail
        else:
            assert step, detail


def test_steps_name_no_paths_and_promise_nothing():
    steps = {E.next_step_for(detail) for detail in ALL_REFUSALS}
    steps.discard("")
    assert len(steps) >= 5
    for step in steps:
        assert "/dev" not in step and "/run" not in step
        assert "{" not in step and "{detail}" not in step
        assert "safe to remove" not in step
        assert step != E.next_step_for("not a real detail")


def test_unknown_details_get_no_step():
    assert E.next_step_for("") == ""
    assert E.next_step_for("Report USB was removed.") == ""


def test_next_steps_follow_active_language():
    from beamo_wipe import lang

    try:
        lang.set_language("fr")
        step = E.next_step_for(E.USB_FAT32_ONLY)
        assert "autre clé USB" in step
        text = C.report_aftercare(
            can_save=False, status="error", message=E.USB_FAT32_ONLY
        )
        assert "autre clé USB" in text
    finally:
        lang.set_language("en")
    assert "different USB stick" in E.next_step_for(E.USB_FAT32_ONLY)


def test_filesystem_rejection_points_to_a_different_stick():
    assert "different USB stick" in E.next_step_for(E.USB_FAT32_ONLY)
    assert "different USB stick" in E.next_step_for(E.USB_FAT32_NOT_12_16)
    assert "different USB stick" in E.next_step_for(E.USB_NEED_ONE_VOLUME)


def test_mounted_media_rejection_points_to_replug():
    assert "plug it back in" in E.next_step_for(E.USB_MUST_BE_WRITABLE)
    assert "plug it back in" in E.next_step_for(E.USB_VOLUME_WRITABLE)
    assert "plug it back in" in E.next_step_for(E.USB_MOUNT_FAILED)


def test_identity_rejection_sorts_while_off():
    assert "while the computer is off" in E.next_step_for(E.USB_IS_PROTECTED)
    assert "while the computer is off" in E.next_step_for(E.USB_ALIASES_PROTECTED)
    assert "while the computer is off" in E.next_step_for(E.DISK_IDENTITY_CHANGED)


def test_stuck_mount_rejection_retries_then_shutdown():
    step = E.next_step_for(E.USB_VERIFIED_UNMOUNT_FAILED)
    assert "Try again" in step and "shut down before removing" in step
    assert "shut down before removing" in E.next_step_for(E.USB_STILL_MOUNTED)


def test_internal_failures_point_to_support():
    assert "contact support" in E.next_step_for(E.EVIDENCE_MALFORMED)
    assert "contact support" in E.next_step_for(E.REPORT_TOO_BIG)
    assert "contact support" in E.next_step_for(E.DIAG_NO_RAW_LOGS)


def test_aftercare_error_carries_problem_step_retry():
    text = C.report_aftercare(
        can_save=False, status="error", message=E.USB_FAT32_ONLY
    )
    assert text.startswith(E.USB_FAT32_ONLY)
    assert "different USB stick" in text
    assert "Save report to USB again" in text
    assert "If it fails again, use a different USB stick." in text
    assert C.REPORT_VOLATILE in text


def test_precedence_count_before_filesystem():
    from beamo_wipe.safety import SafetyError
    from test_usb_report_workflow import (
        _partition,
        _payload,
        _root,
    )

    another = _root(
        "/dev/sdd",
        size=64_000_000,
        tran="usb",
        model="Another",
        serial="REPORT-2",
        rm=1,
        hotplug=1,
        children=[_partition("/dev/sdd1", fstype="ntfs", fsver=None, uuid="EEEE-FFFF")],
    )
    payload, disks = _payload(another)
    with pytest.raises(SafetyError) as excinfo:
        E.select_export_volume(payload, E.baseline_fingerprints(disks))
    assert "More than one" in str(excinfo.value)
    assert E.next_step_for(str(excinfo.value)) == ""


def test_precedence_writability_before_filesystem():
    from beamo_wipe.safety import SafetyError
    from test_usb_report_workflow import _payload

    payload, disks = _payload()
    candidate = payload["blockdevices"][2]
    candidate["children"][0]["fstype"] = "ntfs"
    candidate["children"][0]["fsver"] = None
    candidate["children"][0]["mountpoints"] = ["/media/report"]
    candidate["children"][0]["mountpoint"] = "/media/report"
    with pytest.raises(SafetyError) as excinfo:
        E.select_export_volume(payload, E.baseline_fingerprints(disks))
    assert excinfo.value.args[0] == E.USB_MUST_BE_WRITABLE
    assert "plug it back in" in E.next_step_for(str(excinfo.value))


def test_retry_after_correction_succeeds():
    from beamo_wipe.safety import SafetyError
    from test_usb_report_workflow import _payload

    payload, disks = _payload()
    payload["blockdevices"][2]["children"][0]["fstype"] = "ntfs"
    payload["blockdevices"][2]["children"][0]["fsver"] = None
    baseline = E.baseline_fingerprints(disks)
    with pytest.raises(SafetyError, match="FAT32"):
        E.select_export_volume(payload, baseline)
    payload["blockdevices"][2]["children"][0]["fstype"] = "vfat"
    payload["blockdevices"][2]["children"][0]["fsver"] = "FAT32"
    volume = E.select_export_volume(payload, baseline)
    assert volume.fstype == "vfat"


def test_done_console_error_shows_step(monkeypatch, tmp_path):
    from beamo_wipe.safety import SafetyError

    def exporter(**kw):
        raise SafetyError(E.USB_FAT32_ONLY)

    wiz = _eligible_wizard(exporter, tmp_path)
    wiz.save_report_to_usb()
    assert wiz.report_view.status == "error"
    shown, _, _ = _draw(monkeypatch, wiz)
    assert "Other filesystems are not mounted" in shown
    assert "different USB stick" in shown


def test_done_plain_console_error_shows_step(monkeypatch, capsys, tmp_path):
    from beamo_wipe.safety import SafetyError

    def exporter(**kw):
        raise SafetyError(E.USB_VOLUME_WRITABLE)

    wiz = _eligible_wizard(exporter, tmp_path)
    wiz.save_report_to_usb()

    def fake_input(prompt=""):
        wiz.wants_shutdown = True
        return "NOPE"

    monkeypatch.setattr("builtins.input", fake_input)
    console._plain_loop(wiz)
    visible = capsys.readouterr().out
    assert "must be writable and unmounted" in visible
    assert "plug it back in" in visible


def test_diagnostic_step_property_and_render(monkeypatch):
    from beamo_wipe.demo import make_demo_wizard

    wiz = make_demo_wizard()
    wiz.screen = Screen.DIAGNOSTIC
    wiz.diagnostic_message = E.USB_FAT32_ONLY
    assert "different USB stick" in wiz.diagnostic_step
    shown, _, _ = _draw(monkeypatch, wiz)
    assert "different USB stick" in shown
    wiz.diagnostic_message = ""
    assert wiz.diagnostic_step == ""


def test_next_step_keys_translated_in_fr_and_de():
    from beamo_wipe.locales import de as de_locale
    from beamo_wipe.locales import fr as fr_locale

    for key in (
        "NEXT_REPLUG",
        "NEXT_DIFFERENT_STICK",
        "NEXT_TRY_SUPPORT",
        "NEXT_SUPPORT",
        "NEXT_SHUTDOWN_RETRY",
        "NEXT_SORT_WHILE_OFF",
        "NEXT_WAIT_OTHER",
    ):
        assert key in fr_locale.STRINGS["support_export"]
        assert key in de_locale.STRINGS["support_export"]
        assert "sûre à retirer" not in fr_locale.STRINGS["support_export"][key]
        assert "sûr à retirer" not in fr_locale.STRINGS["support_export"][key]
        assert "sicher entfernbar" not in de_locale.STRINGS["support_export"][key]


def test_retry_escalation_translated_in_fr_and_de():
    from beamo_wipe.locales import de as de_locale
    from beamo_wipe.locales import fr as fr_locale

    assert "autre clé USB" in fr_locale.STRINGS["copy"]["EXPORT_GUIDE_RETRY"]
    assert "anderen USB-Stick" in de_locale.STRINGS["copy"]["EXPORT_GUIDE_RETRY"]


@pytest.mark.parametrize("name", ["index.html", "fr.html", "de.html"])
def test_helper_lists_rejection_remedies(name):
    from beamo_wipe.gallery import project_root

    text = (project_root() / "helper" / name).read_text(encoding="utf-8")
    card = text.split('id="saving-report"', 1)[1].split("</div>", 1)[0]
    markers = {
        "index.html": ("different USB stick", "plug it back in", "while the computer is off"),
        "fr.html": ("autre clé USB", "rebranchez-la", "ordinateur est éteint"),
        "de.html": ("anderen USB-Stick", "wieder an", "Computer aus ist"),
    }[name]
    for marker in markers:
        assert marker in card
    code_markers = {
        "index.html": ("Support code", "Build"),
        "fr.html": ("Code d’assistance", "Version"),
        "de.html": ("Supportcode", "Build-Kennung"),
    }[name]
    for marker in code_markers:
        assert marker in card
