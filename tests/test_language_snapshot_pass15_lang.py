"""A first language switch must preserve the original English surface."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("first", ["fr", "de"])
def test_fresh_process_restores_english_after_first_translation(first):
    script = """
from beamo_wipe import lang
modules = lang._modules()
keys = lang._tables('fr')
original = {
    (module_name, name): getattr(modules[module_name], name)
    for module_name, table in keys.items() for name in table
}
lang.set_language(FIRST)
lang.set_language('en')
changed = [
    (module_name, name) for (module_name, name), value in original.items()
    if getattr(modules[module_name], name) != value
]
assert not changed, f'{len(changed)} English values were not restored: {changed[:3]}'
""".replace("FIRST", repr(first))
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
