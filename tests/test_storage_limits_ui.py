# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline guidance on real fake-JSON classification and console rendering."""

import json
from pathlib import Path

import pytest

from beamo_wipe import storage_limits as limits
from beamo_wipe.discover import discover
from beamo_wipe.models import DiskKind, Screen
from beamo_wipe.nwipe_runner import DryRunRunner
from beamo_wipe.ui.console_wizard import _plain_loop
from beamo_wipe.wizard import Wizard


@pytest.mark.parametrize(
    "rota,kind", [(False, DiskKind.SSD), (True, DiskKind.HDD), (None, DiskKind.UNKNOWN)]
)
def test_fake_lsblk_classification_console_and_help(rota, kind, monkeypatch, capsys):
    payload = json.loads(
        (Path(__file__).parent / "fixtures/lsblk_vm_iso.json").read_text()
    )
    target = next(node for node in payload["blockdevices"] if node["name"] == "vda")
    target.update(rota=rota, tran=None, model="Unknown type fixture")
    discovery = discover(
        lsblk_payload=payload,
        boot_path="/dev/sr0",
        mount_sources=[],
        cmdline="",
        env={"BEAMO_WIPE_DRY_RUN": "1"},
    )
    wiz = Wizard(discovery, DryRunRunner(), dry_run=True)
    wiz.skip_splash()
    wiz.accept_what()
    wiz.set_owner(True)
    wiz.continue_owner()
    wiz.select_disk("/dev/vda")
    wiz.continue_pick()
    wiz.set_confirm_input(wiz.confirm.token)
    wiz.continue_confirm()
    assert wiz.selected.kind == kind
    seen = []

    def answer(prompt):
        seen.append(wiz.screen)
        if wiz.screen == Screen.METHOD:
            if seen.count(Screen.METHOD) == 1:
                return "l"
            raise EOFError
        return ""

    monkeypatch.setattr("builtins.input", answer)
    _plain_loop(wiz)
    text = capsys.readouterr().out
    assert limits.notice(kind) in text
    for _title, body in limits.SECTIONS:
        assert body in " ".join(text.split())
    assert wiz.selected.kind == kind
    assert seen.count(Screen.LIMITS) == len(limits.SECTIONS)
    assert not wiz.runner.started


def test_offline_limits_and_documentation_are_identical():
    doc = (
        Path(__file__).parents[1] / "docs/storage-and-controller-limits.md"
    ).read_text()
    assert limits.full_text() in doc
    assert "Additional overwrite passes do not fix" in limits.full_text()
