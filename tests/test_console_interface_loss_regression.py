"""Unexpected console failures retain fake engine ownership until settled."""

import pytest

from beamo_wipe import app
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen
from beamo_wipe.ui import console_wizard as console
from test_audit_20260907_console_input import _working


def _assert_fake_engine_settled(wizard):
    assert wizard.runner.cancelled
    assert wizard.wipe_result is not None
    assert wizard.wipe_result.summary == "interrupted"
    assert wizard.screen == Screen.DONE


def test_curses_unexpected_failure_settles_active_fake_engine(monkeypatch, tmp_path):
    wizard = _working(monkeypatch, tmp_path)

    def crash(_run):
        raise RuntimeError("simulated curses render failure")

    monkeypatch.setattr(console.curses, "wrapper", crash)
    with pytest.raises(RuntimeError, match="simulated curses render failure"):
        console.run_console(wizard)
    _assert_fake_engine_settled(wizard)


def test_plain_unexpected_failure_settles_active_fake_engine(monkeypatch, tmp_path):
    wizard = _working(monkeypatch, tmp_path)

    def crash(_wizard):
        raise RuntimeError("simulated plain render failure")

    monkeypatch.setattr(console, "_plain_loop_body", crash)
    with pytest.raises(RuntimeError, match="simulated plain render failure"):
        console._plain_loop(wizard)
    _assert_fake_engine_settled(wizard)


@pytest.mark.parametrize("plain", [False, True])
def test_app_console_boundary_settles_before_releasing_session(
    monkeypatch, tmp_path, plain
):
    wizard = _working(monkeypatch, tmp_path)
    args = app._parser().parse_args(["--plain-console"] if plain else ["--console"])
    monkeypatch.setattr(app, "_build_wizard_with_console_stages", lambda _args: wizard)
    entry = "_plain_loop" if plain else "run_console"

    def crash(_wizard):
        raise RuntimeError("simulated console interface loss")

    monkeypatch.setattr(console, entry, crash)
    with pytest.raises(RuntimeError, match="simulated console interface loss"):
        app._run_one_session(
            args,
            session_store=None,
            use_console=True,
            want_accessible=False,
            fullscreen=False,
            reader=None,
        )
    _assert_fake_engine_settled(wizard)


@pytest.mark.parametrize("code", [0, 3])
def test_app_console_unexpected_return_settles_active_fake_engine(
    monkeypatch, tmp_path, code
):
    wizard = _working(monkeypatch, tmp_path)
    args = app._parser().parse_args(["--console"])
    monkeypatch.setattr(app, "_build_wizard_with_console_stages", lambda _args: wizard)
    monkeypatch.setattr(console, "run_console", lambda _wizard: code)

    assert app._run_one_session(
        args,
        session_store=None,
        use_console=True,
        want_accessible=False,
        fullscreen=False,
        reader=None,
    ) == code
    _assert_fake_engine_settled(wizard)


def test_app_console_accepted_shutdown_keeps_normal_exit(monkeypatch):
    wizard = make_demo_wizard()
    wizard.shutdown()
    assert wizard.wants_shutdown
    args = app._parser().parse_args(["--console"])
    monkeypatch.setattr(app, "_build_wizard_with_console_stages", lambda _args: wizard)
    monkeypatch.setattr(console, "run_console", lambda _wizard: 0)

    def unexpected_settlement():
        pytest.fail("accepted shutdown should not be treated as interface loss")

    monkeypatch.setattr(wizard, "settle_failed_interface", unexpected_settlement)
    assert app._run_one_session(
        args,
        session_store=None,
        use_console=True,
        want_accessible=False,
        fullscreen=False,
        reader=None,
    ) == 0
