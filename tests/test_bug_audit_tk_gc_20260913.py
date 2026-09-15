# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise actual Tcl interpreter destruction in an isolated subprocess."""

import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


@pytest.mark.parametrize("first_outcome", ["wizard", "failed", "abandoned"])
def test_startup_releases_tcl_before_later_worker_collection(first_outcome):
    pytest.importorskip("tkinter")
    from beamo_wipe.ui.tk_wizard import _ensure_tk_display

    try:
        _ensure_tk_display()
    except RuntimeError:
        pytest.skip("Tk display unavailable")
    script = textwrap.dedent('''
        import gc
        import sys
        import threading
        from beamo_wipe.ui import tk_wizard as ui
        from beamo_wipe.startup_stages import STAGE_BOOT_USB, STAGE_FINDING

        # The parent already probed the display; keep all native work in this
        # bounded process so a timeout cannot orphan another display probe.
        ui._ensure_tk_display = lambda: None
        mode = sys.argv[1]
        release = threading.Event()
        workers = []
        real_tk = ui.tk.Tk
        def bounded_root():
            root = real_tk()
            root.after(3000, root.destroy)
            if mode == "abandoned":
                root.after(100, lambda: root.tk.call(root.protocol("WM_DELETE_WINDOW")))
            return root
        ui.tk.Tk = bounded_root
        # Defer automatic collection so the later worker deterministically
        # collects every cycle left by the first startup; this intentionally
        # exposes wrong-thread Tcl destruction instead of concealing it.
        gc.disable()
        def first(report):
            workers.append(threading.current_thread())
            report(STAGE_BOOT_USB)
            if mode == "abandoned":
                assert release.wait(5)
            report(STAGE_FINDING)
            if mode == "failed":
                raise OSError("fake discovery failure")
            return "first"
        try:
            outcome = ui.run_tk_startup(first)
            assert outcome[0] == mode, outcome
            release.set()
            for worker in workers:
                worker.join(5)
                assert not worker.is_alive()
            ui.tk.Tk = real_tk
            def second(report):
                gc.collect()
                report(STAGE_BOOT_USB)
                report(STAGE_FINDING)
                return "second"
            assert ui.run_tk_startup(second) == ("wizard", "second")
            print("startup-and-worker-gc-ok", flush=True)
        finally:
            release.set()
            gc.enable()
            gc.collect()
    ''')
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(root / "src"), PYTHONFAULTHANDLER="1")
    result = subprocess.run(
        [sys.executable, "-c", script, first_outcome],
        cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stdout
    assert "startup-and-worker-gc-ok" in result.stdout


@pytest.mark.parametrize("failed_step", ["start", "mainloop"])
def test_startup_exception_closes_its_window(monkeypatch, failed_step):
    pytest.importorskip("tkinter")
    from unittest.mock import MagicMock
    from beamo_wipe.startup_stages import StartupRun
    from beamo_wipe.ui import tk_wizard as ui

    root = MagicMock()
    monkeypatch.setattr(ui, "_ensure_tk_display", lambda: None)
    monkeypatch.setattr(ui.tk, "Tk", lambda: root)
    monkeypatch.setattr(ui.tk, "Frame", MagicMock())
    monkeypatch.setattr(ui.tk, "Label", MagicMock())
    monkeypatch.setattr(StartupRun, "start", MagicMock())
    failure = RuntimeError("fake startup interface failure")
    if failed_step == "start":
        StartupRun.start.side_effect = failure
    else:
        root.mainloop.side_effect = failure
    with pytest.raises(RuntimeError, match="fake startup interface failure"):
        ui.run_tk_startup(lambda report: "fake-wizard")
    root.destroy.assert_called_once_with()
