# SPDX-License-Identifier: GPL-3.0-or-later
"""Browser click-through must report a failed launch honestly."""

import webbrowser

import pytest

from beamo_wipe import app, gallery


def test_gallery_open_refuses_false_browser_result(tmp_path, monkeypatch):
    monkeypatch.setattr(webbrowser, "open", lambda *_args, **_kwargs: False)
    with pytest.raises(OSError, match="Browser"):
        gallery.open_gallery(tmp_path / "index.html")


def test_web_command_returns_error_when_browser_refuses(tmp_path, monkeypatch, capsys):
    helper = tmp_path / "helper" / "index.html"
    helper.parent.mkdir()
    helper.write_text("offline help", encoding="utf-8")
    monkeypatch.delenv("BEAMO_WIPE_NO_OPEN", raising=False)
    monkeypatch.setattr(webbrowser, "open", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(app, "project_root", lambda: tmp_path)
    assert app._main(["--web"]) == 2
    assert "browser" in capsys.readouterr().err.lower()
