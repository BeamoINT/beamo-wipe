"""Native Windows launcher builds reject redirected output parents."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "beamo_desktop_builder_windows_parent", ROOT / "scripts" / "build_desktop.py"
)
assert SPEC and SPEC.loader
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


class WindowsOSProxy:
    name = "nt"

    def __getattr__(self, name):
        return getattr(os, name)


def test_windows_output_creates_ordinary_components(tmp_path, monkeypatch):
    output = tmp_path / "dist" / "desktop"
    monkeypatch.setattr(BUILDER, "os", WindowsOSProxy())
    assert BUILDER._require_output_directory(output, create=True) is None
    assert BUILDER._require_output_directory(output) is None
    assert output.is_dir()


def test_windows_output_rejects_linked_parent_before_creating_child(
    tmp_path, monkeypatch
):
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    linked_parent = tmp_path / "dist"
    linked_parent.symlink_to(foreign, target_is_directory=True)
    output = linked_parent / "desktop"

    monkeypatch.setattr(BUILDER, "os", WindowsOSProxy())
    with pytest.raises(RuntimeError, match="unsafe desktop output directory"):
        BUILDER._require_output_directory(output, create=True)

    assert list(foreign.iterdir()) == []


def test_windows_output_rejects_junction_attribute(tmp_path, monkeypatch):
    output = tmp_path / "dist" / "desktop"
    output.mkdir(parents=True)
    original_lstat = type(output).lstat

    def junction_lstat(path):
        info = original_lstat(path)
        if path == output.parent:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info

    monkeypatch.setattr(BUILDER, "os", WindowsOSProxy())
    monkeypatch.setattr(type(output), "lstat", junction_lstat)
    with pytest.raises(RuntimeError, match="unsafe desktop output directory"):
        BUILDER._require_output_directory(output)
