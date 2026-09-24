"""Generated ISO includes stay bound to their opened staging directory."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
STAGER_PATH = ROOT / "scripts" / "stage_wrapper_sources.py"
SPEC = importlib.util.spec_from_file_location(
    "beamo_stage_publication_pass20", STAGER_PATH
)
assert SPEC and SPEC.loader
STAGER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STAGER)


def test_install_refuses_success_after_parent_swap(tmp_path, monkeypatch):
    output = tmp_path / "stage"
    output.mkdir()
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    original = STAGER._open_output_directory
    swapped = False

    def open_then_swap(path):
        nonlocal swapped
        fd = original(path)
        if not swapped:
            swapped = True
            output.rename(tmp_path / "old-stage")
            output.symlink_to(foreign, target_is_directory=True)
        return fd

    monkeypatch.setattr(STAGER, "_open_output_directory", open_then_swap)
    with pytest.raises(RuntimeError, match="staging directory changed"):
        STAGER.install_bytes(output / "README.txt", b"generated")
    assert list(foreign.iterdir()) == []


def test_install_replaces_link_leaf_without_touching_target(tmp_path):
    output = tmp_path / "stage"
    output.mkdir()
    foreign = tmp_path / "foreign.txt"
    foreign.write_bytes(b"foreign")
    destination = output / "START-HERE.html"
    destination.symlink_to(foreign)

    STAGER.install_bytes(destination, b"generated")

    assert foreign.read_bytes() == b"foreign"
    assert not destination.is_symlink()
    assert destination.read_bytes() == b"generated"


def test_install_rechecks_published_bytes(tmp_path, monkeypatch):
    output = tmp_path / "stage"
    output.mkdir()

    class ReplaceThenAlter:
        def __getattr__(self, name):
            return getattr(os, name)

        def replace(self, source, destination, **kwargs):
            os.replace(source, destination, **kwargs)
            fd = os.open(
                destination,
                os.O_WRONLY | os.O_TRUNC,
                dir_fd=kwargs["dst_dir_fd"],
            )
            with os.fdopen(fd, "wb") as stream:
                stream.write(b"foreign")

    monkeypatch.setattr(STAGER, "os", ReplaceThenAlter())
    with pytest.raises(RuntimeError, match="staged include bytes changed"):
        STAGER.install_bytes(output / "README.txt", b"generated")


def test_live_entrypoint_fifo_does_not_block(tmp_path):
    entrypoint = tmp_path / "beamo-wipe"
    os.mkfifo(entrypoint)
    code = (
        "from pathlib import Path; import sys; "
        "sys.path.insert(0, sys.argv[1]); "
        "from stage_wrapper_sources import require_executable; "
        "require_executable(Path(sys.argv[2]))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(ROOT / "scripts"), str(entrypoint)],
        capture_output=True,
        text=True,
        timeout=2,
    )
    assert result.returncode != 0


def test_live_entrypoint_link_does_not_chmod_target(tmp_path):
    foreign = tmp_path / "foreign"
    foreign.write_bytes(b"foreign")
    foreign.chmod(0o600)
    entrypoint = tmp_path / "beamo-wipe"
    entrypoint.symlink_to(foreign)

    with pytest.raises(OSError):
        STAGER.require_executable(entrypoint)
    assert foreign.stat().st_mode & 0o777 == 0o600


def test_live_entrypoint_refuses_success_after_parent_swap(tmp_path, monkeypatch):
    parent = tmp_path / "stage"
    parent.mkdir()
    entrypoint = parent / "beamo-wipe"
    entrypoint.write_bytes(b"#!/bin/sh\n")
    entrypoint.chmod(0o755)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    original = STAGER._open_output_directory
    swapped = False

    def open_then_swap(path):
        nonlocal swapped
        fd = original(path)
        if not swapped:
            swapped = True
            parent.rename(tmp_path / "old-stage")
            parent.symlink_to(foreign, target_is_directory=True)
        return fd

    monkeypatch.setattr(STAGER, "_open_output_directory", open_then_swap)
    with pytest.raises(RuntimeError, match="staging directory changed"):
        STAGER.require_executable(entrypoint)
    assert list(foreign.iterdir()) == []


def test_linked_live_hook_does_not_chmod_target(tmp_path):
    live = tmp_path / "packaging" / "live"
    hooks = live / "config/hooks/normal"
    hooks.mkdir(parents=True)
    foreign = tmp_path / "foreign-hook"
    foreign.write_bytes(b"foreign")
    foreign.chmod(0o600)
    (hooks / "0500-build-nwipe.hook.chroot").symlink_to(foreign)

    with pytest.raises(RuntimeError, match="unapproved live-build hook"):
        STAGER.require_approved_hook(live)
    assert foreign.stat().st_mode & 0o777 == 0o600


def test_only_regular_approved_live_hook_is_accepted(tmp_path):
    live = tmp_path / "packaging" / "live"
    hooks = live / "config/hooks/normal"
    hooks.mkdir(parents=True)
    approved = hooks / "0500-build-nwipe.hook.chroot"
    approved.write_bytes(b"#!/bin/sh\n")
    approved.chmod(0o755)

    STAGER.require_approved_hook(live)
    (hooks / "other.hook.chroot").write_bytes(b"#!/bin/sh\n")
    with pytest.raises(RuntimeError, match="unapproved live-build hook"):
        STAGER.require_approved_hook(live)
