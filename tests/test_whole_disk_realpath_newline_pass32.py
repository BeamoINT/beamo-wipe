"""A resolved alias must be an exact whole-disk node name."""

import os

import pytest

from beamo_wipe.safety import SafetyError, normalize_whole_disk


def test_alias_resolving_to_newline_suffixed_node_is_rejected(monkeypatch):
    original = os.path.realpath

    def fake_realpath(path):
        if path == "/dev/disk/by-id/claimed-disk":
            return "/dev/sda\n"
        return original(path)

    monkeypatch.setattr(os.path, "realpath", fake_realpath)
    with pytest.raises(SafetyError, match="whole-disk"):
        normalize_whole_disk("/dev/disk/by-id/claimed-disk")


def test_alias_resolving_to_exact_whole_disk_remains_accepted(monkeypatch):
    original = os.path.realpath

    def fake_realpath(path):
        if path == "/dev/disk/by-id/claimed-disk":
            return "/dev/sda"
        return original(path)

    monkeypatch.setattr(os.path, "realpath", fake_realpath)
    assert normalize_whole_disk("/dev/disk/by-id/claimed-disk") == "/dev/sda"
