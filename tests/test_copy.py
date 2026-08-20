# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path

from beamo_wipe import copy

FORBIDDEN = (
    "plug and play",
    "no technical skills",
    "military certified",
    "dod certified",
    "nsa certified",
    "blancco replacement",
    "impossible to recover",
    "we invented",
    "works on any computer",
    "works on any mac",
    "apple silicon",
)

ALLOWED_APPLE_SILICON_CONTEXT = "Not Apple Silicon"


def _read(rel: str) -> str:
    return (Path(__file__).resolve().parents[1] / rel).read_text(encoding="utf-8").lower()


def test_copy_module_has_no_forbidden_claims():
    blob = " ".join(
        [
            copy.SPLASH_TAGLINE,
            " ".join(copy.WHAT_BULLETS),
            copy.ENGINE_LINE,
            copy.DONE_OK,
            copy.DONE_FAIL,
            copy.DONE_OK_PREVIEW,
            copy.DONE_FAIL_PREVIEW,
            copy.PREVIEW_BANNER,
            copy.SAME_SIZE_HINT,
            copy.NOT_LIVE_ERROR,
            " ".join(card["blurb"] + " " + card["pace"] for card in copy.METHOD_CARDS.values()),
        ]
    ).lower()
    for phrase in FORBIDDEN:
        if phrase == "apple silicon":
            continue
        assert phrase not in blob
    assert "not apple silicon" in blob


def test_claims_doc_forbids_bad_bullets():
    text = _read("docs/claims.md")
    assert "plug and play" in text  # listed as forbidden, not as a claim
    assert "not for apple silicon" in text or "not apple silicon" in text
    assert "guided" in text
    assert "nwipe" in text
