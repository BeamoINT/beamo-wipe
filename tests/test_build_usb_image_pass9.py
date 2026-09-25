"""USB-image output stays inside the selected repository directory."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_builder_refuses_linked_dist_directory_before_assembly(tmp_path):
    project = tmp_path / "project"
    script = project / "scripts/build-usb-image.sh"
    script.parent.mkdir(parents=True)
    source = (ROOT / "scripts/build-usb-image.sh").read_text()
    platform_check = (
        '[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 && ! -d /Users/HP ]] || {\n'
        "  echo 'USB image builds require an isolated amd64 Linux worker.' >&2; exit 2;\n"
        "}\n"
    )
    assert platform_check in source
    # End after preflight so this test cannot allocate an image or call FAT tools.
    script.write_text(source.split("TMP_IMAGE=", 1)[0].replace(platform_check, ""))
    package = project / "src/beamo_wipe"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("__version__ = '0.2.9'\n")
    (package / "release_manifest.py").write_text(
        "def verify_build_manifest(*args, **kwargs):\n    return None\n"
    )
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (project / "dist").symlink_to(foreign, target_is_directory=True)
    (foreign / "beamo-wipe-0.2.9-amd64.iso").write_bytes(b"fixture ISO")

    result = subprocess.run(
        ["bash", str(script)],
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(project / "src")},
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 2
    assert "regular output directory" in result.stderr


def test_cleanup_does_not_treat_replaced_stage_link_as_ownership(tmp_path):
    source = (ROOT / "scripts/build-usb-image.sh").read_text()
    function = (
        "remove_owned_link() {"
        + source.split("remove_owned_link() {", 1)[1].split("\n}\ncleanup()", 1)[0]
        + "\n}"
    )
    published = tmp_path / "published.img"
    published.write_bytes(b"another writer's image")
    staged = tmp_path / "staged.img"
    staged.symlink_to(published)

    result = subprocess.run(
        [
            "bash",
            "-c",
            function + '\nremove_owned_link "$1" "$2"',
            "bash",
            str(staged),
            str(published),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert published.read_bytes() == b"another writer's image"
