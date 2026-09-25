"""A swapped output path cannot redirect launcher bytes outside the build."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "beamo_desktop_builder_pass16", ROOT / "scripts" / "build_desktop.py"
)
assert SPEC and SPEC.loader
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def test_builder_does_not_write_launcher_through_swapped_output(tmp_path, monkeypatch):
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    (desktop / "go.mod").write_text("module fixture\n")
    (desktop / "main.go").write_text("package main\n")
    output = tmp_path / "dist" / "desktop"
    foreign = tmp_path / "foreign"
    foreign.mkdir()

    def fake_output(argv, **_kwargs):
        if argv[1:] == ["version"]:
            return "go version go1.26.8 darwin/arm64\n"
        if argv[1:] == ["rev-parse", "HEAD"]:
            return "a" * 40 + "\n"
        if argv[1:] == ["status", "--porcelain"]:
            return ""
        raise AssertionError(argv)

    def fake_build(argv, **_kwargs):
        output.rename(tmp_path / "prior-desktop")
        output.symlink_to(foreign, target_is_directory=True)
        Path(argv[argv.index("-o") + 1]).write_bytes(b"foreign launcher")

    monkeypatch.setattr(BUILDER, "ROOT", tmp_path)
    monkeypatch.setattr(BUILDER.subprocess, "check_output", fake_output)
    monkeypatch.setattr(BUILDER.subprocess, "check_call", fake_build)
    with pytest.raises(RuntimeError, match="build lock changed"):
        BUILDER.build(output)
    assert list(foreign.iterdir()) == []


def test_failed_publish_preserves_replacement_of_temporary_launcher(
    tmp_path, monkeypatch
):
    output = tmp_path / "desktop"
    output.mkdir()
    source = tmp_path / "launcher"
    source.write_bytes(b"compiled launcher")
    output_fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY)
    replacement = None

    def replace_then_fail(*_args):
        nonlocal replacement
        temporary = next(output.glob(".launcher-*"))
        temporary.unlink()
        temporary.write_text("foreign file")
        replacement = temporary
        raise OSError("copy interrupted")

    monkeypatch.setattr(BUILDER.shutil, "copyfileobj", replace_then_fail)
    try:
        with pytest.raises(OSError, match="copy interrupted"):
            BUILDER._publish_launcher(
                output, output_fd, source, "Start Beamo Wipe Linux"
            )
    finally:
        os.close(output_fd)
    assert replacement is not None
    assert replacement.read_text() == "foreign file"


def test_path_fallback_replaces_launcher_link_without_writing_target(tmp_path):
    output = tmp_path / "desktop"
    output.mkdir()
    source = tmp_path / "compiled"
    source.write_bytes(b"compiled launcher")
    foreign = tmp_path / "foreign"
    foreign.write_bytes(b"foreign bytes")
    target = output / "Start Beamo Wipe Linux"
    target.symlink_to(foreign)
    BUILDER._publish_launcher(output, None, source, target.name)
    assert foreign.read_bytes() == b"foreign bytes"
    assert not target.is_symlink()
    assert target.read_bytes() == b"compiled launcher"


def test_builder_rechecks_published_launcher_bytes_before_manifest(
    tmp_path, monkeypatch
):
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    (desktop / "go.mod").write_text("module fixture\n")
    (desktop / "main.go").write_text("package main\n")
    output = tmp_path / "dist" / "desktop"

    def fake_output(argv, **_kwargs):
        if argv[1:] == ["version"]:
            return "go version go1.26.8 darwin/arm64\n"
        if argv[1:] == ["rev-parse", "HEAD"]:
            return "a" * 40 + "\n"
        if argv[1:] == ["status", "--porcelain"]:
            return ""
        raise AssertionError(argv)

    def fake_build(argv, **_kwargs):
        Path(argv[argv.index("-o") + 1]).write_bytes(b"compiled launcher")

    original_replace = os.replace

    def alter_before_replace(src, dest, **kwargs):
        if dest == "Start Beamo Wipe Linux":
            fd = os.open(src, os.O_WRONLY | os.O_TRUNC, dir_fd=kwargs["src_dir_fd"])
            with os.fdopen(fd, "wb") as stream:
                stream.write(b"foreign launcher")
        return original_replace(src, dest, **kwargs)

    monkeypatch.setattr(BUILDER, "ROOT", tmp_path)
    monkeypatch.setattr(BUILDER.subprocess, "check_output", fake_output)
    monkeypatch.setattr(BUILDER.subprocess, "check_call", fake_build)
    monkeypatch.setattr(BUILDER.os, "replace", alter_before_replace)
    with pytest.raises(RuntimeError, match="launcher bytes changed"):
        BUILDER.build(output)
    assert not (output / "desktop-build.json").exists()


def test_builder_does_not_report_success_after_manifest_output_swap(
    tmp_path, monkeypatch
):
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    (desktop / "go.mod").write_text("module fixture\n")
    (desktop / "main.go").write_text("package main\n")
    output = tmp_path / "dist" / "desktop"
    foreign = tmp_path / "foreign"
    foreign.mkdir()

    def fake_output(argv, **_kwargs):
        if argv[1:] == ["version"]:
            return "go version go1.26.8 darwin/arm64\n"
        if argv[1:] == ["rev-parse", "HEAD"]:
            return "a" * 40 + "\n"
        if argv[1:] == ["status", "--porcelain"]:
            return ""
        raise AssertionError(argv)

    def fake_build(argv, **_kwargs):
        Path(argv[argv.index("-o") + 1]).write_bytes(b"compiled launcher")

    original_fdopen = os.fdopen

    def swap_on_manifest(fd, mode="r", *args, **kwargs):
        if mode == "w" and kwargs.get("encoding") == "utf-8":
            output.rename(tmp_path / "prior-desktop")
            output.symlink_to(foreign, target_is_directory=True)
        return original_fdopen(fd, mode, *args, **kwargs)

    monkeypatch.setattr(BUILDER, "ROOT", tmp_path)
    monkeypatch.setattr(BUILDER.subprocess, "check_output", fake_output)
    monkeypatch.setattr(BUILDER.subprocess, "check_call", fake_build)
    monkeypatch.setattr(BUILDER.os, "fdopen", swap_on_manifest)
    with pytest.raises(RuntimeError, match="output changed before completion"):
        BUILDER.build(output)
    assert list(foreign.iterdir()) == []
    assert not (tmp_path / "prior-desktop" / "desktop-build.json").exists()
