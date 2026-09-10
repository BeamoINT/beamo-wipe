# SPDX-License-Identifier: GPL-3.0-or-later
"""Success location copy comes from a validated export receipt. Fake media only."""

from __future__ import annotations

import json
import subprocess
import textwrap
from dataclasses import replace

import pytest

from beamo_wipe import copy as C
from beamo_wipe.models import Screen
from beamo_wipe.support_export import (
    DeviceFingerprint,
    ExportReceipt,
    ExportVolume,
    GENERIC_DESTINATION,
    OWNER_DIAGNOSTIC_FILE,
    OWNER_WIPE_FILE,
    build_success_receipt,
    destination_label_for,
    export_to_new_usb,
    present_export_receipt,
    receipt_is_saved,
    report_folder_for,
)
from beamo_wipe.ui import console_wizard as console
from test_usb_report_workflow import (
    _done_wizard,
    _discovery,
    _payload,
    _success_receipt,
    _terminal_evidence,
    _worker_success_stdout,
)


def _volume(model: str = "Report USB", size: int = 32_000_000) -> ExportVolume:
    parent = DeviceFingerprint("/dev/sdc", size, model, "REPORT-1", "report-wwn")
    return ExportVolume(parent, "/dev/sdc1", size, "vfat", "FAT32", "ABCD-1234")


def _receipt(**kwargs) -> ExportReceipt:
    session = kwargs.get("session_name", "report-0123456789abcdef01234567")
    return ExportReceipt(
        True,
        True,
        "saved_verified_unmounted",
        evidence_sha256=kwargs.get("evidence_sha256", "a" * 64),
        session_name=session,
        log_status=kwargs.get("log_status", "complete"),
        destination_label=kwargs.get("destination_label", "Report USB, 1 GB"),
        report_folder=kwargs.get("report_folder", report_folder_for(session)),
        share_copy=kwargs.get("share_copy", False),
        owner_file=kwargs.get("owner_file", OWNER_WIPE_FILE),
    )


@pytest.mark.parametrize(
    ("model", "want"),
    [
        ("Kingston DataTraveler", "Kingston DataTraveler, 1 GB"),
        ("", f"{GENERIC_DESTINATION}, 1 GB"),
        ("/run/beamo-wipe-export/mount-abc", f"{GENERIC_DESTINATION}, 1 GB"),
        (r"C:\secret", f"{GENERIC_DESTINATION}, 1 GB"),
        ("../mnt/usb", f"{GENERIC_DESTINATION}, 1 GB"),
        ("/dev/sdc", f"{GENERIC_DESTINATION}, 1 GB"),
        (".hidden", f"{GENERIC_DESTINATION}, 1 GB"),
    ],
)
def test_destination_label_never_exposes_paths(model, want):
    assert destination_label_for(model, 32_000_000) == want


def test_long_destination_label_is_truncated():
    model = "W" * 200
    label = destination_label_for(model, 32_000_000)
    assert "(truncated)" in label
    assert "/" not in label
    assert len(label) < 96


@pytest.mark.parametrize("status", ["complete", "tail", "unavailable"])
def test_every_log_status_has_explicit_wording(status):
    text = present_export_receipt(_receipt(log_status=status))
    assert {
        "complete": "Engine log: complete.",
        "tail": "Engine log: only a final tail.",
        "unavailable": "Engine log: unavailable.",
    }[status] in text
    assert "Folder: BEAMO-WIPE-REPORTS/report-0123456789abcdef01234567" in text
    assert "RESULT.txt is the original report." in text
    assert "SHARE.txt" not in text


def test_share_copy_is_distinguished_from_the_original():
    text = present_export_receipt(_receipt(share_copy=True))
    assert "RESULT.txt is the original report." in text
    assert "SHARE.json is a privacy-reduced sharing copy" in text
    assert "not identity evidence" in text


def test_diagnostic_receipt_wording_is_not_erase_evidence():
    receipt = _receipt(owner_file=OWNER_DIAGNOSTIC_FILE, log_status="unavailable")
    text = present_export_receipt(receipt)
    assert text.startswith("Diagnostic report saved and verified on Report USB, 1 GB.")
    assert "This is not erase evidence." in text
    assert "diagnostic.json is the original report." in text
    assert "RESULT.txt" not in text
    assert "SHARE.txt" not in text


def test_wizard_success_message_comes_from_the_receipt(tmp_path):
    receipt = None

    def exporter(**kwargs):
        nonlocal receipt
        receipt = _success_receipt(
            **kwargs, log_status="tail", destination_label="SanDisk Ultra, 16 GB"
        )
        return receipt

    wizard = _done_wizard(exporter, tmp_path)
    wizard.report_share_redacted = False
    wizard.save_report_to_usb()
    assert wizard.report_status == "saved"
    assert wizard.report_message == present_export_receipt(receipt)
    assert "SanDisk Ultra, 16 GB" in wizard.report_message
    assert "Folder: BEAMO-WIPE-REPORTS/report-0123456789abcdef01234567" in wizard.report_message
    assert "Engine log: only a final tail." in wizard.report_message
    assert "RESULT.txt is the original report." in wizard.report_message
    aftercare = C.report_aftercare(
        can_save=False, status="saved", message=wizard.report_message
    )
    assert aftercare == wizard.report_message


def test_privacy_reduced_success_names_the_sharing_copy(tmp_path):
    def exporter(**kwargs):
        return _success_receipt(**kwargs, log_status="complete")

    wizard = _done_wizard(exporter, tmp_path)
    wizard.screen = Screen.REPORT_HELP
    wizard.set_report_share_redacted(True)
    wizard.screen = Screen.DONE
    wizard.save_report_to_usb()
    assert wizard.report_status == "saved"
    assert "SHARE.json is a privacy-reduced sharing copy" in wizard.report_message
    assert "not identity evidence" in wizard.report_message
    assert "RESULT.txt is the original report." in wizard.report_message
    assert "Engine log: complete." in wizard.report_message


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: replace(r, destination_label="/run/beamo-wipe-export/mount-aa"),
        lambda r: replace(r, destination_label=""),
        lambda r: replace(r, report_folder="/mnt/" + r.session_name),
        lambda r: replace(r, owner_file="nwipe.log"),
        lambda r: replace(r, share_copy=True, owner_file=OWNER_DIAGNOSTIC_FILE),
        lambda r: replace(r, log_status="unverified"),
        lambda r: ExportReceipt(True, True, "saved_verified_unmounted"),
    ],
)
def test_unsafe_or_partial_receipts_never_announce_success(tmp_path, mutation):
    def exporter(**kwargs):
        return mutation(_success_receipt(**kwargs))

    wizard = _done_wizard(exporter, tmp_path)
    wizard.save_report_to_usb()
    assert wizard.report_status == "error"
    assert "safe to remove" not in wizard.report_message.casefold()
    assert "Folder:" not in wizard.report_message
    assert "BEAMO-WIPE-REPORTS" not in wizard.report_message


@pytest.mark.parametrize(
    "message",
    [
        "The report USB was removed.",
        "Could not allocate a unique report directory.",
        "The exported report did not pass read-back verification.",
        "The report USB could not be remounted for verification.",
    ],
)
def test_failure_states_keep_the_error_and_do_not_claim_a_folder(tmp_path, message):
    def exporter(**_kwargs):
        from beamo_wipe.safety import SafetyError

        raise SafetyError(message)

    wizard = _done_wizard(exporter, tmp_path)
    wizard.save_report_to_usb()
    assert wizard.report_status == "error"
    assert wizard.report_message == message
    assert "safe to remove" not in wizard.report_message.casefold()
    assert "Folder:" not in wizard.report_message


def test_retry_after_failure_shows_receipt_location(tmp_path):
    attempts = iter((False, True))

    def exporter(**kwargs):
        if next(attempts):
            return _success_receipt(**kwargs, log_status="unavailable")
        from beamo_wipe.safety import SafetyError

        raise SafetyError("The report USB was removed.")

    wizard = _done_wizard(exporter, tmp_path)
    wizard.save_report_to_usb()
    assert wizard.report_status == "error"
    wizard.save_report_to_usb()
    assert wizard.report_status == "saved"
    assert "Engine log: unavailable." in wizard.report_message
    assert "Folder: BEAMO-WIPE-REPORTS/" in wizard.report_message


def test_controller_rejects_path_shaped_destination_labels(tmp_path, monkeypatch):
    evidence_path = _terminal_evidence(tmp_path)
    payload, disks = _payload()
    discovery = _discovery(disks)
    monkeypatch.setattr(
        "beamo_wipe.support_export._block_rdev",
        {"/dev/sdb": 201, "/dev/nvme0n1": 202, "/dev/sdc": 301, "/dev/sdc1": 302}.__getitem__,
    )

    def fake_run(command, **kwargs):
        request = json.loads(kwargs["input"])
        raw = json.loads(_worker_success_stdout(request))
        raw["destination_label"] = "/media/report"
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(raw), stderr="")

    from beamo_wipe.safety import SafetyError

    with pytest.raises(SafetyError, match="invalid"):
        export_to_new_usb(
            evidence_path=evidence_path,
            discovery=discovery,
            target_path="/dev/nvme0n1",
            scan=lambda: payload,
            run=fake_run,
        )


def test_build_success_receipt_matches_selected_volume():
    volume = _volume("Report USB")
    session = "report-" + "ab" * 12
    receipt = build_success_receipt(
        evidence_sha256="b" * 64,
        session_name=session,
        log_status="complete",
        volume=volume,
        privacy_reduced=True,
        diagnostic=False,
    )
    assert receipt_is_saved(
        receipt, expected_sha256="b" * 64, owner_file=OWNER_WIPE_FILE, share_copy=True
    )
    assert receipt.destination_label == "Report USB, 1 GB"
    assert receipt.report_folder == f"BEAMO-WIPE-REPORTS/{session}"
    text = present_export_receipt(receipt)
    assert "SHARE.txt" in text
    diagnostic = build_success_receipt(
        evidence_sha256="b" * 64,
        session_name=session,
        log_status="unavailable",
        volume=volume,
        privacy_reduced=True,
        diagnostic=True,
    )
    assert diagnostic.share_copy is False
    assert diagnostic.owner_file == OWNER_DIAGNOSTIC_FILE


def test_console_wraps_long_success_copy_at_80x24(tmp_path, monkeypatch):
    wizard = _done_wizard(
        lambda **kw: _success_receipt(
            **kw,
            destination_label=destination_label_for("W" * 200, 32_000_000),
            log_status="complete",
        ),
        tmp_path,
    )
    wizard.save_report_to_usb()
    assert wizard.report_status == "saved"

    class Terminal:
        def __init__(self):
            self.rows = {}

        def getmaxyx(self):
            return 24, 80

        def addstr(self, y, x, text, attr=0):
            assert 0 <= y < 24 and len(text) < 80
            self.rows[y] = text

        def getch(self):
            wizard.wants_shutdown = True
            return ord("q")

        def __getattr__(self, name):
            return lambda *a: None

    terminal = Terminal()
    monkeypatch.setattr(console.curses, "curs_set", lambda *a: None)
    monkeypatch.setattr(console.curses, "use_default_colors", lambda *a: None)
    console._loop(terminal, wizard)
    shown = " ".join(terminal.rows[y] for y in sorted(terminal.rows))
    assert "Folder:" in shown
    assert "RESULT.txt" in shown
    assert "Engine log:" in shown
    wrapped = textwrap.wrap(wizard.report_message.replace("\n", " "), 78)
    assert all(len(line) <= 78 for line in wrapped)


def test_recovered_session_still_uses_the_new_receipt(tmp_path):
    wizard = _done_wizard(_success_receipt, tmp_path)
    wizard._recovered = True
    wizard.report_status = "idle"
    wizard.save_report_to_usb()
    assert wizard.report_status == "saved"
    assert "Folder: BEAMO-WIPE-REPORTS/" in wizard.report_message
    assert "safe to remove" in wizard.report_message.casefold()


def test_plain_console_prints_receipt_lines(tmp_path, capsys, monkeypatch):
    wizard = _done_wizard(
        lambda **kw: _success_receipt(**kw, log_status="tail"),
        tmp_path,
    )
    wizard.screen = Screen.REPORT_HELP
    wizard.set_report_share_redacted(True)
    wizard.screen = Screen.DONE
    wizard.save_report_to_usb()
    monkeypatch.setattr("builtins.input", lambda _: "SHUTDOWN")
    console._plain_loop(wizard)
    out = capsys.readouterr().out
    assert "Folder: BEAMO-WIPE-REPORTS/" in out
    assert "Engine log: only a final tail." in out
    assert "SHARE.json is a privacy-reduced sharing copy" in out
