#!/usr/bin/env python3
"""Develop Beamo Wipe with fake devices; see docs/development.md."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def venv_python(host=None):
    host = host or sys.platform
    directory = ROOT / (".venv-" + host)
    return directory / ("Scripts/python.exe" if host == "win32" else "bin/python")


def python():
    candidate = venv_python()
    return str(candidate if candidate.is_file() else Path(sys.executable))


def fake_environment(*, preview=False):
    env = os.environ.copy()
    for key in (
        "BEAMO_WIPE_LIVE",
        "BEAMO_WIPE_BOOT_DEVICE",
        "BEAMO_DESKTOP_NATIVE_INVENTORY_TEST",
        "BEAMO_WIPE_DEMO",
    ):
        env.pop(key, None)
    env.update(BEAMO_WIPE_DRY_RUN="1", PYTHONPATH=str(ROOT / "src"))
    if preview:
        env["BEAMO_WIPE_DEMO"] = "1"
    return env


def live_environment():
    # Do not clear live markers to make a development command work on the kiosk.
    if os.environ.get("BEAMO_WIPE_LIVE") == "1":
        return True
    if sys.platform != "linux":
        return False
    try:
        return (
            "boot=live" in Path("/proc/cmdline").read_text().split()
            or Path("/run/live/medium").is_mount()
        )
    except OSError:
        return True  # Unknown Linux runtime: refuse to start a preview/test.


def run(argv, **kwargs):
    try:
        return subprocess.run(argv, cwd=kwargs.pop("cwd", ROOT), **kwargs).returncode
    except OSError as exc:
        print(f"Could not run {argv[0]}: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


def wsl(argv):
    executable = shutil.which("wsl.exe")
    if not executable:
        print(
            "The Python wizard needs Linux on Windows. Install WSL2 with Ubuntu, then see docs/development.md.",
            file=sys.stderr,
        )
        return 2
    try:
        conversion = subprocess.run(
            [executable, "--exec", "wslpath", "-a", "-u", str(ROOT)],
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        print(f"WSL2 could not start: {exc}", file=sys.stderr)
        return 2
    if conversion.returncode or not conversion.stdout.strip().startswith("/"):
        print(
            "WSL2 path conversion failed. Start your Ubuntu distribution and install python3 and python3-venv.\n"
            + (conversion.stderr or ""),
            file=sys.stderr,
        )
        return conversion.returncode or 2
    path = conversion.stdout.strip().rstrip("/") + "/dev.py"
    return run([executable, "--exec", "python3", path, *argv])


def doctor():
    checks = {
        "python": sys.version.split()[0],
        "host": sys.platform,
        "machine": __import__("platform").machine(),
        "checkout": str(ROOT),
        "environment_python": python(),
        "git": shutil.which("git"),
        "go": shutil.which(os.environ.get("BEAMO_GO_BIN", "go")),
        "gcloud": shutil.which("gcloud"),
        "wsl": shutil.which("wsl.exe") if sys.platform == "win32" else "not needed",
        "live_environment": live_environment(),
    }
    # Importing Tk is safe; do not create a window or claim display availability.
    probe = subprocess.run(
        [python(), "-c", "import tkinter; print(tkinter.TkVersion)"],
        capture_output=True,
        text=True,
    )
    checks["tk_import"] = (
        probe.stdout.strip()
        if probe.returncode == 0
        else "unavailable (web preview remains available)"
    )
    checks["tk_display"] = "not probed; use preview to test the actual display"
    checks["python_workflow"] = (
        "WSL2 required" if sys.platform == "win32" else "native POSIX"
    )
    print(json.dumps(checks, indent=2))
    print(
        "Optional tools: Go 1.26.8 for desktop builds; gcloud for the full amd64 gate. See docs/development.md."
    )
    return (
        0
        if sys.version_info >= (3, 10)
        and checks["git"]
        and not checks["live_environment"]
        else 2
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "doctor", help="Report available tools without installing or reading disks"
    )
    for name in ("setup", "test"):
        child = sub.add_parser(name)
        child.add_argument(
            "--native",
            action="store_true",
            help="Native developer tooling only; no Python wizard or Linux acceptance claims",
        )
    child = sub.add_parser(
        "preview", help="Fake wizard preview; Windows delegates to WSL2"
    )
    child.add_argument("args", nargs=argparse.REMAINDER)
    sub.add_parser(
        "desktop-build", help="Build Windows and Linux launchers with pinned Go"
    )
    sub.add_parser(
        "desktop-test", help="Native Go unit tests and vet; no host inventory opt-in"
    )
    argv = list(sys.argv[1:] if argv is None else argv)
    preview_args = argv[1:] if argv[:1] == ["preview"] else []
    args = parser.parse_args(["preview"] if argv[:1] == ["preview"] else argv)
    if args.command == "doctor":
        return doctor()
    if live_environment():
        print(
            "Development commands are disabled on the live erasure system. Use a separate development machine.",
            file=sys.stderr,
        )
        return 2
    if sys.version_info < (3, 10):
        print("Python 3.10 or newer is required.", file=sys.stderr)
        return 2
    if args.command == "preview":
        if preview_args[:1] == ["--"]:
            preview_args = preview_args[1:]
        if sys.platform == "win32":
            return wsl(["preview", *preview_args])
        env = fake_environment(preview=True)
        # Preserve the canonical Mac Tk >=8.6.13 selection and console fallback.
        # Other hosts use the development venv when present.
        if sys.platform != "darwin":
            env["BEAMO_WIPE_PREVIEW_PYTHON"] = python()
        return run(["sh", str(ROOT / "scripts/preview.sh"), *preview_args], env=env)
    if (
        args.command in ("setup", "test")
        and sys.platform == "win32"
        and not args.native
    ):
        return wsl([args.command])
    if args.command == "setup":
        destination = venv_python().parents[1]
        if not venv_python().is_file():
            code = run([sys.executable, "-m", "venv", str(destination)])
            if code:
                print(
                    "Environment creation failed. On Debian/Ubuntu install python3-venv; rerun setup to retry.",
                    file=sys.stderr,
                )
                return code
        code = run(
            [python(), "-m", "pip", "install", "--upgrade", "pip>=23", "setuptools>=68"]
        )
        if code:
            return code
        packages = (
            ["pytest==9.0.3"]
            if args.native
            else ["-e", ".[dev]", "pytest==9.0.3", "ruff==0.9.2", "mypy==2.1.0"]
        )
        return run([python(), "-m", "pip", "install", *packages])
    if args.command == "test":
        cmd = [python(), "-m", "pytest"] + (["developer_tests"] if args.native else [])
        env = fake_environment()
        # Isolated Xvfb avoids replacing the user's desktop or depending on its DPI.
        if (
            not args.native
            and sys.platform == "linux"
            and shutil.which("xvfb-run")
            and shutil.which("dbus-run-session")
        ):
            cmd = [
                "dbus-run-session",
                "--",
                "xvfb-run",
                "-a",
                "-s",
                "-screen 0 1600x1000x24 -dpi 72",
                *cmd,
            ]
        print(
            "Running developer tooling tests only."
            if args.native
            else "Running the full checkout suite; environment-dependent skips remain visible.",
            flush=True,
        )
        return run(cmd, env=env)
    if args.command == "desktop-build":
        return run([python(), str(ROOT / "scripts/build_desktop.py")])
    env = fake_environment()
    env["GOTOOLCHAIN"] = "local"
    env.pop("GOOS", None)
    env.pop("GOARCH", None)
    go = os.environ.get("BEAMO_GO_BIN", "go")
    for operation in (["test", "./..."], ["vet", "./..."]):
        code = run([go, *operation], cwd=ROOT / "desktop", env=env)
        if code:
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
