"""A broken diagnostic import cannot skip GTK erase ownership settlement."""

import sys

from test_audit_20260907_console_input import _working
from test_accessible_refresh_async_regression import _headless_accessible_module


def test_runtime_failure_settles_active_engine_when_diagnostics_unavailable(
    monkeypatch, tmp_path
):
    module = _headless_accessible_module(monkeypatch)
    wizard = _working(monkeypatch, tmp_path)
    app = module.AccessibleWizard.__new__(module.AccessibleWizard)
    app.w = wizard
    app.failed = False
    closed = []
    app.close = lambda: closed.append(True)
    monkeypatch.setitem(sys.modules, "beamo_wipe.diagnostics", None)

    app._runtime_failure(RuntimeError, RuntimeError("fake toolkit error"), None)

    assert app.failed
    assert wizard.runner.cancelled
    assert wizard.wipe_result is not None
    assert closed == [True]
