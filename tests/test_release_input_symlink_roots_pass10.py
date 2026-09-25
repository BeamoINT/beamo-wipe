"""Release provenance must not hash inputs outside the checkout."""

import pytest

from beamo_wipe import release_manifest as rm


@pytest.mark.parametrize("linked_input", ["src", "package", "desktop", "helper"])
def test_live_build_inputs_reject_symlinked_input_roots(
    tmp_path, monkeypatch, linked_input
):
    root = tmp_path / "checkout"
    (root / "packaging/live/config").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()

    if linked_input == "src":
        (outside / "beamo_wipe").mkdir()
        (outside / "beamo_wipe/__init__.py").write_text("# outside\n")
        (root / "src").symlink_to(outside, target_is_directory=True)
    else:
        (root / "src/beamo_wipe").mkdir(parents=True)
        (root / "src/beamo_wipe/__init__.py").write_text("# inside\n")
    if linked_input == "package":
        (outside / "__init__.py").write_text("# outside\n")
        (root / "src/beamo_wipe/__init__.py").unlink()
        (root / "src/beamo_wipe").rmdir()
        (root / "src/beamo_wipe").symlink_to(outside, target_is_directory=True)
    if linked_input == "desktop":
        (outside / "main.go").write_text("package main\n")
        (root / "desktop").symlink_to(outside, target_is_directory=True)
    else:
        (root / "desktop").mkdir()
    if linked_input == "helper":
        (outside / "index.html").write_text("outside helper\n")
        (root / "helper").symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(rm, "ROOT", root)
    with pytest.raises(RuntimeError, match="symlink"):
        rm.live_build_inputs()
