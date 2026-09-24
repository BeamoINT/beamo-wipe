#!/usr/bin/env python3
"""Publish generated live-image assets through no-follow directory descriptors."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

from stage_wrapper_sources import (
    install_bytes,
    read_regular_bytes,
    read_regular_file,
    require_approved_hook,
    require_executable,
)


README = """Beamo Wipe
This USB is a bootable nwipe front-end. It does not wipe from Windows.
On Windows: open Start Beamo Wipe.exe. Save your work, use Windows Restart,
then choose this USB from the computer's boot menu. The launcher does not
request administrator permission or set a one-time boot entry on Windows.
On supported Linux desktops: open Start Beamo Wipe Linux. A guided restart
is offered only when the USB and an exact boot entry can be verified.
You still choose and confirm the disk after restarting. Nothing erases automatically.
Open START-HERE.html for this USB's build and boot-menu keys.
Engine: nwipe (GPL). Wrapper: GPL-3.0-or-later. NO WARRANTY.
https://github.com/BeamoINT/beamo-wipe
"""


def staged_wrapper_digest(stage: Path) -> str:
    """Hash the bytes that live-build will actually install as wrapper source."""
    digest = hashlib.sha256()
    files = 0
    for path in sorted(stage.rglob("*")):
        if path.is_symlink():
            raise RuntimeError("staged wrapper contains a link")
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            raise RuntimeError("staged wrapper contains bytecode")
        relative = ("src/beamo_wipe/" + path.relative_to(stage).as_posix()).encode()
        file_sha = hashlib.sha256(read_regular_bytes(path)).hexdigest().encode()
        digest.update(f"{len(relative)}:".encode() + relative)
        digest.update(f"{len(file_sha)}:".encode() + file_sha)
        files += 1
    if not files:
        raise RuntimeError("staged wrapper is empty")
    return digest.hexdigest()


def stage_assets(root: Path, live: Path) -> None:
    sys.path.insert(0, str(root / "src"))
    from beamo_wipe import __version__
    from beamo_wipe.build_identity import assert_injectable, injected_payload
    from beamo_wipe.compat_story import inject_helper_html
    from beamo_wipe.release_manifest import git_commit, git_dirty, live_build_inputs

    build_id = os.environ.get("BUILD_ID", "local")
    dirty = git_dirty()[0]
    assert_injectable(
        build_id=build_id,
        source_dirty=dirty,
        allow_dirty=os.environ.get("ALLOW_DIRTY") == "1",
        hosted=os.environ.get("PROJECT_ID") == "beamo-wipe",
    )
    source_sha = live_build_inputs()["src/beamo_wipe/"]
    stage = live / "config/includes.chroot/usr/lib/python3/dist-packages/beamo_wipe"
    if staged_wrapper_digest(stage) != source_sha:
        raise RuntimeError("staged wrapper differs from current source")
    injected = injected_payload(
        source_commit=git_commit(),
        source_sha256=source_sha,
        build_id=build_id,
        source_dirty=dirty,
    )
    identity = (json.dumps(injected, sort_keys=True) + "\n").encode("ascii")
    share = live / "config/includes.chroot/usr/share/beamo-wipe"
    binary = live / "config/includes.binary"
    docs = live / "config/includes.chroot/usr/share/doc/beamo-wipe"
    expected: dict[Path, tuple[bytes, int]] = {}

    def put_bytes(path: Path, data: bytes, *, executable: bool = False) -> None:
        install_bytes(path, data, executable=executable)
        expected[path] = hashlib.sha256(data).digest(), 0o755 if executable else 0o644

    def put_file(source: Path, destination: Path) -> None:
        data, mode = read_regular_file(source)
        put_bytes(destination, data, executable=bool(mode & 0o111))

    put_bytes(share / "build-identity.json", identity)
    put_bytes(binary / "build-identity.json", identity)

    helper_html = read_regular_bytes(root / "helper/index.html").decode("utf-8")
    packaged_html = inject_helper_html(
        helper_html, version=__version__, injected=injected, packaged=True
    ).encode("utf-8")
    put_bytes(share / "helper/index.html", packaged_html)
    put_bytes(binary / "START-HERE.html", packaged_html)
    for name in ("fr.html", "de.html"):
        put_file(root / "helper" / name, share / "helper" / name)
    for name in ("finished.wav", "attention.wav"):
        put_file(root / "packaging/sounds" / name, share / "sounds" / name)

    for name in (
        "Start Beamo Wipe.exe",
        "Start Beamo Wipe Linux",
        "desktop-build.json",
    ):
        put_file(root / "dist/desktop" / name, binary / name)
    for name in ("GO-LICENSE.txt", "GO-PATENTS.txt"):
        put_file(root / "desktop" / name, binary / name)
    for name in ("NOTICE", "LICENSE", "THIRD_PARTY.md"):
        put_file(root / name, docs / name)
    for name in ("NOTICE", "LICENSE"):
        put_file(root / name, binary / name)
    source = b"Source: https://github.com/BeamoINT/beamo-wipe\n"
    put_bytes(binary / "SOURCE.txt", source)
    put_bytes(docs / "SOURCE.txt", source)
    put_bytes(binary / "README.txt", README.encode("utf-8"))

    require_executable(live / "config/includes.chroot/usr/local/bin/beamo-wipe")
    require_approved_hook(live)
    for path, (digest, mode) in expected.items():
        data, actual_mode = read_regular_file(path)
        if hashlib.sha256(data).digest() != digest or actual_mode != mode:
            raise RuntimeError(f"staged asset changed after publication: {path.name}")
    if staged_wrapper_digest(stage) != live_build_inputs()["src/beamo_wipe/"]:
        raise RuntimeError("staged wrapper changed during live asset staging")


def main() -> int:
    try:
        if len(sys.argv) != 3:
            raise RuntimeError("expected repository and live-build paths")
        stage_assets(Path(sys.argv[1]), Path(sys.argv[2]))
    except (OSError, RuntimeError, ValueError, UnicodeError) as exc:
        print(f"live asset staging failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
