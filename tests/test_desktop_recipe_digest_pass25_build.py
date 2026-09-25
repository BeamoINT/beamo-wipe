"""Cached launchers must be rebuilt when their build recipe changes."""

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_cached_launcher_rejects_changed_build_recipe(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    recipe = scripts / "build_desktop.py"
    shutil.copyfile(ROOT / "scripts/build_desktop.py", recipe)
    spec = importlib.util.spec_from_file_location("beamo_test_recipe_digest", recipe)
    assert spec is not None and spec.loader is not None
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)

    desktop = tmp_path / "desktop"
    desktop.mkdir()
    (desktop / "go.mod").write_text("module example.test/launcher\n")
    (desktop / "main.go").write_text("package main\nfunc main() {}\n")
    output = tmp_path / "dist" / "desktop"
    output.mkdir(parents=True)
    files = {}
    for name in builder.LAUNCHERS:
        data = name.encode()
        (output / name).write_bytes(data)
        files[name] = hashlib.sha256(data).hexdigest()
    manifest = {
        "version": "0.2.9",
        "source_commit": "a" * 40,
        "source_sha256": builder.desktop_source_digest(tmp_path),
        "source_dirty": True,
        "go": builder.GO_VERSION,
        "files": files,
    }
    (output / "desktop-build.json").write_text(json.dumps(manifest))
    builder.verify_desktop_bundle(tmp_path, output, "a" * 40, "0.2.9", True)

    recipe.write_text(recipe.read_text() + "\n# Changed compiler recipe.\n")
    with pytest.raises(RuntimeError, match="different desktop source inputs"):
        builder.verify_desktop_bundle(tmp_path, output, "a" * 40, "0.2.9", True)
