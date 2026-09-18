# SPDX-License-Identifier: GPL-3.0-or-later
"""Backlog #84: warnings, errors, limits, protection, and saved reports differ
by wording, icon, and layout — never by color alone.

Baseline (fails before the fix, at 60d827a + uncommitted #83 spacing WIP):
Tk warn/danger panels share one triangle glyph; a saved report renders as
neutral info; the keyboard screen shows errors as warnings; console, gallery,
and accessible views carry no severity words; the review-screen erase warning
is bold red text only. See docs/evidence/warning-success-84/README.md.
"""

import inspect

import pytest

from beamo_wipe import copy as C
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.gallery import gallery_html
from beamo_wipe.models import Screen
from beamo_wipe.outcomes import VIEWS
from beamo_wipe.safety import same_size_conflict
from beamo_wipe.ui import console_wizard as console
from beamo_wipe.wizard import ReportView
from test_result_presentations import CASES, case_evidence


def _luminance(hex_color: str) -> float:
    rgb = [int(hex_color[i : i + 2], 16) / 255.0 for i in (1, 3, 5)]

    def channel(value: float) -> float:
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(v) for v in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(fg: str, bg: str) -> float:
    first, second = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (first + 0.05) / (second + 0.05)


def test_severity_words_are_plain_customer_language():
    assert C.SEVERITY_WARNING == "Warning"
    assert C.SEVERITY_ERROR == "Error"
    assert C.SEVERITY_LIMITS == "Limits"
    assert C.SEVERITY_PROTECTED == "Protected"
    assert C.SEVERITY_SAVED == "Saved"


@pytest.mark.parametrize("status", ["idle", "saving", "saved", "error", "bogus"])
@pytest.mark.parametrize("evidence_error", [None, "Cannot check evidence."])
@pytest.mark.parametrize("saving_evidence", [False, True])
def test_report_tone_marks_only_saved_copies_as_success(
    status, evidence_error, saving_evidence
):
    """Would fail when saved reports shared the neutral info tone."""
    report = ReportView(
        0,
        status,
        "",
        "",
        status == "saving",
        False,
        evidence_error,
        saving_evidence,
    )
    if evidence_error or status == "error":
        assert report.tone == "warn"
    elif status == "saved" and not saving_evidence:
        assert report.tone == "ok"
    else:
        assert report.tone == "info"
    assert report.tone != "danger"


def test_unverified_erase_outcomes_never_take_success_tone():
    """success=True without read-back proof must not look successful."""
    assert VIEWS["unverified"].success is True
    assert VIEWS["unverified"].tone == "warn"
    assert VIEWS["unverified"].icon == "warn"
    assert VIEWS["verified"].tone == "ok"
    assert VIEWS["verified"].icon == "check"


class _StubCanvas:
    """Records canvas drawing calls without needing a display."""

    def __init__(self):
        self.calls = []

    def create_polygon(self, *args, **kwargs):
        self.calls.append(("polygon", args, kwargs))
        return len(self.calls)

    def create_oval(self, *args, **kwargs):
        self.calls.append(("oval", args, kwargs))
        return len(self.calls)

    def create_line(self, *args, **kwargs):
        self.calls.append(("line", args, kwargs))
        return len(self.calls)


def _glyph_calls(kind):
    from beamo_wipe.ui import tk_wizard as tk_mod

    stub = _StubCanvas()
    tk_mod._draw_alert_glyph(stub, 0, 0, 28, kind)
    return stub.calls


def test_tk_severity_glyphs_differ_by_shape_not_color():
    """Would fail when warn/danger shared one triangle; ok/limits missing."""
    from beamo_wipe.ui import tk_wizard as tk_mod

    warn = _glyph_calls("warn")
    danger = _glyph_calls("danger")
    info = _glyph_calls("info")
    ok = _glyph_calls("ok")
    limits = _glyph_calls("limits")
    assert warn[0][0] == "polygon"  # triangle
    assert len(warn[0][1]) == 6
    assert danger[0][0] == "oval"  # circle, not the warning triangle
    assert danger[0][2].get("fill") == tk_mod.DANGER
    crosses = [c for c in danger if c[0] == "line"]
    assert len(crosses) == 2  # X, distinct from the info stem and ok check
    assert info[0][0] == "oval" and info[0][2].get("fill") == tk_mod.PRIMARY
    assert ok[0][0] == "oval" and ok[0][2].get("fill") == tk_mod.OK
    assert [c for c in ok if c[0] == "line"]  # check mark, no halo badge
    assert limits[0][0] == "polygon"  # rounded square document
    assert len(limits[0][1][0]) == 24
    assert len([c for c in limits if c[0] == "line"]) >= 2
    with pytest.raises(ValueError):
        _glyph_calls("bogus")


def test_tk_panels_label_every_severity_but_neutral_info():
    """Would fail when panels carried no severity words and no ok/limits."""
    from beamo_wipe.ui import tk_wizard as tk_mod

    source = inspect.getsource(tk_mod.TkWizard._panel)
    for kind in ('"warn"', '"danger"', '"info"', '"ok"', '"limits"'):
        assert kind in source
    assert "SEVERITY_WARNING" in source
    assert "SEVERITY_ERROR" in source
    assert "SEVERITY_SAVED" in source
    assert "SEVERITY_LIMITS" in source
    assert "OK_TINT" in source


def test_tk_severity_label_contrast_meets_aa():
    """Would fail without the darker label colors on tinted panels."""
    from beamo_wipe.ui import tk_wizard as tk_mod

    pairs = [
        (tk_mod.WARN, tk_mod.WARN_BG),
        (tk_mod.DANGER, tk_mod.DANGER_TINT),
        (tk_mod.OK, tk_mod.OK_TINT),
        (tk_mod.PRIMARY, tk_mod.SURFACE_ALT),
        (tk_mod.INK, tk_mod.WARN_BG),
        (tk_mod.INK, tk_mod.DANGER_TINT),
        (tk_mod.INK, tk_mod.OK_TINT),
    ]
    for fg, bg in pairs:
        assert _contrast(fg, bg) >= 4.5, (fg, bg, _contrast(fg, bg))


def test_tk_keyboard_error_is_danger_not_warning():
    """Would fail while keyboard errors reused the warning panel."""
    from beamo_wipe.ui import tk_wizard as tk_mod

    source = inspect.getsource(tk_mod.TkWizard._keyboard)
    assert 'kind="danger"' in source
    assert source.index("self.w.error") < source.index("self.w.keyboard_message")


def test_tk_blocked_and_storage_sites_use_error_and_limits():
    """Would fail while blocked used warn and notices reused info."""
    from beamo_wipe.ui import tk_wizard as tk_mod

    assert '"danger"' in inspect.getsource(tk_mod.TkWizard._blocked)
    pick = inspect.getsource(tk_mod.TkWizard._pick)
    assert 'kind="limits"' in pick
    method = inspect.getsource(tk_mod.TkWizard._method)
    assert 'kind="limits"' in method
    last = inspect.getsource(tk_mod.TkWizard._last)
    assert "SEVERITY_WARNING" in last


def _run_plain(wizard, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError()))
    console._plain_loop(wizard)
    return capsys.readouterr().out


def test_console_saved_report_is_labeled_saved_not_neutral(monkeypatch, capsys):
    """Would fail when the saved headline printed with no severity word."""
    wizard, _, _ = case_evidence(CASES[0])
    wizard.report_status = "saved"
    output = _run_plain(wizard, monkeypatch, capsys)
    assert f"{C.SEVERITY_SAVED}: Report copy saved and checked" in output


def test_console_report_problems_stay_warnings_not_errors(monkeypatch, capsys):
    """Would fail before severity words; guards the deliberate no-red rule."""
    wizard, _, _ = case_evidence(CASES[0])
    wizard.report_status = "error"
    output = _run_plain(wizard, monkeypatch, capsys)
    assert f"{C.SEVERITY_WARNING}: Report copy could not be saved and checked" in output
    assert f"{C.SEVERITY_ERROR}:" not in output.split(C.REPORT_STATUS_TITLE)[1]


def test_console_errors_warnings_and_limits_carry_words(monkeypatch, capsys):
    """Would fail when console severities printed as bare text."""
    blocked = make_demo_wizard(scenario="blocked")
    blocked.skip_intro()
    blocked.accept_what()
    blocked.set_owner(True)
    blocked.continue_owner()
    assert blocked.screen == Screen.PICK_BLOCKED
    output = _run_plain(blocked, monkeypatch, capsys)
    assert C.SEVERITY_ERROR in output
    from beamo_wipe import recovery as R
    assert R.RECOVERY_HAPPENED in output
    assert C.IDENTIFY_ERROR in output

    picking = make_demo_wizard()
    picking.skip_intro()
    picking.accept_what()
    picking.set_owner(True)
    picking.continue_owner()
    assert picking.screen == Screen.PICK
    assert same_size_conflict(picking.listed_disks)
    output = _run_plain(picking, monkeypatch, capsys)
    assert f"{C.SEVERITY_WARNING}: {C.SAME_SIZE_HINT}" in output
    assert C.BOOT_USB_BANNER in output  # protected wording is the label


def test_console_keyboard_error_is_labeled_error(monkeypatch, capsys):
    """Would fail while keyboard errors printed unlabeled."""
    wizard = make_demo_wizard()
    wizard.skip_splash()
    assert wizard.screen == Screen.KEYBOARD
    wizard.error = "Could not change the keyboard layout."
    output = _run_plain(wizard, monkeypatch, capsys)
    from beamo_wipe import recovery as R
    assert C.SEVERITY_ERROR in output
    assert "Could not change the keyboard layout." in output
    assert R.RECOVERY_HAPPENED in output


def test_curses_report_and_pick_severities_carry_words(monkeypatch):
    """Would fail when the curses view printed bare severities."""
    from test_console_parity import _draw

    wizard, _, _ = case_evidence(CASES[0])
    wizard.report_status = "saved"
    shown, _, _ = _draw(monkeypatch, wizard, h=40, w=80)
    assert C.SEVERITY_SAVED in shown
    assert "Report copy saved and checked" in shown

    picking = make_demo_wizard()
    picking.skip_intro()
    picking.accept_what()
    picking.set_owner(True)
    picking.continue_owner()
    shown, _, _ = _draw(monkeypatch, picking, h=40, w=80)
    assert f"{C.SEVERITY_WARNING}:" in shown


def test_gallery_panels_mirror_glyphs_labels_and_roles():
    """Would fail with one triangle, no labels, and no ARIA roles."""
    html = gallery_html()
    assert C.SEVERITY_WARNING in html
    assert C.SEVERITY_ERROR in html
    assert C.SEVERITY_SAVED in html
    assert C.SEVERITY_LIMITS in html
    assert 'role="alert"' in html
    assert 'role="status"' in html
    assert 'role="note"' in html
    assert ".panel.ok" in html
    assert ".panel.limits" in html
    assert 'kind === "ok"' in html
    assert 'kind === "limits"' in html
    assert "review-warning" in html
    segment = html.split('<p class="review-warning">')[1].split("</p>")[0]
    assert "sevWarning" in segment


def test_accessible_view_marks_severity_in_words_and_roles():
    """Would fail with red warnings, bare text, and no alert roles."""
    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parents[1]
        / "src/beamo_wipe/ui/accessible_wizard.py"
    ).read_text()
    for name in (
        "SEVERITY_WARNING",
        "SEVERITY_ERROR",
        "SEVERITY_SAVED",
        "SEVERITY_LIMITS",
    ):
        assert name in source
    assert "Atk.Role.ALERT" in source
    assert "report-saved" in source
    assert ".erase-warning { background: #FBF1D5; color: #7A5200;" in source
    assert "def _error_text" in source
    assert source.count("_error_text(self.w)") == 2


def test_severity_words_have_one_localization_source():
    """Would fail if renderers hardcoded severity words outside copy.py."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1] / "src/beamo_wipe"
    pattern = re.compile(r'"(Warning|Error|Limits|Protected|Saved)"')
    hits = []
    for path in list((root / "ui").glob("*.py")) + [root / "gallery.py"]:
        if path.name == "copy.py":
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if pattern.search(line):
                hits.append(f"{path.name}:{lineno}:{line.strip()}")
    assert hits == []


def test_preview_report_stays_neutral_and_badges_keep_canonical_icons():
    """Guards: preview never takes success styling; erase icons unchanged."""
    from beamo_wipe.ui import tk_wizard as tk_mod

    done = inspect.getsource(tk_mod.TkWizard._done)
    assert '"info" if self.w.preview else report.tone' in done
    for code, view in VIEWS.items():
        assert view.icon == ("check" if view.tone == "ok" else view.tone), code
