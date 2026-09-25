"""Cached desktop launchers require unambiguous provenance metadata."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
BUILDER = importlib.import_module("build_desktop")


def test_desktop_bundle_rejects_duplicate_source_dirty(tmp_path):
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    (desktop / "go.mod").write_text("module fixture\n")
    (desktop / "main.go").write_text("package main\n")
    output = tmp_path / "dist" / "desktop"
    output.mkdir(parents=True)
    files = {}
    for name in BUILDER.LAUNCHERS:
        path = output / name
        path.write_bytes(f"fixture {name}".encode())
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    source = "a" * 40
    manifest = {
        "source_commit": source,
        "source_sha256": BUILDER.desktop_source_digest(tmp_path),
        "version": "0.2.9",
        "source_dirty": False,
        "go": BUILDER.GO_VERSION,
        "files": files,
    }
    raw = json.dumps(manifest).replace(
        '"source_dirty": false', '"source_dirty": true, "source_dirty": false'
    )
    (output / "desktop-build.json").write_text(raw)
    with pytest.raises(RuntimeError, match="duplicate"):
        BUILDER.verify_desktop_bundle(tmp_path, output, source, "0.2.9", False)


def test_desktop_bundle_rejects_linked_manifest(tmp_path):
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    (desktop / "go.mod").write_text("module fixture\n")
    (desktop / "main.go").write_text("package main\n")
    output = tmp_path / "dist" / "desktop"
    output.mkdir(parents=True)
    files = {}
    for name in BUILDER.LAUNCHERS:
        path = output / name
        path.write_bytes(f"fixture {name}".encode())
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    source = "a" * 40
    manifest = {
        "source_commit": source,
        "source_sha256": BUILDER.desktop_source_digest(tmp_path),
        "version": "0.2.9",
        "source_dirty": False,
        "go": BUILDER.GO_VERSION,
        "files": files,
    }
    foreign = tmp_path / "foreign.json"
    foreign.write_text(json.dumps(manifest))
    (output / "desktop-build.json").symlink_to(foreign)
    with pytest.raises(RuntimeError, match="manifest"):
        BUILDER.verify_desktop_bundle(tmp_path, output, source, "0.2.9", False)


def test_desktop_bundle_rejects_fifo_manifest_without_waiting(tmp_path):
    output = tmp_path / "dist" / "desktop"
    output.mkdir(parents=True)
    os.mkfifo(output / "desktop-build.json")
    script = (
        "import pathlib,sys; sys.path.insert(0,sys.argv[1]); "
        "from build_desktop import verify_desktop_bundle; "
        "verify_desktop_bundle(pathlib.Path(sys.argv[2]),pathlib.Path(sys.argv[3]),"
        "'a'*40,'0.2.9',False)"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(ROOT / "scripts"),
            str(tmp_path),
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=2,
    )
    assert result.returncode != 0
    assert "manifest" in result.stderr
