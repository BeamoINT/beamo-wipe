"""Orca cleanup cannot replace the accessible UI's outcome."""

import ast
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest


def _reader_functions():
    source = Path(__file__).parents[1] / "src/beamo_wipe/ui/accessible_wizard.py"
    tree = ast.parse(source.read_text())
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"stop_live_reader", "run_accessible"}
    ]
    namespace = {"subprocess": subprocess, "Wizard": object}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), namespace)  # noqa: S102
    return namespace


def test_orca_exit_race_does_not_mask_successful_ui_outcome():
    namespace = _reader_functions()
    calls = []

    class Reader:
        def poll(self):
            return None

        def terminate(self):
            calls.append("terminate")
            raise ProcessLookupError("Orca exited after poll")

        def wait(self, timeout):
            calls.append(("wait", timeout))
            return 0

    namespace["start_live_reader"] = Reader
    namespace["AccessibleWizard"] = lambda *_args: SimpleNamespace(run=lambda: 7)

    assert namespace["run_accessible"](object()) == 7
    assert calls == ["terminate", ("wait", 5)]


def test_orca_stuck_after_kill_does_not_mask_ui_failure():
    namespace = _reader_functions()
    calls = []

    class Reader:
        def poll(self):
            return None

        def terminate(self):
            calls.append("terminate")

        def wait(self, timeout):
            calls.append(("wait", timeout))
            raise subprocess.TimeoutExpired("orca", timeout)

        def kill(self):
            calls.append("kill")

    namespace["start_live_reader"] = Reader

    def fail_ui(*_args):
        return SimpleNamespace(run=lambda: (_ for _ in ()).throw(ValueError("UI failed")))

    namespace["AccessibleWizard"] = fail_ui
    with pytest.raises(ValueError, match="UI failed"):
        namespace["run_accessible"](object())
    assert calls == ["terminate", ("wait", 5), "kill", ("wait", 5)]
