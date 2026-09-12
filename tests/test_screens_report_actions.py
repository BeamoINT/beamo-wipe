# SPDX-License-Identifier: GPL-3.0-or-later
"""docs/screens.md Working/Finished rows match the shipped report actions."""

from __future__ import annotations

from pathlib import Path

from beamo_wipe import copy as C

ROOT = Path(__file__).resolve().parents[1]
SCREENS = ROOT / "docs" / "screens.md"


def _row(name: str) -> str:
    for line in SCREENS.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"| {name} |"):
            return line
    raise AssertionError(f"screens.md has no {name} row")


def test_working_row_documents_cancel_interactivity():
    row = _row("Working")
    assert "Cancel erase" in row
    assert "Shut down is not offered" in row
    assert "indeterminate" in row


def test_finished_row_documents_report_actions():
    row = _row("Finished")
    assert C.BTN_SAVE_REPORT in row  # "Save report to USB"
    assert C.BTN_SHUTDOWN in row  # "Shut down"
    assert "Retry evidence save" in row
    assert C.BTN_RUN_AGAIN in row  # "Run again"
    assert C.BTN_CLOSE_PREVIEW in row  # "Close preview"
    assert "Finished" in row and "Erase result" in row
    assert "verification was not performed" in row
