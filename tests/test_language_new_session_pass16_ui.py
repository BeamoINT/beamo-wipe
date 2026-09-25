"""A fresh erase session keeps the owner's chosen language in sync with copy."""

from beamo_wipe import app, copy as C, lang


def test_erase_another_keeps_language_selection_and_visible_copy(monkeypatch):
    from beamo_wipe.ui import tk_wizard

    args = app._parser().parse_args(["--demo"])
    seen = []

    def fake_ui(wizard, **_kwargs):
        seen.append((wizard.language, C.TITLE_PICK))
        if len(seen) == 1:
            assert wizard.set_language("fr")
            wizard.wants_new_session = True
        else:
            wizard.wants_shutdown = True
        return 0

    monkeypatch.setattr(tk_wizard, "run_tk", fake_ui)
    lang.set_language("en")
    try:
        assert app._run_session(
            args, session_store=None, use_console=False,
            want_accessible=False, fullscreen=False, reader=None,
        ) == 0
        assert len(seen) == 2
        assert seen[1] == ("fr", "Quel disque devons-nous effacer ?")
    finally:
        lang.set_language("en")
