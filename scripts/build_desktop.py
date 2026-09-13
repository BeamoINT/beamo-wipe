#!/usr/bin/env python3
"""Build portable launchers without a shell, device discovery, or reboot."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
GO_VERSION = "go1.26.8"


def build(output=None):
    go = os.environ.get("BEAMO_GO_BIN", "go")
    env = os.environ.copy()
    env.update(CGO_ENABLED="0", GOTOOLCHAIN="local")
    version_line = subprocess.check_output([go, "version"], text=True, env=env).split()
    if len(version_line) < 3 or version_line[2] != GO_VERSION:
        raise RuntimeError(
            "Launcher builds require Go 1.26.8 (see scripts/ci-desktop.sh)."
        )
    sys.path.insert(0, str(ROOT / "src"))
    from beamo_wipe import __version__

    source = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    dirty = bool(
        subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True
        ).strip()
    )
    output = Path(output) if output is not None else ROOT / "dist" / "desktop"
    output.mkdir(parents=True, exist_ok=True)
    lock = output / ".build.lock"
    try:
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeError(
            "Another desktop build owns this output. Wait for it to finish; see docs/development.md for interrupted builds."
        ) from exc
    try:
        manifest = output / "desktop-build.json"
        # A failed rebuild must not leave an earlier success receipt beside partial outputs.
        manifest.unlink(missing_ok=True)
        flags = f"-s -w -X main.version={__version__} -X main.sourceCommit={source} -X main.sourceDirty={str(dirty).lower()}"
        files = {}
        for host, name in (
            ("linux", "Start Beamo Wipe Linux"),
            ("windows", "Start Beamo Wipe.exe"),
        ):
            target = output / name
            subprocess.check_call(
                [
                    go,
                    "build",
                    "-trimpath",
                    "-buildvcs=false",
                    "-ldflags",
                    flags + (" -H=windowsgui" if host == "windows" else ""),
                    "-o",
                    str(target),
                    ".",
                ],
                cwd=ROOT / "desktop",
                env={**env, "GOOS": host, "GOARCH": "amd64"},
            )
            files[name] = hashlib.sha256(target.read_bytes()).hexdigest()
        manifest.write_text(
            json.dumps(
                {
                    "version": __version__,
                    "source_commit": source,
                    "go": GO_VERSION,
                    "files": files,
                },
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(
            "Built Windows and Linux desktop launchers. Runtime and firmware tests remain separate gates."
        )
    finally:
        os.close(lock_fd)
        lock.unlink()


if __name__ == "__main__":
    try:
        build()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
