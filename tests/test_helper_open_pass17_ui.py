# SPDX-License-Identifier: GPL-3.0-or-later
"""A browser launch refusal must not be reported as a successful helper open."""

import webbrowser

from beamo_wipe.app import _open_html


def test_helper_open_reports_browser_launch_failure(tmp_path, monkeypatch, capsys):
    helper = tmp_path / "helper.html"
    helper.write_text("safe offline help", encoding="utf-8")
    monkeypatch.delenv("BEAMO_WIPE_NO_OPEN", raising=False)
    monkeypatch.setattr(webbrowser, "open", lambda *_args, **_kwargs: False)
    assert _open_html(helper) == 2
    assert "could not open" in capsys.readouterr().err.lower()


def test_helper_open_accepts_browser_launch(tmp_path, monkeypatch, capsys):
    helper = tmp_path / "helper.html"
    helper.write_text("safe offline help", encoding="utf-8")
    monkeypatch.delenv("BEAMO_WIPE_NO_OPEN", raising=False)
    monkeypatch.setattr(webbrowser, "open", lambda *_args, **_kwargs: True)
    assert _open_html(helper) == 0
    assert str(helper) in capsys.readouterr().out
