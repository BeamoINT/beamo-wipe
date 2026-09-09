# SPDX-License-Identifier: GPL-3.0-or-later
"""Last-chance operation summary and authorization invalidation. Fake disks only."""

import pytest

from beamo_wipe.copy import AUTHORIZATION_STALE
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.methods import METHODS
from beamo_wipe.models import MethodId, Screen, WipeRequest
from beamo_wipe.nwipe_runner import DryRunRunner, build_nwipe_argv
from beamo_wipe.wizard import Wizard
from test_tk_runtime import ui, _drive_to  # noqa: F401


SUMMARIES = {
    MethodId.EVERYDAY: "One overwrite, followed by verification.",
    MethodId.EXTRA: "Three overwrites, followed by verification.",
    MethodId.QUICK_ZERO: "One overwrite. Verification is not performed.",
}


def _at_last(method=MethodId.EVERYDAY):
    wiz = make_demo_wizard()
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    wiz.select_disk(sorted(wiz.selectable, key=lambda d: d.path)[0].path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.set_method(method)
    wiz.continue_method()
    return wiz


@pytest.mark.parametrize("method_id,expected", list(SUMMARIES.items()))
def test_operation_summary_matches_spec_and_argv(method_id, expected):
    spec = METHODS[method_id]
    assert spec.operation_summary == expected
    if spec.verification_passes:
        assert spec.overwrite_passes >= 1
        assert "followed by verification" in expected
    else:
        assert spec.verification_passes == 0
        assert "Verification is not performed" in expected
    wiz = _at_last(method_id)
    assert wiz.operation_summary == expected
    assert wiz.screen == Screen.LAST_CHANCE
    argv = build_nwipe_argv(
        WipeRequest(
            wiz.selected.path,
            method_id,
            wiz.discovery.boot.path,
            "/tmp/beamo-wipe/nwipe-fake.log",
        )
    )
    assert f"--method={spec.nwipe_method}" in argv
    assert f"--verify={spec.verify}" in argv
    assert "--rounds=1" in argv
    assert "--noblank" in argv
    assert ev_summary_in_evidence(wiz, expected)


def ev_summary_in_evidence(wiz, expected):
    from beamo_wipe.evidence import build_evidence
    from beamo_wipe.models import WipeResult

    ev = build_evidence(
        disk=wiz.selected,
        discovery=wiz.discovery,
        method=wiz.method,
        request=None,
        result=WipeResult(False, 1, "nwipe exited 1", "fake-log"),
        started_at_wall="",
        ended_at_wall="",
        started_mono=0,
        ended_mono=1,
        argv=[],
        log_text="",
    )
    assert ev["method"]["operation_summary"] == expected
    assert ev["method"]["overwrite_passes"] == METHODS[wiz.method].overwrite_passes
    assert ev["method"]["verification_passes"] == METHODS[wiz.method].verification_passes
    return True


@pytest.mark.parametrize("method_id", list(METHODS))
def test_last_chance_back_without_change_keeps_token_and_needs_new_countdown(method_id):
    wiz = _at_last(method_id)
    token = wiz.confirm_input
    wiz.back()
    assert wiz.screen == Screen.METHOD
    assert wiz._erase_until is None
    assert wiz.confirm_input == token
    wiz.continue_method()
    assert wiz.screen == Screen.LAST_CHANCE
    assert wiz.countdown_left > 0
    assert wiz.confirm_input == token
    assert not wiz.erase_enabled


@pytest.mark.parametrize("method_id", list(METHODS))
def test_method_change_after_last_chance_requires_full_confirm(method_id):
    wiz = _at_last(method_id)
    other = next(mid for mid in METHODS if mid != method_id)
    wiz.back()
    wiz.set_method(other)
    assert wiz.confirm_input == ""
    assert wiz._authorized_operation is None
    wiz.continue_method()
    assert wiz.screen == Screen.CONFIRM
    assert not wiz.token_ok
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.set_method(other)
    wiz.continue_method()
    assert wiz.screen == Screen.LAST_CHANCE
    assert wiz.operation_summary == SUMMARIES[other]
    assert wiz.countdown_left > 0


def test_target_change_clears_authorization():
    wiz = _at_last()
    first = wiz.selected.path
    other = next(d.path for d in wiz.selectable if d.path != first)
    wiz.back()
    wiz.back()
    wiz.back()
    assert wiz.screen == Screen.PICK
    wiz.select_disk(other)
    assert wiz.confirm_input == ""
    assert wiz._authorized_operation is None
    wiz.continue_pick()
    assert wiz.screen == Screen.CONFIRM
    assert not wiz.token_ok


def test_stale_authorization_cannot_start_erase(monkeypatch, tmp_path):
    monkeypatch.setattr("beamo_wipe.safety.default_log_dir", lambda: tmp_path)
    wiz = _at_last()
    wiz.preview = False
    wiz._erase_until = 0
    wiz._authorized_operation = ("stale",)
    wiz.confirm_erase()
    assert wiz.screen == Screen.CONFIRM
    assert wiz.error == AUTHORIZATION_STALE
    assert not getattr(wiz.runner, "started", False)
    assert wiz.wipe_result is None


def test_refresh_invalidates_last_chance_authorization():
    def rediscover():
        return make_demo_wizard().discovery

    base = make_demo_wizard()
    wiz = Wizard(base.discovery, DryRunRunner(duration_s=0.5), dry_run=True, rediscover=rediscover)
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    wiz.select_disk(wiz.selectable[0].path)
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    wiz.continue_method()
    assert wiz.screen == Screen.LAST_CHANCE
    assert wiz.refresh_disks()
    assert wiz.confirm_input == ""
    assert wiz._erase_until is None
    assert wiz._authorized_operation is None
    assert wiz.screen in {Screen.WHAT, Screen.PICK, Screen.PICK_BLOCKED, Screen.PICK_EMPTY}


@pytest.mark.parametrize("method_id", list(METHODS))
def test_last_chance_tk_shows_operation_next_to_identity(ui, method_id):  # noqa: F811
    wiz, app = ui()
    _drive_to(wiz, app, Screen.METHOD)
    wiz.set_method(method_id)
    wiz.continue_method()
    app._draw()
    app.root.update()
    texts = []

    def visit(widget):
        if widget.winfo_class() == "Label":
            texts.append(str(widget.cget("text")))
        for child in widget.winfo_children():
            visit(child)

    visit(app.root)
    view = wiz.disk_view(wiz.selected)
    assert view.title in texts
    assert SUMMARIES[method_id] in texts
    assert texts.index(SUMMARIES[method_id]) > texts.index(view.title)
    assert wiz.erase_label() in texts
