# SPDX-License-Identifier: GPL-3.0-or-later
"""Process entry. Preview with ./preview or --demo. Never auto-starts a wipe."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from pathlib import Path

from beamo_wipe import NWIPE_PINNED_VERSION, __version__
from beamo_wipe.demo import Scenario, make_demo_wizard
from beamo_wipe.discover import discover, load_lsblk_json_text
from beamo_wipe.nwipe_runner import DryRunRunner, NwipeRunner
from beamo_wipe.models import Screen
from beamo_wipe.safety import SafetyError, require_live_or_dry_run, running_on_live_usb
from beamo_wipe.wizard import Wizard


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="beamo-wipe",
        description=(
            "Guided front-end for nwipe. This is not a wipe engine. "
            "It will not erase disks from inside Windows or macOS. "
            "On this computer, use --preview or ./preview (fake disks)."
        ),
    )
    p.add_argument(
        "--demo",
        "--preview",
        dest="demo",
        action="store_true",
        help="Tk window with fake disks. Nothing is erased.",
    )
    p.add_argument(
        "--web",
        "--gallery",
        dest="web",
        action="store_true",
        help="Open a browser click-through of the screens. Does not wipe.",
    )
    p.add_argument(
        "--helper",
        action="store_true",
        help="Open the boot-menu helper page (does not wipe).",
    )
    p.add_argument(
        "--scenario",
        choices=("happy", "empty", "blocked", "fail"),
        default="happy",
        help="Preview disk list: happy, empty, blocked, or fail.",
    )
    p.add_argument("--empty", action="store_true", help="Preview: only the Beamo USB.")
    p.add_argument("--blocked", action="store_true", help="Preview: cannot identify USB.")
    p.add_argument(
        "--fail",
        "--fail-demo",
        dest="fail_demo",
        action="store_true",
        help="Preview a failed wipe.",
    )
    p.add_argument("--plain-console", action="store_true", help="Use sequential text prompts without curses screen redraws.")
    p.add_argument("--console", action="store_true", help="Use the keyboard console UI.")
    p.add_argument("--fullscreen", action="store_true", help="Fill the screen (live USB).")
    p.add_argument("--dry-run", action="store_true", help="Do not invoke nwipe.")
    p.add_argument("--lsblk-json", help="Read disks from an lsblk JSON file.")
    p.add_argument("--boot-device", help="Override live-medium path (tests only).")
    p.add_argument("--version", action="version", version=f"Beamo Wipe {__version__}")
    return p


def _scenario(args: argparse.Namespace) -> Scenario:
    if args.empty:
        return "empty"
    if args.blocked:
        return "blocked"
    if args.fail_demo:
        return "fail"
    return args.scenario  # type: ignore[return-value]


def _open_html(path: Path) -> int:
    if not path.is_file():
        print(f"Missing file: {path}", file=sys.stderr)
        return 2
    if os.environ.get("BEAMO_WIPE_NO_OPEN") == "1":
        print(path)
        return 0
    import webbrowser

    webbrowser.open(path.resolve().as_uri())
    print(path)
    return 0


def apply_live_session_overrides(args: argparse.Namespace) -> None:
    """On the live USB, preview/gallery flags cannot disguise a fake wipe."""
    if not running_on_live_usb():
        return
    args.demo = False
    args.empty = False
    args.blocked = False
    args.fail_demo = False
    args.scenario = "happy"
    args.lsblk_json = None
    args.boot_device = None
    args.dry_run = False
    args.web = False
    args.helper = False
    os.environ.pop("BEAMO_WIPE_BOOT_DEVICE", None)
    os.environ.pop("BEAMO_WIPE_DRY_RUN", None)
    os.environ.pop("BEAMO_WIPE_DEMO", None)


def _build_wizard(args: argparse.Namespace) -> Wizard:
    apply_live_session_overrides(args)

    if args.demo:
        os.environ["BEAMO_WIPE_DEMO"] = "1"
        os.environ["BEAMO_WIPE_DRY_RUN"] = "1"
        return make_demo_wizard(fail=args.fail_demo, scenario=_scenario(args))

    if args.lsblk_json:
        args.dry_run = True
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
    use_dry = (
        args.dry_run
        or args.demo
        or bool(args.lsblk_json)
        or os.environ.get("BEAMO_WIPE_DEMO") == "1"
        or os.environ.get("BEAMO_WIPE_DRY_RUN") == "1"
    )
    if use_dry:
        runner = DryRunRunner(duration_s=3.0, fail=args.fail_demo)
        def fresh_fake_discovery():
            if not args.lsblk_json:
                raise SafetyError("A fake lsblk JSON file is required for refresh.")
            with open(args.lsblk_json, encoding="utf-8") as fh:
                fresh_payload = load_lsblk_json_text(fh.read())
            return discover(lsblk_payload=fresh_payload, boot_path=args.boot_device)
        return Wizard(discovery, runner, dry_run=True, rediscover=fresh_fake_discovery)
    live_runner = NwipeRunner()
    return Wizard(discovery, live_runner, dry_run=False)


def _shutdown() -> bool:
    import subprocess

    last_exc: Exception | None = None
    for cmd in (
        ["/usr/bin/systemctl", "poweroff"],
        ["/bin/systemctl", "poweroff"],
        ["/sbin/shutdown", "-h", "now"],
        ["/usr/sbin/shutdown", "-h", "now"],
        ["/sbin/poweroff"],
        ["/usr/sbin/poweroff"],
        ["/sbin/halt", "-p"],
    ):
        try:
            # Harden: never inherit attacker-controlled env (LD_PRELOAD etc.)
            # even for poweroff — use the same replacement env as nwipe.
            from beamo_wipe.safety import CLEAN_SUBPROCESS_ENV

            completed = subprocess.run(
                cmd,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                env=CLEAN_SUBPROCESS_ENV,
                shell=False,
                timeout=8,
            )
            if completed.returncode == 0:
                return True
            last_exc = RuntimeError(f"exit {completed.returncode}")
        except (OSError, subprocess.TimeoutExpired) as exc:
            last_exc = exc
            continue
    # All shutdown paths failed; surface to diagnostics and stderr (safe, no secrets)
    try:
        from beamo_wipe.diagnostics import log_diag

        detail = type(last_exc).__name__ if last_exc else "unknown"
        log_diag("app", "shutdown_failed", detail)
    except Exception:
        pass
    print("Shutdown failed: could not power off. Hold the power button.", file=sys.stderr)
    return False


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.empty or args.blocked or args.fail_demo or args.scenario != "happy":
        args.demo = True
    apply_live_session_overrides(args)
    if not args.demo:
        try:
            signal.signal(signal.SIGTSTP, signal.SIG_IGN)
            signal.signal(signal.SIGINT, signal.SIG_IGN)
        except (AttributeError, ValueError, OSError):
            pass
    if args.web:
        from beamo_wipe.gallery import open_gallery, write_gallery

        dest = project_root() / "web-preview" / "index.html"
        if not (project_root() / "helper" / "index.html").is_file():
            dest = Path.cwd() / "web-preview" / "index.html"
        if os.environ.get("BEAMO_WIPE_NO_OPEN") == "1":
            path = write_gallery(dest)
            print(path)
            return 0
        path = open_gallery(dest)
        print(path)
        return 0
    if args.helper:
        helper = project_root() / "helper" / "index.html"
        if not helper.is_file():
            helper = Path.cwd() / "helper" / "index.html"
        return _open_html(helper)

    try:
        wizard = _build_wizard(args)
    except SafetyError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    windowed = args.demo and not args.fullscreen
    use_console = args.plain_console or args.console or os.environ.get("BEAMO_WIPE_UI") == "console"
    if not use_console:
        try:
            from beamo_wipe.ui.tk_wizard import run_tk

            code = run_tk(wizard, fullscreen=args.fullscreen or not windowed)
            if wizard.wants_shutdown and not args.demo and not wizard.dry_run:
                _shutdown()
            return code
        except Exception as exc:  # noqa: BLE001 — fall back to console
            print(f"Graphical UI failed ({exc}). Using keyboard screens.", file=sys.stderr)
            if not args.demo and not wizard.dry_run:
                # Under startx, running the console here leaves X owning tty1
                # and hides the fallback. Exit so the kiosk supervisor can
                # tear X down and launch the visible console on tty1.
                if wizard.screen == Screen.WORKING:
                    try:
                        wizard.cancel_wipe(origin="system")
                    except Exception as cancel_exc:
                        try:
                            from beamo_wipe.diagnostics import log_diag

                            log_diag(
                                "app",
                                "graphical_failure_cancel_failed",
                                type(cancel_exc).__name__,
                            )
                        except Exception:
                            pass
                return 3
            use_console = True

    from beamo_wipe.ui.console_wizard import run_console

    if args.plain_console:
        from beamo_wipe.ui.console_wizard import _plain_loop
        code = _plain_loop(wizard)
    else:
        code = run_console(wizard)
    if wizard.wants_shutdown and not args.demo and not wizard.dry_run:
        _shutdown()
    return code


# Referenced by packaging so the ISO banner can print the engine version.
NWIPE_VERSION = NWIPE_PINNED_VERSION
