# SPDX-License-Identifier: GPL-3.0-or-later
"""Backlog #87: early language + keyboard-layout selection (EN/FR/DE)."""

import string

FRENCH_TITLE_PICK = "Quel disque devons-nous effacer ?"
GERMAN_TITLE_PICK = "Welcher Datenträger soll gelöscht werden?"

# Module-level UPPER names that are codes, filenames, or hook-rebuilt
# structures — never translated. Everything else UPPER/str/tuple-of-str
# must appear in the fr/de tables exactly.
EXCLUDED = {
    "copy": {
        "EMPTY_DISKS", "SSD_FOOTER", "DONE_OK", "DONE_FAIL", "METHOD_CARDS",
        "STOP_LEAD", "WHAT_MORE", "REPORT_HELP_SECTIONS", "REPORT_HELP_TEXT",
        "ADVANCED_LOG_NOTE", "APP_NAME",
        # Live re-exports, translated in their home modules.
        "STOP_WARNING", "EMPTY_STEPS", "OVERWRITE_LIMITS",
    },
    "keyboard": {"LAYOUTS", "LIMITS", "LAYOUT_ORDER", "DEFAULT_LAYOUT"},
    "outcomes": {"VIEWS"},
    "inventory": {"NESTED_SILENT_REASONS"},
    "storage_limits": {"SECTIONS"},
    "result_summary": {"STATUS_LABELS"},
    "support_export": {
        "LOG_STATUS_LINES", "UNSHARE_BIN", "PYTHON_BIN", "MOUNT_BIN",
        "UMOUNT_BIN", "SYNC_BIN", "MOUNTINFO_PATH", "REPORTS_DIR",
        "OWNER_WIPE_FILE", "OWNER_DIAGNOSTIC_FILE",
    },
    "discover": {
        "LIVE_MOUNTS", "LSBLK_BINARIES", "FINDMNT_BINARIES", "MOUNTINFO_PATH",
        "LSBLK_COLUMNS",
    },
    "models": {
        "CONTENTS_WINDOWS", "CONTENTS_SYSTEM", "CONTENTS_DATA", "CONTENTS_UNKNOWN",
    },
    "safety": {"PROTECTED_MOUNT_PREFIXES", "FORBIDDEN_LOG_ROOTS"},
    "engine_checks": {"CHECK_IDS", "PARSER"},
    "session_recovery": {"NAME"},
    "privacy": {"POLICY_ID", "SHARE_JSON", "SHARE_SUMMARY"},
    # Technical earcon ids and asset path; never displayed.
    "sound": {"KIND_FINISHED", "KIND_ATTENTION", "SOUNDS_DIR"},
}

# Translated values that are intentionally identical to English.
IDENTICAL_KEEPERS = {
    ("fr", "copy", "LANGUAGE_NAME_EN"),
    ("fr", "copy", "LANGUAGE_NAME_FR"),
    ("fr", "copy", "LANGUAGE_NAME_DE"),
    ("de", "copy", "LANGUAGE_NAME_EN"),
    ("de", "copy", "LANGUAGE_NAME_FR"),
    ("de", "copy", "LANGUAGE_NAME_DE"),
    ("fr", "copy", "CON_INPUT_PREFIX"),
    ("de", "copy", "CON_INPUT_PREFIX"),
    ("fr", "result_summary", "STATUS_PRODUCTION"),
    # Correct German is byte-identical to the English label here.
    ("de", "support_export", "README_SUPPORT"),
}


def _swept_surface():
    """Every translatable module-level name, swept from source."""
    import ast
    import pathlib

    from beamo_wipe import lang

    surface = {}
    for module_name in lang.TRANSLATED_MODULES:
        src = pathlib.Path(f"src/beamo_wipe/{module_name}.py").read_text()
        tree = ast.parse(src)
        keys = []
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                name = node.targets[0].id
                if not name.isupper() or name.startswith("_"):
                    continue
                if name in EXCLUDED.get(module_name, set()):
                    continue
                try:
                    value = ast.literal_eval(node.value)
                except Exception:
                    continue
                if isinstance(value, str):
                    keys.append(name)
                elif (
                    isinstance(value, (tuple, list))
                    and value
                    and all(isinstance(x, str) for x in value)
                ):
                    keys.append(name)
        surface[module_name] = keys
    return surface


def _placeholders(text):
    return {
        field
        for _, field, _, _ in string.Formatter().parse(text)
        if field is not None
    }


def test_lang_round_trip_restores_english_exactly():
    from beamo_wipe import copy as C
    from beamo_wipe import lang

    before = {m: dict(n) for m, n in lang.surface().items()}
    assert lang.set_language("fr") == "fr"
    assert C.TITLE_PICK == FRENCH_TITLE_PICK
    assert lang.set_language("de") == "de"
    assert C.TITLE_PICK == GERMAN_TITLE_PICK
    assert lang.set_language("en") == "en"
    assert {m: dict(n) for m, n in lang.surface().items()} == before
    assert lang.current() == "en"


def test_lang_rejects_unknown_codes():
    import pytest

    from beamo_wipe import lang

    assert lang.is_supported("en")
    assert lang.is_supported("fr")
    assert lang.is_supported("de")
    assert not lang.is_supported("es")
    assert not lang.is_supported("")
    with pytest.raises(ValueError):
        lang.set_language("es")
    assert lang.current() == "en"


def test_lang_tables_cover_the_same_surface_as_english():
    from beamo_wipe import lang

    surface = lang.surface()
    assert set(surface) >= {"copy", "keyboard", "methods", "outcomes"}
    assert len(surface["copy"]) >= 150
    for module in surface:
        assert lang.keys("fr", module) == lang.keys("de", module)
        assert set(lang.keys("fr", module)) == set(surface[module])
        for name in surface[module]:
            assert lang.english(module, name) == surface[module][name]


def test_swept_surface_matches_tables_exactly():
    from beamo_wipe import lang

    swept = _swept_surface()
    for module, keys in swept.items():
        assert set(lang.keys("fr", module)) == set(keys), module
        assert set(lang.keys("de", module)) == set(keys), module


def test_translations_carry_no_english_sentences():
    from beamo_wipe import lang

    for code in ("fr", "de"):
        for module in lang.surface():
            for name in lang.surface()[module]:
                english = lang.english(module, name)
                translated = lang.translated(code, module, name)
                if not isinstance(english, str) or len(english) < 25:
                    continue
                if " " not in english.strip():
                    continue
                if (code, module, name) in IDENTICAL_KEEPERS:
                    continue
                assert translated != english, (code, module, name)
                assert isinstance(translated, str) and translated.strip()


def test_translations_have_no_english_stopword_leak():
    from beamo_wipe import lang

    known_tokens = (
        "enter", "esc", "space", "tab", "up/down", "up ", " down",
        "page up", "page down", "pgup", "pgdn", "f2", "f5", "f8",
        "nwipe", "beamo", "usb", "fat32", "fat12", "fat16", "exfat", "ntfs",
        "linux", "windows", "or", "or ",
        "orca", "shift", "qwerty", "azerty", "qwertz", "share.json",
        "share.txt", "result.json", "result.txt", "/dev/sda", "yes", "no",
        "save", "erase", "stop", "keep", "cancel", "retry", "another",
        "shutdown", "diagnostic", "report", "back", "check disks again",
        "type", "complete", "error summary", "pass=", "verify=", "fsync=",
    )
    stopwords = (
        " the ", " and ", " with ", " from ", " that ", " this ",
        " will ", " your ", " have ", " they ", " them ", " does ",
        " are ", " for ", " use ", " all ", " but ", " not ",
        " you ", " can ",
    )
    for code in ("fr", "de"):
        for module in lang.surface():
            for name in lang.surface()[module]:
                english = lang.english(module, name)
                if not isinstance(english, str) or " " not in english:
                    continue
                scrubbed = f" {lang.translated(code, module, name).lower()} "
                for token in known_tokens:
                    scrubbed = scrubbed.replace(token, " ")
                for word in stopwords:
                    assert word not in scrubbed, (code, module, name, word)


def test_placeholders_and_spacing_survive_translation():
    from beamo_wipe import lang

    for code in ("fr", "de"):
        for module in lang.surface():
            for name in lang.surface()[module]:
                english = lang.english(module, name)
                translated = lang.translated(code, module, name)
                if isinstance(english, tuple):
                    assert isinstance(translated, tuple)
                    assert len(translated) == len(english), (code, module, name)
                    assert all(t.strip() for t in translated)
                    continue
                assert _placeholders(translated) == _placeholders(english), (
                    code, module, name,
                )
                assert translated[:1].isspace() == english[:1].isspace(), (
                    code, module, name,
                )
                assert translated[-1:].isspace() == english[-1:].isspace(), (
                    code, module, name,
                )
                assert translated.strip(), (code, module, name)


def test_every_template_formats_in_every_language():
    from collections import defaultdict

    from beamo_wipe import lang

    args = defaultdict(lambda: "X")
    for code in ("en", "fr", "de"):
        lang.set_language(code)
        for module in lang.surface():
            for name in lang.surface()[module]:
                value = lang.english(module, name) if code == "en" else lang.translated(code, module, name)
                texts = value if isinstance(value, tuple) else (value,)
                for text in texts:
                    if "{" in text:
                        text.format_map(args)


def test_derived_structures_rebuild_per_language():
    from beamo_wipe import copy as C
    from beamo_wipe import inventory, keyboard, lang, outcomes
    from beamo_wipe import result_summary, storage_limits, support_export

    lang.set_language("fr")
    assert outcomes.VIEWS["verified"].message == "Effacement terminé ; vérification réussie"
    assert C.DONE_OK == outcomes.VIEWS["verified"].message
    assert C.METHOD_CARDS
    assert keyboard.LAYOUTS["fr"].title == "AZERTY (français)"
    assert keyboard.LIMITS.startswith("Seuls QWERTY")
    assert result_summary.STATUS_LABELS["dirty"] == "modifié"
    assert "modifié" in str(result_summary.STATUS_LABELS)
    assert storage_limits.SECTIONS[0][0] == "Ce que cet outil prend en charge"
    assert inventory.NESTED_SILENT_REASONS == frozenset({"périphérique non pris en charge"})
    assert inventory.kind_label_for_type("part") == "Partition"
    assert support_export.LOG_STATUS_LINES["complete"] == "Journal du moteur : complet."
    assert C.EMPTY_DISKS == inventory.EMPTY_STEPS
    lang.set_language("en")
    assert outcomes.VIEWS["verified"].message == "Erase completed; verification passed"
    assert keyboard.LAYOUTS["fr"].title == "AZERTY (French)"
    assert inventory.NESTED_SILENT_REASONS == frozenset({"unsupported device"})


def test_markers_are_stable_across_languages():
    from beamo_wipe import lang
    from beamo_wipe.support_export import _marker_for

    skip_prefixes = ("RECEIPT_", "README_", "LOG_")
    skip = {"TRUNCATED_SUFFIX", "GENERIC_DESTINATION", "USB_NONE_FOUND", "USB_MANY_FOUND"}
    names = [
        n
        for n in lang.keys("fr", "support_export")
        if "{" not in lang.english("support_export", n)
        and not n.startswith(skip_prefixes)
        and n not in skip
    ]
    assert len(names) > 70
    english_markers = {}
    for code in ("en", "fr", "de"):
        lang.set_language(code)
        from beamo_wipe import support_export as S

        if code == "en":
            for name in names:
                english_markers[name] = _marker_for(getattr(S, name))
        else:
            for name in names:
                assert _marker_for(getattr(S, name)) == english_markers[name], (code, name)
        # The real compound messages (templates are never marked raw).
        for detail in (S.USB_NONE_FOUND, S.USB_MANY_FOUND):
            assert (
                _marker_for(S.USB_NOT_SINGLE.format(detail=detail))
                == "BEAMO_WIPE_EXPORT_FAIL_COUNT"
            ), code


def test_logic_comparisons_survive_translation():
    from beamo_wipe import identity, inventory, lang
    from beamo_wipe.progress import phase_display
    from beamo_wipe.safety import SafetyError
    from beamo_wipe import safety as safety_mod

    for code in ("fr", "de"):
        lang.set_language(code)
        # Token mismatch still compares exactly: both sides read one constant.
        try:
            raise SafetyError(safety_mod.TOKEN_MISMATCH)
        except SafetyError as exc:
            assert str(exc) == safety_mod.TOKEN_MISMATCH
        # Serial-label comparison follows the translated label.
        assert identity.SERIAL_LABEL != "Serial"
        # Phase codes stay comparable; only display changes.
        assert phase_display("Writing") != "Writing"
        assert phase_display("Writing") == lang.translated(code, "progress", "PHASE_WRITING")
        assert inventory.REASON_UNSUPPORTED in inventory.NESTED_SILENT_REASONS


def test_no_module_freezes_translated_names_at_import():
    """Module-level from-imports of translated names would stay English."""
    import ast
    import pathlib

    from beamo_wipe import lang

    translated = {
        module: set(lang.keys("fr", module)) | {"LAYOUTS", "VIEWS", "LIMITS"}
        for module in lang.surface()
    }
    offenders = []
    for path in sorted(pathlib.Path("src/beamo_wipe").rglob("*.py")):
        if "locales" in path.parts or path.name == "lang.py":
            continue
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("beamo_wipe")
            ):
                mod = node.module.split(".")[-1]
                if mod in translated:
                    hits = [a.name for a in node.names if a.name in translated[mod]]
                    if hits:
                        offenders.append(f"{path}:{node.lineno} {node.module} {hits}")
    assert offenders == []


def test_language_names_are_never_translated():
    from beamo_wipe import lang

    assert lang.LANGUAGE_NAMES == {"en": "English", "fr": "Français", "de": "Deutsch"}
    assert lang.LANGUAGE_ORDER == ("en", "fr", "de")


def test_wizard_language_validates_records_and_applies():
    from beamo_wipe import copy as C
    from beamo_wipe import lang
    from beamo_wipe.demo import make_demo_wizard

    wizard = make_demo_wizard()
    assert wizard.language == "en"
    assert wizard.set_language("xx") is False
    assert wizard.language == "en"
    assert lang.current() == "en"
    assert wizard.set_language("fr") is True
    assert wizard.language == "fr"
    assert C.TITLE_PICK == FRENCH_TITLE_PICK


def test_fresh_sessions_default_to_english_and_us():
    from beamo_wipe.demo import make_demo_wizard

    wizard = make_demo_wizard()
    assert (wizard.language, wizard.keyboard_layout) == ("en", "us")


def test_keyboard_screen_offers_languages_in_every_renderer():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    tk = (root / "src/beamo_wipe/ui/tk_wizard.py").read_text()
    assert "LANGUAGE_NAMES" in tk and "set_language" in tk
    console = (root / "src/beamo_wipe/ui/console_wizard.py").read_text()
    assert "LANGUAGE_NAMES" in console and "set_language" in console
    accessible = (root / "src/beamo_wipe/ui/accessible_wizard.py").read_text()
    assert "LANGUAGE_NAMES" in accessible and "set_language" in accessible
    gallery = (root / "src/beamo_wipe/gallery.py").read_text()
    assert "language" in gallery and "LANGUAGE_NAMES" in gallery


def test_confirmation_shows_active_layout_everywhere():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    for rel in (
        "src/beamo_wipe/ui/tk_wizard.py",
        "src/beamo_wipe/ui/console_wizard.py",
        "src/beamo_wipe/ui/accessible_wizard.py",
        "src/beamo_wipe/gallery.py",
    ):
        source = (root / rel).read_text()
        assert "CONFIRM_KEYBOARD_LINE" in source, rel


def test_evidence_records_locale_and_layout(monkeypatch):
    from beamo_wipe import evidence as E
    from beamo_wipe.demo import make_demo_wizard
    from beamo_wipe.keyboard import ApplyResult
    from beamo_wipe.models import MethodId

    wizard = make_demo_wizard()
    wizard.set_language("fr")
    wizard.skip_splash()
    monkeypatch.setattr(
        wizard, "_apply_keyboard", lambda layout_id, **_: ApplyResult(True, "", layout_id)
    )
    assert wizard.set_keyboard_layout("de") is True
    payload = E.build_evidence(
        disk=wizard.selectable[0],
        discovery=wizard.discovery,
        method=MethodId.EVERYDAY,
        request=None,
        result=None,
        started_at_wall=None,
        ended_at_wall=None,
        started_mono=None,
        ended_mono=None,
        argv=[],
        log_text="",
        language=wizard.language,
        keyboard_layout=wizard.keyboard_layout,
    )
    assert payload["locale"] == {"language": "fr", "keyboard_layout": "de"}


def test_evidence_locale_fails_closed_on_garbage():
    from beamo_wipe import evidence as E
    from beamo_wipe.demo import make_demo_wizard
    from beamo_wipe.models import MethodId

    wizard = make_demo_wizard()
    payload = E.build_evidence(
        disk=wizard.selectable[0],
        discovery=wizard.discovery,
        method=MethodId.EVERYDAY,
        request=None,
        result=None,
        started_at_wall=None,
        ended_at_wall=None,
        started_mono=None,
        ended_mono=None,
        argv=[],
        log_text="",
        language="xx",
        keyboard_layout="../evil",
    )
    assert payload["locale"] == {"language": "en", "keyboard_layout": "us"}


def test_french_console_keeps_exact_typed_commands(monkeypatch, capsys):
    from beamo_wipe import lang
    from beamo_wipe.demo import make_demo_wizard
    from beamo_wipe.ui import console_wizard as console

    from beamo_wipe import copy as C

    lang.set_language("fr")
    wizard = make_demo_wizard()
    answers = iter([""])

    def fake_input(_prompt=""):
        try:
            return next(answers)
        except StopIteration:
            raise EOFError

    monkeypatch.setattr("builtins.input", fake_input)
    console._plain_loop(wizard)
    output = capsys.readouterr().out
    assert C.TITLE_KEYBOARD in output
    assert "Check your keyboard" not in output
    assert "Language and keyboard" not in output


def test_german_console_wraps_at_80_columns(monkeypatch):
    from test_console_parity import _draw

    from beamo_wipe import copy as C
    from beamo_wipe import lang
    from beamo_wipe.demo import make_demo_wizard
    from beamo_wipe.models import Screen

    lang.set_language("de")
    wizard = make_demo_wizard()
    wizard.skip_intro()
    wizard.accept_what()
    wizard.set_owner(True)
    wizard.continue_owner()
    assert wizard.screen == Screen.PICK
    shown, _, _ = _draw(monkeypatch, wizard, h=24, w=80)
    assert C.pick_subtitle() in shown
    assert "Match the name, size and serial" not in shown
    assert "Which disk should we erase?" not in shown


def test_helper_ships_french_and_german():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "helper"
    index = (root / "index.html").read_text(encoding="utf-8")
    assert 'href="fr.html"' in index and 'href="de.html"' in index
    french = (root / "fr.html").read_text(encoding="utf-8")
    german = (root / "de.html").read_text(encoding="utf-8")
    assert 'lang="fr"' in french and 'lang="de"' in german
    assert "What this USB does" not in french
    assert "What this USB does" not in german


def test_translated_surfaces_carry_no_forbidden_claims():
    import pathlib

    from beamo_wipe import lang
    from beamo_wipe.gallery import gallery_html
    from test_copy import FORBIDDEN

    root = pathlib.Path(__file__).resolve().parents[1]
    for code in ("fr", "de"):
        blob = " ".join(
            t if isinstance(t, str) else " ".join(t)
            for module in lang.surface()
            for t in (lang.translated(code, module, n) for n in lang.surface()[module])
        ).lower()
        blob += " " + (root / f"helper/{code}.html").read_text(encoding="utf-8").lower()
        blob += " " + gallery_html(code).lower()
        for phrase in FORBIDDEN:
            if phrase == "apple silicon":
                continue
            assert phrase not in blob, (code, phrase)
    fr_blob = (root / "helper/fr.html").read_text(encoding="utf-8").lower()
    assert "pas les mac apple silicon" in fr_blob
    de_blob = (root / "helper/de.html").read_text(encoding="utf-8").lower()
    assert "keine apple-silicon-macs" in de_blob


def test_tokens_stay_ascii_exact_in_every_language():
    from beamo_wipe import lang
    from beamo_wipe.models import ConfirmSpec
    from beamo_wipe.safety import token_matches

    spec = ConfirmSpec(token="S4EV", prompt="x")
    for code in ("en", "fr", "de"):
        lang.set_language(code)
        assert token_matches("S4EV", spec)
        assert token_matches("s4ev", spec)
        assert not token_matches("S4EW", spec)
        assert not token_matches("", spec)


def test_gallery_renders_every_language_without_tokens():
    import json

    from beamo_wipe.gallery import gallery_html

    for code, needle in (
        ("en", "Which disk should we erase?"),
        ("fr", FRENCH_TITLE_PICK),
        ("de", GERMAN_TITLE_PICK),
    ):
        html = gallery_html(code)
        assert f'<html lang="{code}">' in html
        # The payload is ensure_ascii JSON: match its escaped form.
        assert json.dumps(needle)[1:-1] in html
        assert "__GALLERY_" not in html
        assert "__PAYLOAD__" not in html
    import pytest

    with pytest.raises(ValueError):
        gallery_html("es")
