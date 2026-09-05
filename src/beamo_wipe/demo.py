# SPDX-License-Identifier: GPL-3.0-or-later
"""Load fake lsblk JSON for --demo / --preview scenarios."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from beamo_wipe.discover import discover, load_lsblk_json_text
from beamo_wipe.models import DiscoveryResult
from beamo_wipe.nwipe_runner import DryRunRunner
from beamo_wipe.wizard import Wizard

Scenario = Literal["happy", "empty", "blocked", "fail"]
HERE = Path(__file__).resolve().parent
DEMO_DURATION_S = 8.0


def _payload(name: str) -> dict:
    return load_lsblk_json_text((HERE / name).read_text(encoding="utf-8"))


def discovery_for_scenario(scenario: Scenario) -> DiscoveryResult:
    if scenario == "fail":
        scenario = "happy"
    if scenario == "blocked":
        return discover(
            lsblk_payload=_payload("demo_blocked.json"),
            boot_path=None,
            mount_sources=[],
            cmdline="",
            env={"BEAMO_WIPE_DRY_RUN": "1"},
        )
    if scenario == "empty":
        return discover(
            lsblk_payload=_payload("demo_empty.json"),
            boot_path="/dev/sdb",
            mount_sources=[],
            cmdline="",
            env={"BEAMO_WIPE_DRY_RUN": "1", "BEAMO_WIPE_BOOT_DEVICE": "/dev/sdb"},
        )
    return discover(
        lsblk_payload=_payload("demo_lsblk.json"),
        boot_path="/dev/sdb",
        mount_sources=[],
        cmdline="",
        env={"BEAMO_WIPE_DRY_RUN": "1", "BEAMO_WIPE_BOOT_DEVICE": "/dev/sdb"},
    )


def make_demo_wizard(fail: bool = False, scenario: Scenario = "happy") -> Wizard:
    import os

    os.environ["BEAMO_WIPE_DRY_RUN"] = "1"
    os.environ["BEAMO_WIPE_DEMO"] = "1"
    if scenario == "fail":
        fail = True
        scenario = "happy"
    discovery = discovery_for_scenario(scenario)
    runner = DryRunRunner(duration_s=DEMO_DURATION_S, fail=fail)
    wiz = Wizard(discovery, runner, dry_run=True, rediscover=lambda: discovery_for_scenario(scenario))
    wiz.preview = True
    return wiz
