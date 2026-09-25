"""Launcher builds must not inherit Go settings outside their source receipt."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "beamo_desktop_builder_go_environment", ROOT / "scripts" / "build_desktop.py"
)
assert SPEC and SPEC.loader
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def test_launcher_build_ignores_inherited_go_overlays_and_cpu_level(
    tmp_path, monkeypatch
):
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    (desktop / "go.mod").write_text("module fixture\n")
    (desktop / "main.go").write_text("package main\n")
    monkeypatch.setattr(BUILDER, "ROOT", tmp_path)
    monkeypatch.setenv("GOFLAGS", "-overlay=/tmp/unrecorded-go-source.json")
    monkeypatch.setenv("GOWORK", "/tmp/unrecorded-go.work")
    monkeypatch.setenv("GOAMD64", "v4")
    monkeypatch.setenv("GOEXPERIMENT", "loopvar")
    monkeypatch.setenv("GOENV", "/tmp/unrecorded-go-env")
    monkeypatch.setenv("GOROOT", "/tmp/unrecorded-go-root")
    monkeypatch.setenv("GO111MODULE", "off")
    build_envs = []

    def output(argv, **_kwargs):
        if argv[1:] == ["version"]:
            return "go version go1.26.8 darwin/arm64\n"
        if argv[1:] == ["rev-parse", "HEAD"]:
            return "a" * 40 + "\n"
        if argv[1:] == ["status", "--porcelain"]:
            return ""
        raise AssertionError(argv)

    def compile_fake(argv, **kwargs):
        build_envs.append(kwargs["env"])
        Path(argv[argv.index("-o") + 1]).write_bytes(b"fixture launcher")

    monkeypatch.setattr(BUILDER.subprocess, "check_output", output)
    monkeypatch.setattr(BUILDER.subprocess, "check_call", compile_fake)
    BUILDER.build(tmp_path / "dist" / "desktop")

    assert len(build_envs) == 2
    for env in build_envs:
        assert env["GOFLAGS"] == ""
        assert env["GOWORK"] == "off"
        assert env["GOAMD64"] == "v1"
        assert env["GOEXPERIMENT"] == ""
        assert env["GOENV"] == "off"
        assert "GOROOT" not in env
        assert env["GO111MODULE"] == "on"
