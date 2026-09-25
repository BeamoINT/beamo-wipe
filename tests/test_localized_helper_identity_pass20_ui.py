"""Every language of the offline helper identifies the image being used."""

from pathlib import Path

import pytest

from beamo_wipe import __version__
from beamo_wipe.compat_story import inject_helper_html


HELPER = Path(__file__).resolve().parents[1] / "helper"
BUILD_ID = "12345678-1234-1234-1234-123456789abc"
COMMIT = "a" * 40
MARKERS = (
    "BEAMO_BUILD_LABEL",
    "BEAMO_VERSION",
    "BEAMO_BUILD_ID",
    "BEAMO_SOURCE_COMMIT",
    "BEAMO_BUILD_STATUS",
)


def _inside(page: str, marker: str) -> str:
    return page.split(f"<!--{marker}-->", 1)[1].split(f"<!--/{marker}-->", 1)[0]


@pytest.mark.parametrize(
    ("language", "build_id", "dirty", "expected_status", "label_fragment"),
    (
        ("fr", BUILD_ID, False, "production", "Cette clé USB est une image"),
        ("de", BUILD_ID, False, "Produktion", "Dieser USB-Stick enthält ein hergestelltes"),
        ("fr", "local", False, "développement", "pas une version de production"),
        ("de", "local", False, "Entwicklung", "keine Produktionsversion"),
        ("fr", BUILD_ID, True, "modifié", "code source modifié"),
        ("de", BUILD_ID, True, "geändert", "geändertem Quellcode"),
    ),
)
def test_localized_helper_identifies_this_packaged_image(
    language, build_id, dirty, expected_status, label_fragment
):
    source = (HELPER / f"{language}.html").read_text(encoding="utf-8")
    for marker in MARKERS:
        assert source.count(f"<!--{marker}-->") == 1
        assert source.count(f"<!--/{marker}-->") == 1
    result = inject_helper_html(
        source,
        version=__version__,
        injected={
            "build_id": build_id,
            "source_commit": COMMIT,
            "source_dirty": dirty,
            "source_sha256": "b" * 64,
        },
        packaged=True,
        language=language,
    )
    assert _inside(result, "BEAMO_BUILD_ID") == build_id
    assert _inside(result, "BEAMO_SOURCE_COMMIT") == COMMIT
    assert _inside(result, "BEAMO_VERSION") == __version__
    assert _inside(result, "BEAMO_BUILD_STATUS") == expected_status
    assert label_fragment in _inside(result, "BEAMO_BUILD_LABEL")
    assert "This USB is a manufactured Beamo Wipe image." not in result
