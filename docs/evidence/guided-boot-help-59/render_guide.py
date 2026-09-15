#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless Chrome shots of the offline helper and desktop help. Fake UI only."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
HELPER = ROOT / "helper" / "index.html"
DESKTOP_WEB = ROOT / "desktop" / "web"


def chrome() -> str:
    mac = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if mac.is_file():
        return str(mac)
    found = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
    if not found:
        raise SystemExit("Chrome is not installed")
    return found


def shot(bin_path: str, url: str, dest: Path, width: int, height: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        raw = tmp_path / "page.png"
        argv = [
            bin_path,
            "--headless=new",
            f"--user-data-dir={tmp_path / 'profile'}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-extensions",
            "--disable-sync",
            "--use-mock-keychain",
            "--password-store=basic",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            f"--window-size={width},{height}",
            f"--screenshot={raw}",
            "--timeout=10000",
            url,
        ]
        with (tmp_path / "log.txt").open("w+b") as output:
            proc = subprocess.Popen(argv, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                deadline = time.monotonic() + 40
                while time.monotonic() < deadline:
                    log = (tmp_path / "log.txt").read_text(errors="replace")
                    code = proc.poll()
                    if code is not None:
                        if code != 0:
                            raise SystemExit(f"chrome failed {url}: {log}")
                        break
                    if raw.is_file() and raw.stat().st_size > 2000 and "bytes written" in log:
                        break
                    time.sleep(0.1)
                else:
                    raise SystemExit(f"chrome timed out {url}: {(tmp_path / 'log.txt').read_text(errors='replace')}")
            finally:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=3)
        shutil.copyfile(raw, dest)
        print(dest.name, dest.stat().st_size)


def main() -> None:
    bin_path = chrome()
    helper = HELPER.resolve().as_uri()
    shot(bin_path, helper, OUT / "helper-360.png", 360, 900)
    shot(bin_path, helper, OUT / "helper-1280.png", 1280, 900)
    source = HELPER.read_text(encoding="utf-8")
    for name in ("trouble-usb", "trouble-key", "trouble-firmware", "trouble-launcher"):
        marked = source.replace(
            f'id="{name}"',
            f'id="{name}" data-evidence="open"',
            1,
        )
        extra = (
            "<style>.guide-hint{display:none !important}"
            ".guide .panel{display:none !important}"
            f'.guide .panel[id="{name}"]{{display:block !important}}</style></head>'
        )
        marked = marked.replace("</head>", extra, 1)
        tmp_html = OUT / f"_{name}.html"
        tmp_html.write_text(marked, encoding="utf-8")
        shot(bin_path, tmp_html.resolve().as_uri(), OUT / f"helper-360-{name}.png", 360, 1400)
        tmp_html.unlink()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        html = (DESKTOP_WEB / "index.html").read_text(encoding="utf-8")
        html = html.replace('<details id="help">', '<details id="help" open>')
        html = html.replace('href="/style.css"', 'href="style.css"')
        html = html.replace('src="/app.js"', 'src="app.js"')
        (tmp_path / "index.html").write_text(html, encoding="utf-8")
        shutil.copyfile(DESKTOP_WEB / "style.css", tmp_path / "style.css")
        shutil.copyfile(DESKTOP_WEB / "app.js", tmp_path / "app.js")
        uri = (tmp_path / "index.html").resolve().as_uri()
        shot(bin_path, uri, OUT / "desktop-help-360.png", 360, 900)
        shot(bin_path, uri, OUT / "desktop-help-1024.png", 1024, 900)
        firmware = html.replace(
            'id="trouble-firmware"',
            'id="trouble-firmware" data-evidence="open"',
            1,
        )
        firmware = firmware.replace(
            "</head>",
            "<style>.guide-hint{display:none !important}"
            ".guide .panel{display:none !important}"
            '.guide .panel[id="trouble-firmware"]{display:block !important}</style></head>',
            1,
        )
        (tmp_path / "firmware.html").write_text(firmware, encoding="utf-8")
        shot(
            bin_path,
            (tmp_path / "firmware.html").resolve().as_uri(),
            OUT / "desktop-help-360-firmware.png",
            360,
            1400,
        )


if __name__ == "__main__":
    main()
