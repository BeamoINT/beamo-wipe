"""Preview generation must not follow a linked output directory."""

from pathlib import Path

import pytest

from beamo_wipe.gallery import write_gallery


@pytest.mark.parametrize("nested", [False, True])
def test_gallery_rejects_symlinked_output_directory(tmp_path: Path, nested: bool):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "web-preview"
    link.symlink_to(outside, target_is_directory=True)

    destination = link / "new-child" / "index.html" if nested else link / "index.html"
    with pytest.raises(OSError):
        write_gallery(destination)

    assert list(outside.iterdir()) == []
