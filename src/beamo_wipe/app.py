# SPDX-License-Identifier: GPL-3.0-or-later
"""Process entry. Preview with --demo. Never auto-starts a wipe."""

from __future__ import annotations

import argparse
import os
import sys

from beamo_wipe import NWIPE_PINNED_VERSION, __version__
from beamo_wipe.discover import discover, load_lsblk_json_text
from beamo_wipe.nwipe_runner import DryRunRunner, NwipeRunner
from beamo_wipe.safety import SafetyError, require_live_or_dry_run
from beamo_wipe.wizard import Wizard, make_demo_wizard


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="beamo-wipe",
        description=(
            "Guided front-end for nwipe. This is not a wipe engine. "
            "It will not erase disks from inside Windows or macOS."
        ),
    )
    p.add_argument("--demo", action="store_true", help="Fake disks. No real wipe.")
    p.add_argument("--console", action="store_true", help="Use the keyboard console UI.")
    p.add_argument("--fullscreen", action="store_true", help="Fill the screen (live USB).")
    p.add_argument("--dry-run", action="store_true", help="Do not invoke nwipe.")
    p.add_argument("--lsblk-json", help="Read disks from an lsblk JSON file.")
    p.add_argument("--boot-device", help="Override live-medium path (tests only).")
    p.add_argument("--fail-demo", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--version", action="version", version=f"Beamo Wipe {__version__}")
    return p


def _build_wizard(args: argparse.Namespace) -> Wizard:
    if args.demo:
        os.environ["BEAMO_WIPE_DEMO"] = "1"
        os.environ["BEAMO_WIPE_DRY_RUN"] = "1"
        return make_demo_wizard(fail=args.fail_demo)

    if args.dry_run:
        os.environ["BEAMO_WIPE_DRY_RUN"] = "1"
    if args.boot_device:
        os.environ["BEAMO_WIPE_BOOT_DEVICE"] = args.boot_device

    require_live_or_dry_run()

    payload = None
    if args.lsblk_json:
        with open(args.lsblk_json, encoding="utf-8") as fh:
            payload = load_lsblk_json_text(fh.read())

    discovery = discover(
        lsblk_payload=payload,
        boot_path=args.boot_device,
    )
    if args.dry_run:
        runner = DryRunRunner(duration_s=3.0, fail=args.fail_demo)
        return Wizard(discovery, runner, dry_run=True)
    runner = NwipeRunner()
    return Wizard(discovery, runner, dry_run=False)


def _shutdown() -> None:
    import subprocess

    for cmd in (
        ["systemctl", "poweroff"],
        ["shutdown", "-h", "now"],
        ["poweroff"],
    ):
        try:
            subprocess.Popen(cmd)
            return
        except OSError:
            continue


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        wizard = _build_wizard(args)
    except SafetyError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    use_console = args.console or os.environ.get("BEAMO_WIPE_UI") == "console"
    if not use_console:
        try:
            from beamo_wipe.ui.tk_wizard import run_tk

            code = run_tk(wizard, fullscreen=args.fullscreen or not args.demo)
            if wizard.wants_shutdown and not args.demo:
                _shutdown()
            return code
        except Exception as exc:  # noqa: BLE001 — fall back to console
            print(f"Graphical UI failed ({exc}). Using keyboard screens.", file=sys.stderr)
            use_console = True

    from beamo_wipe.ui.console_wizard import run_console

    code = run_console(wizard)
    if wizard.wants_shutdown and not args.demo:
        _shutdown()
    return code


# Referenced by packaging so the ISO banner can print the engine version.
NWIPE_VERSION = NWIPE_PINNED_VERSION
