"""Regenerating the fake web preview must not overwrite linked source files."""

from pathlib import Path

import pytest

from beamo_wipe.gallery import write_gallery


@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_gallery_replaces_link_without_modifying_its_other_name(tmp_path: Path, link_kind: str):
    original = tmp_path / "keep.txt"
    original.write_text("owner data", encoding="utf-8")
    preview = tmp_path / "index.html"
    if link_kind == "symlink":
        preview.symlink_to(original)
    else:
        preview.hardlink_to(original)

    write_gallery(preview)

    assert original.read_text(encoding="utf-8") == "owner data"
    assert preview.is_file() and not preview.is_symlink()
    assert "PREVIEW" in preview.read_text(encoding="utf-8")
