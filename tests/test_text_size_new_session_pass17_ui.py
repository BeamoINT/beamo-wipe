# SPDX-License-Identifier: GPL-3.0-or-later
"""An erase-another session retains the owner's accessibility choice."""

from beamo_wipe import app


def test_erase_another_keeps_text_size_in_fresh_wizard(monkeypatch):
    from beamo_wipe.ui import tk_wizard

    args = app._parser().parse_args(["--demo"])
    seen = []

    def fake_ui(wizard, **_kwargs):
        seen.append(wizard.text_size)
        if len(seen) == 1:
            assert wizard.set_text_size("extra")
            wizard.wants_new_session = True
        else:
            wizard.wants_shutdown = True
        return 0

    monkeypatch.setattr(tk_wizard, "run_tk", fake_ui)
    assert app._run_session(
        args, session_store=None, use_console=False,
        want_accessible=False, fullscreen=False, reader=None,
    ) == 0
    assert seen == ["standard", "extra"]
