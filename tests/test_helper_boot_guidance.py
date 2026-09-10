# SPDX-License-Identifier: GPL-3.0-or-later
"""Helper boot guidance: Win10/Win11 split, BitLocker warning, offline packaging.

Fake devices only. Live Microsoft URLs are read-only link checks.
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "helper" / "index.html"
START_HERE = ROOT / "packaging/live/config/includes.binary/START-HERE.html"
DESKTOP = ROOT / "desktop/web/index.html"
BUILD_ISO = ROOT / "scripts" / "build-iso.sh"

MICROSOFT_SOURCES = (
    "https://support.microsoft.com/en-us/windows/experience/backup-recovery/windows-recovery-environment",
    "https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/windows-recovery-environment--windows-re--technical-reference?view=windows-11",
    "https://learn.microsoft.com/en-us/windows/security/operating-system-security/data-protection/bitlocker/recovery-overview",
    "https://support.microsoft.com/en-us/windows/security/encryption/find-your-bitlocker-recovery-key",
)

FORBIDDEN = (
    "disable secure boot",
    "turn off secure boot",
    "turn off bitlocker",
    "disable bitlocker",
    "works on any computer",
    "works on every pc",
    "plug and play",
    "impossible to recover",
)


class _Doc(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.headings: list[tuple[int, str]] = []
        self.links: list[str] = []
        self.ids: list[str] = []
        self.external_assets: list[str] = []
        self._capture: list[str] | None = None
        self.skip = False
        self.has_main = False
        self.focus_visible = False

    def handle_starttag(self, tag, attrs):
        names = dict(attrs)
        if tag in {"h1", "h2", "h3"}:
            self._capture = []
        if tag == "a" and names.get("href"):
            self.links.append(names["href"])
        if tag == "main" and names.get("id") == "main":
            self.has_main = True
        if names.get("id"):
            self.ids.append(names["id"])
        if tag in {"link", "script"}:
            src = names.get("href") or names.get("src") or ""
            if src and not src.startswith("data:"):
                self.external_assets.append(src)
        if tag == "a" and "skip" in names.get("class", "").split():
            self.skip = names.get("href") == "#main"

    def handle_data(self, data):
        if self._capture is not None:
            self._capture.append(data)

    def handle_endtag(self, tag):
        if tag in {"h1", "h2", "h3"} and self._capture is not None:
            self.headings.append((int(tag[1]), "".join(self._capture).strip()))
            self._capture = None


def _html() -> str:
    return HELPER.read_text(encoding="utf-8")


def _parse() -> _Doc:
    doc = _Doc()
    raw = _html()
    doc.focus_visible = "a:focus-visible" in raw
    doc.feed(raw)
    return doc


def test_helper_and_iso_start_here_are_identical():
    assert HELPER.read_bytes() == START_HERE.read_bytes()
    script = BUILD_ISO.read_text(encoding="utf-8")
    assert 'cp "$ROOT/helper/index.html" "$STAGE_BIN/START-HERE.html"' in script
    assert 'cp "$ROOT/helper/index.html" "$STAGE_SHARE/helper/index.html"' in script


def test_helper_is_self_contained_for_offline_usb():
    doc = _parse()
    assert doc.external_assets == []
    text = _html()
    assert "<link rel=\"stylesheet\"" not in text
    assert "<script" not in text
    assert "Windows 11: start this USB from Settings" in text
    assert "Windows 10: start this USB from Settings" in text
    assert "Settings → System → Recovery" in text
    assert "Settings → Update &amp; Security → Recovery" in text
    assert "Use a device" in text
    assert "48-digit recovery key" in text


def test_windows_10_and_11_sections_are_separate():
    headings = [title for _level, title in _parse().headings]
    assert headings.index("Windows 11: start this USB from Settings") < headings.index(
        "Windows 10: start this USB from Settings"
    )
    ids = _parse().ids
    assert "windows-11" in ids and "windows-10" in ids and "bitlocker" in ids
    win11 = _html().split('id="windows-11"', 1)[1].split('id="windows-10"', 1)[0]
    win10 = _html().split('id="windows-10"', 1)[1].split('id="fallbacks"', 1)[0]
    assert "System → Recovery" in win11
    assert "Update &amp; Security" not in win11
    assert "Update &amp; Security → Recovery" in win10
    assert "System → Recovery" not in win10
    assert "UEFI" in win11 and "UEFI" in win10


def test_bitlocker_warning_precedes_firmware_advice():
    text = _html()
    bit = text.index('id="bitlocker"')
    firmware_later = text.index("firmware, boot-order, or Secure Boot")
    assert bit < firmware_later
    assert bit < text.index("If the computer says Secure Boot")
    lower = text.lower()
    assert "before" in lower
    assert "microsoft support cannot retrieve" in lower
    assert "does not turn bitlocker off" in lower
    for phrase in FORBIDDEN:
        assert phrase not in lower, phrase


def test_oem_variation_and_safe_fallbacks_are_documented():
    text = _html()
    assert "not the same on every PC" in text
    assert "Examples only" in text
    assert "Shift" in text
    assert "another direct USB port" in text or "another USB port" in text
    assert "manufacturer" in text.lower()
    assert "legacy BIOS" in text


def test_keyboard_and_small_display_structure():
    doc = _parse()
    assert doc.skip
    assert doc.has_main
    assert doc.focus_visible
    html = _html()
    assert "Skip to instructions" in html
    assert "@media (max-width: 600px)" in html
    assert "overflow-x: auto" in html
    assert 'scope="col"' in html
    assert "<caption>" in html
    levels = [level for level, _title in doc.headings]
    assert levels == sorted(levels)


def test_desktop_help_matches_helper_paths():
    text = DESKTOP.read_text(encoding="utf-8")
    assert "Windows 11: Settings → System → Recovery" in text
    assert "Windows 10: Settings → Update &amp; Security → Recovery" in text
    assert "BitLocker recovery key" in text
    assert "does not change Secure Boot or BitLocker" in text
    assert "START-HERE.html" in text
    lower = text.lower()
    for phrase in FORBIDDEN:
        assert phrase not in lower, phrase


@pytest.mark.parametrize("url", MICROSOFT_SOURCES)
def test_cited_microsoft_sources_are_current(url):
    request = urllib.request.Request(url, headers={"User-Agent": "BeamoWipeHelperCheck/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            status = getattr(response, "status", 200)
            final = response.geturl()
            body = response.read(4000).decode("utf-8", "replace").lower()
    except urllib.error.HTTPError as exc:
        pytest.fail(f"stale or unreachable Microsoft source {url}: {exc.code}")
    except urllib.error.URLError as exc:
        pytest.skip(f"network unavailable for {url}: {exc.reason}")
    assert status < 400
    assert "microsoft" in final.lower() or "learn.microsoft.com" in final.lower() or "support.microsoft.com" in final.lower()
    if "bitlocker" in url:
        assert "recovery" in body
    if "windows-recovery-environment" in url or "windows-re" in url:
        assert "recovery" in body


def test_helper_cites_the_verified_microsoft_sources():
    text = _html()
    for url in MICROSOFT_SOURCES:
        assert url in text
    doc = _parse()
    hrefs = [link for link in doc.links if link.startswith("http")]
    allowed = {
        "https://github.com/BeamoINT/beamo-wipe",
        *MICROSOFT_SOURCES,
    }
    assert set(hrefs) <= allowed


def _chrome() -> str | None:
    mac = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if mac.is_file():
        return str(mac)
    return shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")


def test_helper_renders_both_windows_paths_on_small_and_desktop_displays():
    chrome = _chrome()
    if not chrome:
        pytest.skip("Chrome is not installed for helper pixel checks")
    html = HELPER.resolve().as_uri()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for width, height, name in ((360, 900, "small"), (1280, 900, "desktop")):
            shot = tmp_path / f"{name}.png"
            dump = subprocess.check_output(
                [
                    chrome,
                    "--headless=new",
                    "--disable-gpu",
                    "--hide-scrollbars",
                    f"--window-size={width},{height}",
                    f"--screenshot={shot}",
                    "--virtual-time-budget=2000",
                    "--dump-dom",
                    html,
                ],
                stderr=subprocess.STDOUT,
                timeout=40,
            )
            dom = dump.decode("utf-8", "replace")
            assert "Windows 11: start this USB from Settings" in dom
            assert "Windows 10: start this USB from Settings" in dom
            assert "BitLocker recovery key" in dom
            assert "Skip to instructions" in dom
            assert shot.is_file() and shot.stat().st_size > 2000
