"""Live asset publication uses the staged wrapper and safe output paths."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys

from scripts.build_desktop import GO_VERSION, desktop_source_digest


ROOT = Path(__file__).resolve().parents[1]
STAGER = ROOT / "scripts" / "stage_wrapper_sources.py"
ASSETS = ROOT / "scripts" / "stage_live_assets.py"


def _fixture(tmp_path):
    project = tmp_path / "project"
    source = project / "src/beamo_wipe"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text('__version__ = "0.2.9"\n')
    (source / "payload.py").write_text("PAYLOAD = 'A'\n")
    (source / "build_identity.py").write_text(
        "def assert_injectable(**kwargs): pass\n"
        "def injected_payload(**kwargs): return kwargs\n"
    )
    (source / "compat_story.py").write_text(
        "def inject_helper_html(text, **kwargs):\n"
        "    return (text.replace('not packaged', kwargs['injected']['build_id'])\n"
        "                .replace('source status', 'production')\n"
        "                + '<!-- packaged -->')\n"
    )
    (source / "release_manifest.py").write_text(
        "import hashlib\n"
        "from pathlib import Path\n"
        "ROOT = Path(__file__).resolve().parents[2]\n"
        "def git_commit(): return 'a' * 40\n"
        "def git_dirty(): return (False, [])\n"
        "def live_build_inputs():\n"
        "    h = hashlib.sha256()\n"
        "    for path in sorted((ROOT / 'src/beamo_wipe').rglob('*')):\n"
        "        if not path.is_file() or '__pycache__' in path.parts or path.suffix in {'.pyc', '.pyo'}: continue\n"
        "        name = str(path.relative_to(ROOT)).encode()\n"
        "        digest = hashlib.sha256(path.read_bytes()).hexdigest().encode()\n"
        "        h.update(f'{len(name)}:'.encode() + name)\n"
        "        h.update(f'{len(digest)}:'.encode() + digest)\n"
        "    return {'src/beamo_wipe/': h.hexdigest()}\n"
    )
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(["git", "add", "src/beamo_wipe"], cwd=project, check=True)
    for name in ("index.html", "fr.html", "de.html"):
        path = project / "helper" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"<html>{name}: not packaged; source status</html>\n")
    for name in ("finished.wav", "attention.wav"):
        path = project / "packaging/sounds" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
    for name in (
        "Start Beamo Wipe.exe",
        "Start Beamo Wipe Linux",
        "desktop-build.json",
    ):
        path = project / "dist/desktop" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
        if name == "Start Beamo Wipe Linux":
            path.chmod(0o755)
    for name in ("GO-LICENSE.txt", "GO-PATENTS.txt"):
        path = project / "desktop" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    (project / "desktop/go.mod").write_text("module fixture\n")
    (project / "desktop/main.go").write_text("package main\nfunc main() {}\n")
    (project / "dist/desktop/desktop-build.json").write_text(
        json.dumps(
            {
                "version": "0.2.9",
                "source_commit": "a" * 40,
                "source_sha256": desktop_source_digest(project),
                "source_dirty": False,
                "go": GO_VERSION,
                "files": {
                    name: hashlib.sha256(
                        (project / "dist/desktop" / name).read_bytes()
                    ).hexdigest()
                    for name in ("Start Beamo Wipe.exe", "Start Beamo Wipe Linux")
                },
            }
        )
    )
    for name in ("NOTICE", "LICENSE", "THIRD_PARTY.md"):
        (project / name).write_text(name)
    live = project / "packaging/live"
    entrypoint = live / "config/includes.chroot/usr/local/bin/beamo-wipe"
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_text("#!/bin/sh\n")
    entrypoint.chmod(0o755)
    hook = live / "config/hooks/normal/0500-build-nwipe.hook.chroot"
    hook.parent.mkdir(parents=True)
    hook.write_text("#!/bin/sh\n")
    hook.chmod(0o755)
    subprocess.run(
        [
            "git",
            "add",
            "packaging/live/config/includes.chroot/usr/local/bin/beamo-wipe",
        ],
        cwd=project,
        check=True,
    )
    subprocess.run([sys.executable, str(STAGER), "--prepare", str(live)], check=True)
    subprocess.run(
        [
            sys.executable,
            str(STAGER),
            str(project),
            str(
                live / "config/includes.chroot/usr/lib/python3/dist-packages/beamo_wipe"
            ),
        ],
        check=True,
    )
    return project, live, source


def test_stage_live_assets_normal_and_link_leaf(tmp_path):
    project, live, _source = _fixture(tmp_path)
    binary = live / "config/includes.binary"
    foreign = tmp_path / "foreign.html"
    foreign.write_text("foreign")
    (binary / "START-HERE.html").symlink_to(foreign)

    result = subprocess.run(
        [sys.executable, str(ASSETS), str(project), str(live)],
        cwd=project,
        env={**os.environ, "BUILD_ID": "local"},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert foreign.read_text() == "foreign"
    assert "packaged" in (binary / "START-HERE.html").read_text()
    for language in ("fr", "de"):
        localized = (
            live
            / "config/includes.chroot/usr/share/beamo-wipe/helper"
            / f"{language}.html"
        )
        localized_text = localized.read_text()
        assert "local; production" in localized_text
        assert "not packaged" not in localized_text
    assert (
        json.loads((binary / "build-identity.json").read_text())["build_id"] == "local"
    )
    assert (binary / "Start Beamo Wipe.exe").read_bytes() == b"Start Beamo Wipe.exe"
    assert (binary / "Start Beamo Wipe Linux").stat().st_mode & 0o111
    assert (
        live / "config/includes.chroot/usr/share/beamo-wipe/sounds/attention.wav"
    ).read_bytes() == b"attention.wav"


def test_stage_live_assets_refuses_source_changed_after_wrapper_stage(tmp_path):
    project, live, source = _fixture(tmp_path)
    (source / "payload.py").write_text("PAYLOAD = 'B'\n")

    result = subprocess.run(
        [sys.executable, str(ASSETS), str(project), str(live)],
        cwd=project,
        env={**os.environ, "BUILD_ID": "local"},
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "staged wrapper" in result.stderr


def test_stage_live_assets_refuses_earlier_asset_changed_during_staging(tmp_path):
    project, live, _source = _fixture(tmp_path)
    code = (
        "from pathlib import Path; import sys; "
        "sys.path.insert(0, sys.argv[1]); import stage_live_assets as assets; "
        "original = assets.install_bytes; "
        "\n"
        "def install_then_alter(path, data, **kwargs):\n"
        "    original(path, data, **kwargs)\n"
        "    if path.name == 'README.txt':\n"
        "        (path.parent / 'START-HERE.html').write_bytes(b'foreign')\n"
        "assets.install_bytes = install_then_alter\n"
        "assets.stage_assets(Path(sys.argv[2]), Path(sys.argv[3]))\n"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            str(ROOT / "scripts"),
            str(project),
            str(live),
        ],
        cwd=project,
        env={**os.environ, "BUILD_ID": "local"},
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "staged asset changed" in result.stderr


def test_stage_live_assets_refuses_earlier_asset_mode_changed_during_staging(tmp_path):
    project, live, _source = _fixture(tmp_path)
    code = (
        "from pathlib import Path; import os, sys; "
        "sys.path.insert(0, sys.argv[1]); import stage_live_assets as assets; "
        "original = assets.install_bytes; "
        "\n"
        "def install_then_chmod(path, data, **kwargs):\n"
        "    original(path, data, **kwargs)\n"
        "    if path.name == 'README.txt':\n"
        "        os.chmod(path.parent / 'START-HERE.html', 0o666)\n"
        "assets.install_bytes = install_then_chmod\n"
        "assets.stage_assets(Path(sys.argv[2]), Path(sys.argv[3]))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(ROOT / "scripts"), str(project), str(live)],
        cwd=project,
        env={**os.environ, "BUILD_ID": "local"},
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "staged asset changed" in result.stderr


def test_stage_live_assets_refuses_unreviewed_chroot_include(tmp_path):
    project, live, _source = _fixture(tmp_path)
    injected = live / "config/includes.chroot/etc/.env"
    injected.parent.mkdir(parents=True, exist_ok=True)
    injected.write_text("UNREVIEWED=present\n")

    result = subprocess.run(
        [sys.executable, str(ASSETS), str(project), str(live)],
        cwd=project,
        env={**os.environ, "BUILD_ID": "local"},
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0, result.stderr
    assert "unreviewed live include" in result.stderr
