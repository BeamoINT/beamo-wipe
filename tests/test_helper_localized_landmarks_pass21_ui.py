# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline helper languages keep named troubleshooting landmarks."""

from html.parser import HTMLParser
from pathlib import Path

import pytest


HELPER = Path(__file__).resolve().parents[1] / "helper"
BRANCHES = ("trouble-usb", "trouble-key", "trouble-firmware", "trouble-launcher")


class _Landmarks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.articles = {}
        self.links = []

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if "id" in data:
            self.ids.add(data["id"])
        if tag == "article" and "id" in data:
            self.articles[data["id"]] = data.get("aria-labelledby")
        if tag == "a" and "href" in data:
            self.links.append(data["href"])


@pytest.mark.parametrize("language", ("en", "fr", "de"))
def test_helper_troubleshooting_articles_have_heading_names(language):
    filename = "index.html" if language == "en" else f"{language}.html"
    html = (HELPER / filename).read_text(encoding="utf-8")
    page = _Landmarks()
    page.feed(html)

    assert "secure-boot" in page.ids
    assert "#secure-boot" in page.links
    for branch in BRANCHES:
        label_id = f"{branch}-title"
        assert page.articles[branch] == label_id
        assert label_id in page.ids
