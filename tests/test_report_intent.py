# SPDX-License-Identifier: GPL-3.0-or-later
"""Report planning never authorizes disk I/O. All inventories and runners are fake."""

from dataclasses import replace

import pytest

from beamo_wipe import copy as C
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.discover import node_to_disk
from beamo_wipe.models import Screen
from beamo_wipe.safety import SafetyError
from beamo_wipe.support_export import baseline_fingerprints, select_export_volume
from beamo_wipe.ui import console_wizard as console
from test_refresh_disks import authorized
from test_usb_report_workflow import _payload, _done_wizard, _success_receipt


@pytest.mark.parametrize("screen", [Screen.WHAT, Screen.METHOD, Screen.ADVANCED])
@pytest.mark.parametrize("wanted", [True, False])
def test_optional_help_only_records_intent(screen, wanted):
    w = authorized()
    w.screen = screen
    before = (
        w.discovery,
        w.selected,
        w.owner_ok,
        w.confirm_input,
        w.method,
        w._erase_until,
    )
    assert not w.report_wanted
    w.open_report_help()
    assert w.screen == Screen.REPORT_HELP
    w.set_report_wanted(wanted)
    w.confirm_erase()
    assert not w.can_save_report and not w.runner.started
    w.back()
    assert w.screen == screen and w.report_wanted is wanted
    assert before == (
        w.discovery,
        w.selected,
        w.owner_ok,
        w.confirm_input,
        w.method,
        w._erase_until,
    )
    assert w._wipe_request is None and w.evidence is None


@pytest.mark.parametrize(
    "screen",
    [s for s in Screen if s not in {Screen.WHAT, Screen.METHOD, Screen.ADVANCED}],
)
def test_help_cannot_interrupt_or_advance_other_screens(screen):
    w = make_demo_wizard()
    w.screen = screen
    w.open_report_help()
    assert w.screen == screen
    if screen != Screen.REPORT_HELP:
        w.set_report_wanted(True)
        assert not w.report_wanted


@pytest.mark.parametrize("wanted", [True, False])
@pytest.mark.parametrize("changed", [False, True])
def test_intent_retained_on_refresh_but_all_confirmation_is_required(wanted, changed):
    w = authorized()
    w.screen = Screen.METHOD
    w.open_report_help()
    w.set_report_wanted(wanted)
    old = w.discovery
    target = old.selectable[0]
    fresh = (
        replace(
            old,
            disks=tuple(d for d in old.disks if d != target),
            selectable=tuple(d for d in old.selectable if d != target),
        )
        if changed
        else old
    )
    w._rediscover = lambda: fresh
    assert w.refresh_disks()
    assert w.report_wanted is wanted
    assert w.screen == Screen.WHAT and w._report_help_from is None
    assert (
        w.selected is None
        and not w.owner_ok
        and not w.confirm_input
        and w._erase_until is None
    )
    w.close_report_help()
    w.confirm_erase()
    assert not w.runner.started
    w.accept_what()
    w.continue_owner()
    assert w.screen == Screen.OWNER
    w.reset_for_preview()
    assert not w.report_wanted


@pytest.mark.parametrize("wanted", [True, False])
def test_report_intent_does_not_skip_final_rediscovery(wanted):
    w = authorized()
    w.screen = Screen.METHOD
    w.open_report_help()
    w.set_report_wanted(wanted)
    w.close_report_help()
    w.continue_method()
    w._erase_until = 0
    w.dry_run = False
    w.preview = False
    calls = []
    w._rediscover = lambda: calls.append(True) or replace(
        w.discovery, boot=None, boot_identified=False
    )
    w.confirm_erase()
    assert calls == [True]
    assert not w.runner.started and w.error


def test_early_report_media_must_be_removed_before_refreshed_final_inventory():
    payload, disks = _payload()
    boot_and_target = baseline_fingerprints(disks)
    early = baseline_fingerprints(
        [*disks, node_to_disk(payload["blockdevices"][-1], is_boot=False)]
    )
    with pytest.raises(SafetyError, match="No new report USB"):
        select_export_volume(payload, early)
    absent = {"blockdevices": payload["blockdevices"][:-1]}
    with pytest.raises(SafetyError, match="No new report USB"):
        select_export_volume(absent, boot_and_target)
    # A fresh baseline with report media absent accepts only its later insertion.
    assert select_export_volume(payload, boot_and_target).path == "/dev/sdc1"


@pytest.mark.parametrize("wanted", [True, False])
def test_evidence_eligibility_and_explicit_save_are_independent(tmp_path, wanted):
    calls = []
    w = _done_wizard(lambda **kw: calls.append(kw) or _success_receipt(**kw), tmp_path)
    w.report_wanted = wanted
    assert w.can_save_report and not calls
    w.save_report_to_usb()
    assert len(calls) == 1 and w.report_status == "saved"
    assert w.report_wanted is wanted


@pytest.mark.parametrize("wanted", [True, False])
def test_plain_console_report_choice_is_optional_rendered_and_paged(
    monkeypatch, capsys, wanted
):
    w = make_demo_wizard()
    w.skip_splash()
    answers = iter(
        ["REPORT", *([""] * len(C.REPORT_HELP_SECTIONS)), "YES" if wanted else "NO"]
    )

    def answer(_prompt):
        try:
            return next(answers)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr("builtins.input", answer)
    assert console._plain_loop(w) == (3 if wanted else 0)
    assert w.wants_shutdown is (not wanted)
    text = " ".join(capsys.readouterr().out.split())
    for paragraph in C.REPORT_HELP_SECTIONS:
        assert " ".join(paragraph.split()) in text
    assert w.report_wanted is wanted and w.selected is None and not w.runner.started


class Terminal:
    def __init__(self, w, keys, size):
        self.w, self.keys, self.size = w, iter(keys), size
        self.rows = {}
        self.pages = []

    def getmaxyx(self):
        return self.size

    def erase(self):
        self.rows = {}

    def addstr(self, y, x, text, attr=0):
        assert 0 <= y < self.size[0] and len(text) < self.size[1]
        self.rows[y] = text

    def getch(self):
        self.pages.append(" ".join(self.rows[y] for y in sorted(self.rows)))
        try:
            return next(self.keys)
        except StopIteration:
            self.w.wants_shutdown = True
            return -1

    def __getattr__(self, name):
        return lambda *args: None


@pytest.mark.parametrize("wanted", [True, False])
@pytest.mark.parametrize("size", [(24, 80), (20, 60)])
def test_curses_help_scrolls_all_media_guidance_at_small_sizes(
    monkeypatch, wanted, size
):
    w = make_demo_wizard()
    w.skip_splash()
    keys = [ord("r")] + ([ord(" ")] if wanted else []) + [console.curses.KEY_DOWN] * 100
    terminal = Terminal(w, keys, size)
    monkeypatch.setattr(console.curses, "curs_set", lambda *a: None)
    monkeypatch.setattr(console.curses, "use_default_colors", lambda *a: None)
    console._loop(terminal, w)
    all_pages = " ".join(terminal.pages)
    for phrase in [
        "FAT32",
        "exFAT",
        "NTFS",
        "FAT12",
        "FAT16",
        "loses power.",
        "while saving.",
        "Check disks",
        "not erase evidence",
    ]:
        assert phrase in all_pages
    assert f"[{'X' if wanted else ' '}] {C.REPORT_WANTED}" in terminal.pages[-1]
    assert w.report_wanted is wanted and not w.runner.started


@pytest.mark.parametrize(
    "fstype,fsver",
    [
        ("exfat", None),
        ("ntfs", None),
        ("vfat", "FAT12"),
        ("vfat", "FAT16"),
        (None, None),
    ],
)
def test_console_aftercare_displays_actual_unsupported_media_error(
    monkeypatch, capsys, tmp_path, fstype, fsver
):
    payload, disks = _payload()
    payload["blockdevices"][-1]["children"][0].update(fstype=fstype, fsver=fsver)

    def exporter(**kw):
        select_export_volume(payload, baseline_fingerprints(disks))
        pytest.fail("unsupported media reached export")

    w = _done_wizard(exporter, tmp_path)
    answers = iter(["SAVE", "SHUTDOWN"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    console._plain_loop(w)
    text = capsys.readouterr().out
    assert "FAT32" in text and C.REPORT_VOLATILE in text
    assert w.report_status == "error" and "saved and verified" not in text


def test_aftercare_never_promises_unavailable_report_or_safe_removal():
    text = C.report_aftercare(
        can_save=False, status="error", message="Report USB was removed."
    )
    assert "removed" in text and C.REPORT_VOLATILE in text
    assert "Insert" not in text and "safe to remove" not in text
    assert C.report_aftercare(can_save=True, status="idle", message="").startswith(
        C.REPORT_INSERT
    )


def test_plain_console_advanced_is_reachable_and_displays_synchronized_guidance(
    monkeypatch, capsys
):
    w = authorized()
    w.screen = Screen.METHOD
    answers = iter(["A", "", "REPORT", *([""] * len(C.REPORT_HELP_SECTIONS)), "BACK"])

    def answer(_):
        try:
            return next(answers)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr("builtins.input", answer)
    console._plain_loop(w)
    text = " ".join(capsys.readouterr().out.split())
    assert " ".join(C.ADVANCED_LOG_NOTE.split()) in text
    assert C.REPORT_HELP_TITLE in text and not w.runner.started


def test_curses_advanced_help_returns_without_advancing_method():
    w = authorized()
    w.screen = Screen.METHOD
    console._handle(w, ord("a"))
    assert w.screen == Screen.ADVANCED
    console._handle(w, ord("r"))
    console._handle(w, ord(" "))
    console._handle(w, 27)
    assert w.screen == Screen.ADVANCED and w.report_wanted
    console._handle(w, 10)
    assert w.screen == Screen.METHOD and not w.runner.started


def test_console_removal_error_and_explicit_retry_keep_report_unsaved(
    monkeypatch, capsys, tmp_path
):
    payload, disks = _payload()
    calls = []

    def exporter(**kw):
        calls.append(True)
        select_export_volume(
            {"blockdevices": payload["blockdevices"][:-1]}, baseline_fingerprints(disks)
        )
        pytest.fail("missing report USB reached worker")

    w = _done_wizard(exporter, tmp_path)
    answers = iter(["SAVE", "SHUTDOWN"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    console._plain_loop(w)
    text = capsys.readouterr().out
    assert len(calls) == 1 and "No new report USB found" in text
    assert C.REPORT_VOLATILE in text and w.report_status == "error"
    assert "saved and verified" not in text
