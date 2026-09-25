"""A desktop source swapped after validation must not be hashed through a link."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "beamo_desktop_builder_pass36", ROOT / "scripts/build_desktop.py"
)
assert SPEC and SPEC.loader
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def test_desktop_digest_rejects_source_swapped_to_link(tmp_path, monkeypatch):
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    (desktop / "go.mod").write_text("module fixture\n")
    main = desktop / "main.go"
    main.write_text("package main\nfunc main() {}\n")
    outside = tmp_path / "outside.go"
    outside.write_text("package main\nfunc main() { panic(\"outside\") }\n")

    original_is_symlink = Path.is_symlink
    swapped = False

    def swap_after_check(path):
        nonlocal swapped
        result = original_is_symlink(path)
        if path == main and not swapped:
            main.rename(desktop / "original.go")
            main.symlink_to(outside)
            swapped = True
        return result

    monkeypatch.setattr(Path, "is_symlink", swap_after_check)
    with pytest.raises(RuntimeError, match="source input.*changed|source input.*unsafe"):
        BUILDER.desktop_source_digest(tmp_path)
    assert swapped


def test_builder_compiles_from_verified_private_source_copy(tmp_path, monkeypatch):
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    (desktop / "go.mod").write_text("module fixture\n")
    main = desktop / "main.go"
    original = b"package main\nfunc main() {}\n"
    main.write_bytes(original)
    output = tmp_path / "dist/desktop"

    def fake_output(argv, **_kwargs):
        if argv[1:] == ["version"]:
            return "go version go1.26.8 linux/amd64\n"
        if argv[1:] == ["rev-parse", "HEAD"]:
            return "a" * 40 + "\n"
        if argv[1:] == ["status", "--porcelain"]:
            return ""
        raise AssertionError(argv)

    builds = []

    def fake_build(argv, **kwargs):
        if not builds:
            main.write_bytes(b"package main\nfunc main() { panic(\"outside\") }\n")
        compiled = (Path(kwargs["cwd"]) / "main.go").read_bytes()
        main.write_bytes(original)
        Path(argv[argv.index("-o") + 1]).write_bytes(compiled)
        builds.append(compiled)

    monkeypatch.setattr(BUILDER, "ROOT", tmp_path)
    monkeypatch.setattr(BUILDER.subprocess, "check_output", fake_output)
    monkeypatch.setattr(BUILDER.subprocess, "check_call", fake_build)
    BUILDER.build(output)

    assert builds == [original, original]
    assert all((output / name).read_bytes() == original for name in BUILDER.LAUNCHERS)
    assert json.loads((output / "desktop-build.json").read_text())["source_sha256"] == BUILDER.desktop_source_digest(tmp_path)
