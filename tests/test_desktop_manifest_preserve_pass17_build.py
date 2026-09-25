"""A launcher rebuild must not erase unrelated output called desktop-build.json."""

from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "beamo_desktop_builder_pass17", ROOT / "scripts/build_desktop.py"
)
assert SPEC and SPEC.loader
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def test_builder_preserves_unrecognized_existing_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    (desktop / "go.mod").write_text("module fixture\n")
    (desktop / "main.go").write_text("package main\nfunc main() {}\n")
    output = tmp_path / "dist/desktop"
    output.mkdir(parents=True)
    prior = output / "desktop-build.json"
    prior.write_text("This is unrelated user work.\n")

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

    monkeypatch.setattr(BUILDER, "ROOT", tmp_path)
    monkeypatch.setattr(BUILDER.subprocess, "check_output", fake_output)
    monkeypatch.setattr(BUILDER.subprocess, "check_call", fake_build)
    with pytest.raises(RuntimeError, match="unrecognized desktop manifest"):
        BUILDER.build(output)
    assert prior.read_text() == "This is unrelated user work.\n"


def test_builder_replaces_recognized_prior_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    (desktop / "go.mod").write_text("module fixture\n")
    (desktop / "main.go").write_text("package main\nfunc main() {}\n")
    output = tmp_path / "dist/desktop"
    output.mkdir(parents=True)
    launcher_bytes = b"prior compiled launcher"
    for name in BUILDER.LAUNCHERS:
        (output / name).write_bytes(launcher_bytes)
    prior = output / "desktop-build.json"
    prior.write_text(
        json.dumps(
            {
                "version": "0.2.9",
                "source_commit": "a" * 40,
                "source_sha256": "b" * 64,
                "source_dirty": False,
                "go": "go1.26.8",
                "files": {
                    name: hashlib.sha256(launcher_bytes).hexdigest()
                    for name in BUILDER.LAUNCHERS
                },
            }
        )
    )

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

    monkeypatch.setattr(BUILDER, "ROOT", tmp_path)
    monkeypatch.setattr(BUILDER.subprocess, "check_output", fake_output)
    monkeypatch.setattr(BUILDER.subprocess, "check_call", fake_build)
    BUILDER.build(output)
    assert json.loads(prior.read_text())[
        "source_sha256"
    ] == BUILDER.desktop_source_digest(tmp_path)
