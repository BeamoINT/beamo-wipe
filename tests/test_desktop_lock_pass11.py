"""A desktop build may remove only the lock inode it created."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "beamo_desktop_builder_pass11", ROOT / "scripts" / "build_desktop.py"
)
assert SPEC and SPEC.loader
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


@pytest.mark.parametrize("replace_lock", [False, True])
def test_builder_owns_lock_through_publication(tmp_path, monkeypatch, replace_lock):
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    (desktop / "go.mod").write_text("module fixture\n")
    (desktop / "main.go").write_text("package main\n")
    output = tmp_path / "dist" / "desktop"
    lock = output / ".build.lock"
    calls = 0

    def fake_output(argv, **_kwargs):
        if argv[1:] == ["version"]:
            return "go version go1.26.8 darwin/arm64\n"
        if argv[1:] == ["rev-parse", "HEAD"]:
            return "a" * 40 + "\n"
        if argv[1:] == ["status", "--porcelain"]:
            return ""
        raise AssertionError(argv)

    def fake_build(argv, **_kwargs):
        nonlocal calls
        calls += 1
        Path(argv[argv.index("-o") + 1]).write_bytes(f"launcher-{calls}".encode())
        if calls == 1 and replace_lock:
            lock.unlink()
            lock.write_text("foreign build lock")

    monkeypatch.setattr(BUILDER, "ROOT", tmp_path)
    monkeypatch.setattr(BUILDER.subprocess, "check_output", fake_output)
    monkeypatch.setattr(BUILDER.subprocess, "check_call", fake_build)
    if replace_lock:
        with pytest.raises(RuntimeError, match="build lock changed"):
            BUILDER.build(output)
        assert lock.read_text() == "foreign build lock"
        assert not (output / "desktop-build.json").exists()
    else:
        BUILDER.build(output)
        assert not lock.exists()
        assert (output / "desktop-build.json").is_file()


def test_builder_rejects_manifest_path_inserted_during_build(tmp_path, monkeypatch):
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    (desktop / "go.mod").write_text("module fixture\n")
    (desktop / "main.go").write_text("package main\n")
    output = tmp_path / "dist" / "desktop"
    foreign = tmp_path / "foreign.json"
    foreign.write_text("foreign receipt\n")
    calls = 0

    def fake_output(argv, **_kwargs):
        if argv[1:] == ["version"]:
            return "go version go1.26.8 darwin/arm64\n"
        if argv[1:] == ["rev-parse", "HEAD"]:
            return "a" * 40 + "\n"
        if argv[1:] == ["status", "--porcelain"]:
            return ""
        raise AssertionError(argv)

    def fake_build(argv, **_kwargs):
        nonlocal calls
        calls += 1
        Path(argv[argv.index("-o") + 1]).write_bytes(f"launcher-{calls}".encode())
        if calls == 2:
            (output / "desktop-build.json").symlink_to(foreign)

    monkeypatch.setattr(BUILDER, "ROOT", tmp_path)
    monkeypatch.setattr(BUILDER.subprocess, "check_output", fake_output)
    monkeypatch.setattr(BUILDER.subprocess, "check_call", fake_build)
    with pytest.raises(RuntimeError, match="manifest path"):
        BUILDER.build(output)
    assert foreign.read_text() == "foreign receipt\n"


@pytest.mark.parametrize("link_parent", [False, True])
def test_builder_rejects_linked_output_directory(tmp_path, monkeypatch, link_parent):
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    (desktop / "go.mod").write_text("module fixture\n")
    (desktop / "main.go").write_text("package main\n")
    output = tmp_path / "dist" / "desktop"
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    if link_parent:
        output.parent.symlink_to(foreign, target_is_directory=True)
    else:
        output.parent.mkdir()
        output.symlink_to(foreign, target_is_directory=True)

    def fake_output(argv, **_kwargs):
        if argv[1:] == ["version"]:
            return "go version go1.26.8 darwin/arm64\n"
        if argv[1:] == ["rev-parse", "HEAD"]:
            return "a" * 40 + "\n"
        if argv[1:] == ["status", "--porcelain"]:
            return ""
        raise AssertionError(argv)

    def fake_build(argv, **_kwargs):
        Path(argv[argv.index("-o") + 1]).write_bytes(b"launcher")

    monkeypatch.setattr(BUILDER, "ROOT", tmp_path)
    monkeypatch.setattr(BUILDER.subprocess, "check_output", fake_output)
    monkeypatch.setattr(BUILDER.subprocess, "check_call", fake_build)
    with pytest.raises(RuntimeError, match="output directory"):
        BUILDER.build(output)
    assert list(foreign.iterdir()) == []
