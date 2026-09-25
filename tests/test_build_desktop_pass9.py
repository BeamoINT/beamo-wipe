"""Desktop source receipts cover every file that Go may compile or link."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "beamo_desktop_builder_pass9", ROOT / "scripts" / "build_desktop.py"
)
assert SPEC and SPEC.loader
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


@pytest.mark.parametrize("name", ["helper_amd64.s", "prebuilt.syso"])
def test_desktop_digest_changes_with_non_go_compiler_input(tmp_path, name):
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    (desktop / "go.mod").write_text("module fixture\n")
    (desktop / "main.go").write_text("package main\nfunc main() {}\n")
    extra = desktop / name
    extra.write_bytes(b"first build input")

    first = BUILDER.desktop_source_digest(tmp_path)
    extra.write_bytes(b"changed build input")

    assert BUILDER.desktop_source_digest(tmp_path) != first


def test_desktop_digest_refuses_special_compiler_input(tmp_path):
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    (desktop / "go.mod").write_text("module fixture\n")
    (desktop / "main.go").write_text("package main\nfunc main() {}\n")
    os.mkfifo(desktop / "blocked.go")

    with pytest.raises(RuntimeError, match="regular"):
        BUILDER.desktop_source_digest(tmp_path)


class _WindowsOSProxy:
    name = "nt"

    def __getattr__(self, name):
        return getattr(os, name)


def test_windows_build_rejects_swapped_output_with_hardlinked_lock(
    tmp_path, monkeypatch
):
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    (desktop / "go.mod").write_text("module fixture\n")
    (desktop / "main.go").write_text("package main\nfunc main() {}\n")
    output = tmp_path / "dist" / "desktop"
    archived = tmp_path / "original-output"

    def fake_output(argv, **_kwargs):
        if argv[1:] == ["version"]:
            return "go version go1.26.8 windows/amd64\n"
        if argv[1:] == ["rev-parse", "HEAD"]:
            return "a" * 40 + "\n"
        if argv[1:] == ["status", "--porcelain"]:
            return ""
        raise AssertionError(argv)

    build_calls = 0

    def fake_build(argv, **_kwargs):
        nonlocal build_calls
        build_calls += 1
        if build_calls == 1:
            output.rename(archived)
            output.mkdir()
            os.link(archived / ".build.lock", output / ".build.lock")
        Path(argv[argv.index("-o") + 1]).write_bytes(b"compiled launcher")

    monkeypatch.setattr(BUILDER, "ROOT", tmp_path)
    monkeypatch.setattr(BUILDER, "os", _WindowsOSProxy())
    monkeypatch.setattr(BUILDER.subprocess, "check_output", fake_output)
    monkeypatch.setattr(BUILDER.subprocess, "check_call", fake_build)

    with pytest.raises(RuntimeError, match="output changed|build lock changed"):
        BUILDER.build(output)
    assert not (output / "desktop-build.json").exists()
