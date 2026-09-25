"""A launcher rebuild must not replace files its prior receipt cannot identify."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "beamo_desktop_builder_pass22", ROOT / "scripts/build_desktop.py"
)
assert SPEC and SPEC.loader
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def test_builder_preserves_launcher_changed_since_prior_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    (desktop / "go.mod").write_text("module fixture\n")
    (desktop / "main.go").write_text("package main\nfunc main() {}\n")
    output = tmp_path / "dist/desktop"
    output.mkdir(parents=True)
    prior = output / "desktop-build.json"
    prior.write_text(
        json.dumps(
            {
                "version": "0.2.9",
                "source_commit": "a" * 40,
                "source_sha256": "b" * 64,
                "source_dirty": False,
                "go": BUILDER.GO_VERSION,
                "files": {name: "c" * 64 for name in BUILDER.LAUNCHERS},
            }
        )
    )
    launcher = output / BUILDER.LAUNCHERS[0]
    launcher.write_bytes(b"user replacement")
    other = output / BUILDER.LAUNCHERS[1]
    other.write_bytes(b"another user replacement")

    def fake_output(argv, **_kwargs):
        if argv[1:] == ["version"]:
            return "go version go1.26.8 darwin/arm64\n"
        if argv[1:] == ["rev-parse", "HEAD"]:
            return "a" * 40 + "\n"
        if argv[1:] == ["status", "--porcelain"]:
            return ""
        raise AssertionError(argv)

    build_calls = []

    def fake_build(argv, **_kwargs):
        build_calls.append(argv)
        Path(argv[argv.index("-o") + 1]).write_bytes(b"compiled launcher")

    monkeypatch.setattr(BUILDER, "ROOT", tmp_path)
    monkeypatch.setattr(BUILDER.subprocess, "check_output", fake_output)
    monkeypatch.setattr(BUILDER.subprocess, "check_call", fake_build)

    with pytest.raises(RuntimeError, match="unrecognized desktop manifest"):
        BUILDER.build(output)
    assert not build_calls
    assert launcher.read_bytes() == b"user replacement"
    assert other.read_bytes() == b"another user replacement"
    assert prior.is_file()


def test_builder_preserves_launcher_without_prior_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    (desktop / "go.mod").write_text("module fixture\n")
    (desktop / "main.go").write_text("package main\nfunc main() {}\n")
    output = tmp_path / "dist/desktop"
    output.mkdir(parents=True)
    launcher = output / BUILDER.LAUNCHERS[0]
    launcher.write_bytes(b"unidentified launcher bytes")

    def fake_output(argv, **_kwargs):
        if argv[1:] == ["version"]:
            return "go version go1.26.8 darwin/arm64\n"
        if argv[1:] == ["rev-parse", "HEAD"]:
            return "a" * 40 + "\n"
        if argv[1:] == ["status", "--porcelain"]:
            return ""
        raise AssertionError(argv)

    build_calls = []

    def fake_build(argv, **_kwargs):
        build_calls.append(argv)
        Path(argv[argv.index("-o") + 1]).write_bytes(b"compiled launcher")

    monkeypatch.setattr(BUILDER, "ROOT", tmp_path)
    monkeypatch.setattr(BUILDER.subprocess, "check_output", fake_output)
    monkeypatch.setattr(BUILDER.subprocess, "check_call", fake_build)

    with pytest.raises(RuntimeError, match="unrecognized desktop launcher"):
        BUILDER.build(output)
    assert not build_calls
    assert launcher.read_bytes() == b"unidentified launcher bytes"
    assert not (output / "desktop-build.json").exists()
