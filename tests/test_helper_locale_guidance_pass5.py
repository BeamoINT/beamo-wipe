# SPDX-License-Identifier: GPL-3.0-or-later
"""Language switches must retain the offline troubleshooting routes."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

import pytest


HELPER = Path(__file__).resolve().parents[1] / "helper"
BRANCHES = ("trouble-usb", "trouble-key", "trouble-firmware", "trouble-launcher")


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.links = []
        self.duplicate_ids = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            if attrs["id"] in self.ids:
                self.duplicate_ids.append(attrs["id"])
            self.ids.add(attrs["id"])
        if tag == "a" and "href" in attrs:
            self.links.append(attrs["href"])


@pytest.mark.parametrize("language", ("en", "fr", "de"))
def test_localized_helper_retains_each_offline_troubleshooting_route(language):
    name = "index.html" if language == "en" else f"{language}.html"
    html = (HELPER / name).read_text(encoding="utf-8")
    page = _Links()
    page.feed(html)
    assert not page.duplicate_ids
    assert all(link[1:] in page.ids for link in page.links if link.startswith("#"))
    assert "guide" in page.ids
    for branch in BRANCHES:
        assert branch in page.ids, branch
        assert f"#{branch}" in page.links, branch
    assert "#bitlocker" in page.links
    assert "#keys" in page.links
    assert "<script" not in html
