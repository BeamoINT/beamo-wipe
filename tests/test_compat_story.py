# SPDX-License-Identifier: GPL-3.0-or-later
"""USB build identity and current-build compatibility guidance. Fake disks only."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from beamo_wipe import __version__
from beamo_wipe.build_identity import (
    STATUS_DEVELOPMENT,
    STATUS_DIRTY,
    STATUS_PRODUCTION,
    write_injected,
)
from beamo_wipe.compat_story import (
    HISTORY_DUMP,
    LABEL_PRODUCTION,
    MARKERS,
    NOT_PACKAGED,
    OLDER_MEDIA,
    PLATFORMS,
    SECURE_BOOT,
    SOURCE_STUB,
    THIS_IMAGE_ONLY,
    customer_label,
    inject_helper_html,
    required_story_phrases,
    sentence_from_application,
    version_report,
)
from beamo_wipe.copy import SECURE_BOOT_HINT, WHAT_BULLETS, this_usb_line

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "helper" / "index.html"
DESKTOP = ROOT / "desktop/web/index.html"
DESKTOP_JS = ROOT / "desktop/web/app.js"
BUILD_ISO = ROOT / "scripts" / "build-iso.sh"
PRODUCTION_ID = "12345678-1234-1234-1234-123456789abc"
COMMIT = "a" * 40
DIGEST = "b" * 64


def _html() -> str:
    return HELPER.read_text(encoding="utf-8")


def _payload(**kwargs):
    return write_injected(
        Path(kwargs.pop("path")),
        source_commit=kwargs.get("source_commit", COMMIT),
        source_sha256=kwargs.get("source_sha256", DIGEST),
        build_id=kwargs.get("build_id", PRODUCTION_ID),
        source_dirty=kwargs.get("source_dirty", False),
        allow_dirty=kwargs.get("allow_dirty", False),
        hosted=kwargs.get("hosted", False),
    )


def test_source_helper_is_honest_checkout_stub():
    html = _html()
    assert SOURCE_STUB in html
    assert "id=\"this-usb\"" in html
    assert f"Beamo Wipe <!--BEAMO_VERSION-->{__version__}<!--/BEAMO_VERSION-->" in html
    assert NOT_PACKAGED in html
    for name in MARKERS:
        assert html.count(f"<!--{name}-->") == 1
        assert html.count(f"<!--/{name}-->") == 1
    assert "<script" not in html
    assert "<link rel=\"stylesheet\"" not in html


def test_helper_and_desktop_match_current_build_story():
    helper = _html()
    desktop = DESKTOP.read_text(encoding="utf-8")
    for phrase in (SECURE_BOOT, OLDER_MEDIA, THIS_IMAGE_ONLY):
        assert phrase in helper, phrase
    assert "For 64-bit Intel/AMD Windows or Linux PCs that start from this USB." in helper
    assert "Not Apple Silicon Macs. Not Chromebooks." in helper
    assert PLATFORMS in desktop
    assert SECURE_BOOT in desktop
    assert OLDER_MEDIA in desktop
    assert PLATFORMS == WHAT_BULLETS[-1]
    assert "signed boot files" in SECURE_BOOT_HINT
    assert "does not change Secure Boot" in SECURE_BOOT_HINT
    assert required_story_phrases() == (PLATFORMS, SECURE_BOOT, OLDER_MEDIA, THIS_IMAGE_ONLY)


def test_customer_surfaces_do_not_dump_development_history():
    blobs = [
        _html().lower(),
        DESKTOP.read_text(encoding="utf-8").lower(),
        (ROOT / "docs" / "boot-card.md").read_text(encoding="utf-8").lower(),
        (ROOT / "docs" / "claims.md").read_text(encoding="utf-8").lower(),
    ]
    for blob in blobs:
        for phrase in HISTORY_DUMP:
            assert phrase not in blob, phrase


def test_inject_production_helper_replaces_stub(tmp_path):
    payload = _payload(path=tmp_path / "build-identity.json")
    out = inject_helper_html(
        _html(), version=__version__, injected=payload, packaged=True
    )
    assert SOURCE_STUB not in out
    assert LABEL_PRODUCTION in out
    assert PRODUCTION_ID in out
    assert COMMIT in out
    assert ">production<" in out
    assert NOT_PACKAGED not in out
    assert "<script" not in out
    assert SECURE_BOOT in out
    assert "Not Apple Silicon Macs. Not Chromebooks." in out


def test_inject_local_build_is_not_manufactured(tmp_path):
    payload = _payload(path=tmp_path / "build-identity.json", build_id="local")
    out = inject_helper_html(
        _html(), version=__version__, injected=payload, packaged=True
    )
    assert SOURCE_STUB not in out
    assert "development image, not a manufactured release" in out
    assert ">local<" in out
    assert ">development<" in out


def test_inject_dirty_build_is_not_production(tmp_path):
    payload = _payload(
        path=tmp_path / "build-identity.json", source_dirty=True, allow_dirty=True
    )
    out = inject_helper_html(
        _html(), version=__version__, injected=payload, packaged=True
    )
    assert "built from changed source" in out
    assert ">dirty<" in out
    assert LABEL_PRODUCTION not in out


def test_inject_refuses_missing_markers_or_identity():
    with pytest.raises(RuntimeError, match="manufactured helper"):
        inject_helper_html(_html(), version=__version__, injected=None, packaged=True)
    with pytest.raises(RuntimeError, match="marker"):
        inject_helper_html("<html></html>", version=__version__, injected={}, packaged=False)
    with pytest.raises(RuntimeError, match="invalid build identity"):
        inject_helper_html(
            _html(),
            version=__version__,
            injected={
                "source_commit": "short",
                "source_sha256": DIGEST,
                "build_id": PRODUCTION_ID,
                "source_dirty": False,
            },
            packaged=True,
        )


def test_iso_builder_copies_then_injects_helper(tmp_path):
    script = BUILD_ISO.read_text(encoding="utf-8")
    assert 'cp "$ROOT/helper/index.html" "$STAGE_SHARE/helper/index.html"' in script
    assert 'cp "$ROOT/helper/index.html" "$STAGE_BIN/START-HERE.html"' in script
    assert "inject_helper_html" in script
    assert "includes.binary/build-identity.json" in script
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "packaging/live/config/includes.binary/build-identity.json" in gitignore
    ignored = subprocess.run(
        [
            "git",
            "check-ignore",
            "-q",
            "packaging/live/config/includes.binary/build-identity.json",
        ],
        cwd=ROOT,
    )
    assert ignored.returncode == 0
    identity = tmp_path / "build-identity.json"
    payload = _payload(path=identity)
    share = tmp_path / "helper"
    share.mkdir()
    binary = tmp_path / "binary"
    binary.mkdir()
    (share / "index.html").write_text(_html(), encoding="utf-8")
    (binary / "START-HERE.html").write_text(_html(), encoding="utf-8")
    injected = inject_helper_html(
        (binary / "START-HERE.html").read_text(encoding="utf-8"),
        version=__version__,
        injected=payload,
        packaged=True,
    )
    (binary / "START-HERE.html").write_text(injected, encoding="utf-8")
    (share / "index.html").write_text(injected, encoding="utf-8")
    (binary / "build-identity.json").write_bytes(identity.read_bytes())
    assert (share / "index.html").read_text(encoding="utf-8") == injected
    assert (binary / "START-HERE.html").read_text(encoding="utf-8") == injected
    assert json.loads((binary / "build-identity.json").read_text()) == payload
    assert SOURCE_STUB not in injected
    assert PRODUCTION_ID in injected


def test_desktop_help_shows_identity_fields_and_current_story():
    html = DESKTOP.read_text(encoding="utf-8")
    js = DESKTOP_JS.read_text(encoding="utf-8")
    for ident in (
        "identity-label",
        "identity-version",
        "identity-build-id",
        "identity-commit",
        "identity-status",
        "usb-build-ids",
    ):
        assert ident in html
    for ident in (
        "identity-label",
        "identity-version",
        "identity-build-id",
        "identity-commit",
        "identity-status",
    ):
        assert ident in js
    assert "identity_label" in js
    assert "build_id" in js
    assert "manufactured" in js
    assert "START-HERE.html" in html


def test_live_session_stub_is_honest_without_injection():
    assert this_usb_line() == "This session is not a manufactured USB image."
    text = version_report(build={"status": "unavailable", "build_id": ""})
    assert "Beamo Wipe" in text
    assert "This session is not a manufactured USB image." in text
    assert "source helper" not in text
    assert "Release build:" in text
    assert "Build status:" in text


def test_status_labels_match_build_identity():
    from beamo_wipe import build_identity as identity
    from beamo_wipe import compat_story as story

    assert story.STATUS_PRODUCTION == identity.STATUS_PRODUCTION
    assert story.STATUS_DEVELOPMENT == identity.STATUS_DEVELOPMENT
    assert story.STATUS_DIRTY == identity.STATUS_DIRTY
    assert story.STATUS_MISMATCH == identity.STATUS_MISMATCH
    assert story.STATUS_UNAVAILABLE == identity.STATUS_UNAVAILABLE


def test_support_sentence_uses_application_identity():
    assert sentence_from_application(None) == "This session is not a manufactured USB image."
    assert (
        sentence_from_application({"build_status": STATUS_PRODUCTION, "build": {"build_id": PRODUCTION_ID}})
        == LABEL_PRODUCTION
    )
    assert customer_label(STATUS_DEVELOPMENT, packaged=True) == (
        "This USB is a development image, not a manufactured release."
    )
    assert customer_label(STATUS_DIRTY, packaged=True).startswith("This USB was built from changed source")
    assert customer_label(STATUS_PRODUCTION, packaged=False) == SOURCE_STUB


def test_this_usb_card_precedes_the_startup_chooser():
    html = _html()
    assert html.index('id="this-usb"') < html.index('id="guide"')
    assert html.index('id="this-usb"') < html.index('aria-label="Startup problems"')
    assert html.index('id="guide"') < html.index('id="trouble-usb"')
    assert 'class="support-qr"' in html
    assert "BitLocker" in html
    assert "not the same on every PC" in html


def test_usb_story_strings_stay_on_the_swept_copy_surface():
    """Aliases like SECURE_BOOT_HINT = COMPAT_… drop off language sweep."""
    from beamo_wipe.compat_story import SECURE_BOOT_HINT as STORY_HINT
    from beamo_wipe.demo import discovery_for_scenario
    from beamo_wipe.inventory import count_summary
    from test_language_selection import _swept_surface

    keys = set(_swept_surface()["copy"])
    assert "WHAT_BULLETS" in keys
    assert "SECURE_BOOT_HINT" in keys
    assert PLATFORMS == WHAT_BULLETS[-1]
    assert STORY_HINT == SECURE_BOOT_HINT
    summary = count_summary(discovery_for_scenario("happy"))
    assert isinstance(summary, str) and summary.strip()


def test_what_screen_keeps_title_and_shows_this_usb_line():
    """this_usb_line is supporting copy, not a rewritten WHAT heading."""
    from gi.repository import Atk, Gtk

    from beamo_wipe import copy as C
    from beamo_wipe.models import Screen
    from beamo_wipe.ui.accessible_wizard import AccessibleWizard
    from test_accessible_runtime import drain, make_demo_wizard, text, widgets

    wizard = make_demo_wizard()
    wizard.screen = Screen.WHAT
    app = AccessibleWizard(wizard)
    try:
        drain()
        heading = app.window.get_focus()
        assert isinstance(heading, Gtk.Label)
        assert heading.get_text() == C.TITLE_WHAT
        shown = text(app)
        assert C.this_usb_line() in shown
        assert C.TITLE_WHAT in shown
        heading_names = [
            widget.get_accessible().get_name()
            for widget in widgets(app.window)
            if widget.get_accessible().get_role() == Atk.Role.HEADING
        ]
        assert C.this_usb_line() not in heading_names
        assert not any(
            (name or "").startswith(C.this_usb_line()) for name in heading_names
        )
    finally:
        app.close()
        drain()
