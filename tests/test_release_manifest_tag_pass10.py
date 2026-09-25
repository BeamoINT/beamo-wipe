"""A manifest must identify its version tag when a commit has several tags."""

import pytest

from beamo_wipe import release_manifest as rm


def test_manifest_tag_prefers_its_release_version(monkeypatch):
    monkeypatch.setattr(rm, "_run", lambda *_args, **_kw: "v0.2.8\nv0.2.9")
    assert rm.git_tag_for_commit("a" * 40) == "v0.2.9"


@pytest.mark.parametrize("kind", ["file", "directory", "parent_directory"])
def test_live_build_inputs_reject_linked_config_entry(tmp_path, monkeypatch, kind):
    source = tmp_path / "src" / "beamo_wipe"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text("# fixture\n")
    config = tmp_path / "packaging" / "live" / "config"
    config.mkdir(parents=True)
    outside = tmp_path / "external"
    if kind == "file":
        outside.write_text("outside input\n")
        linked = config / "package-lists" / "beamo.list.chroot"
        linked.parent.mkdir()
    elif kind == "directory":
        outside.mkdir()
        (outside / "external.txt").write_text("outside input\n")
        linked = config / "apt"
    else:
        outside.mkdir()
        (outside / "beamo.list.chroot").write_text("outside input\n")
        linked = config / "package-lists"
    linked.symlink_to(outside)
    monkeypatch.setattr(rm, "ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="symlink"):
        rm.live_build_inputs()
