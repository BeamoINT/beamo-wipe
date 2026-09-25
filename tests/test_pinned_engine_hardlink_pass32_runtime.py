"""A second nwipe process can exec the pinned inode through a hard link."""

import errno
import os

import pytest

from beamo_wipe import nwipe_runner


@pytest.mark.parametrize("deleted_alias", [False, True])
def test_pinned_engine_running_through_hardlink_blocks_another_wipe(
    tmp_path, monkeypatch, deleted_alias
):
    pinned = tmp_path / "nwipe"
    pinned.write_bytes(b"fake executable")
    alias = tmp_path / "nwipe-other-name"
    os.link(pinned, alias)
    running_stat = alias.stat()
    if deleted_alias:
        alias.unlink()
    monkeypatch.setattr(nwipe_runner, "NWIPE_PINNED_PATH", str(pinned))
    monkeypatch.setattr(nwipe_runner.os, "listdir", lambda path: ["4242"])
    monkeypatch.setattr(
        nwipe_runner.os,
        "readlink",
        lambda path: str(alias) + (" (deleted)" if deleted_alias else ""),
    )
    stat = os.stat

    def proc_stat(path, *args, **kwargs):
        if str(path) == "/proc/4242/exe":
            return running_stat
        return stat(path, *args, **kwargs)

    monkeypatch.setattr(nwipe_runner.os, "stat", proc_stat)

    assert nwipe_runner.pinned_nwipe_already_running() is True


def test_missing_pinned_path_cannot_rule_out_old_hardlink_process(
    tmp_path, monkeypatch
):
    pinned = tmp_path / "nwipe"
    pinned.write_bytes(b"fake executable")
    alias = tmp_path / "nwipe-other-name"
    os.link(pinned, alias)
    pinned.unlink()
    monkeypatch.setattr(nwipe_runner, "NWIPE_PINNED_PATH", str(pinned))
    monkeypatch.setattr(nwipe_runner.os, "listdir", lambda path: ["4242"])
    monkeypatch.setattr(nwipe_runner.os, "readlink", lambda path: str(alias))

    assert nwipe_runner.pinned_nwipe_already_running() is True


def test_process_exit_between_readlink_and_inode_check_is_ignored(
    tmp_path, monkeypatch
):
    pinned = tmp_path / "nwipe"
    pinned.write_bytes(b"fake executable")
    alias = tmp_path / "nwipe-other-name"
    os.link(pinned, alias)
    monkeypatch.setattr(nwipe_runner, "NWIPE_PINNED_PATH", str(pinned))
    monkeypatch.setattr(nwipe_runner.os, "listdir", lambda path: ["4242"])
    monkeypatch.setattr(nwipe_runner.os, "readlink", lambda path: str(alias))
    stat = os.stat

    def proc_stat(path, *args, **kwargs):
        if str(path) == "/proc/4242/exe":
            raise FileNotFoundError(errno.ENOENT, "gone", path)
        return stat(path, *args, **kwargs)

    monkeypatch.setattr(nwipe_runner.os, "stat", proc_stat)

    assert nwipe_runner.pinned_nwipe_already_running() is False
