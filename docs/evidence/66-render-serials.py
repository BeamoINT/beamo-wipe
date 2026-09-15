# SPDX-License-Identifier: GPL-3.0-or-later
"""Reproduce #66 picker renders using synthetic test fixtures only.

Run from the repo root with PYTHONPATH=src:tests under isolated 72-DPI Xvfb.
Arguments: near|long|duplicate|missing OUTPUT_DIRECTORY.
"""
import sys
import time
from pathlib import Path

from PIL import ImageGrab

from beamo_wipe import gallery
from beamo_wipe.models import Screen
from beamo_wipe.ui.tk_wizard import TkWizard
from test_serial_comparison import comparison_wizard

SCENARIOS = {
    "near": ("ABC123XYZ", "ABC124XYZ"),
    "long": ("A" * 240 + "X" + "Z" * 80, "A" * 240 + "Y" + "Z" * 80),
    "duplicate": ("ABC123XYZ", "ABC123XYZ"),
    "missing": ("", "ABC124XYZ"),
}

if __name__ == "__main__":
    name, output = sys.argv[1], Path(sys.argv[2])
    output.mkdir(parents=True, exist_ok=True)
    wizard = comparison_wizard(SCENARIOS[name])
    wizard.screen = Screen.PICK
    app = TkWizard(wizard)
    try:
        app.root.geometry("1024x740+0+0")
        app._draw()
        for _ in range(15):
            app.root.update()
            time.sleep(0.05)
        ImageGrab.grab().save(output / f"{name}-tk.png")
    finally:
        app._teardown()
    gallery.discovery_for_scenario = lambda _: wizard.discovery
    (output / f"{name}.html").write_text(gallery.gallery_html(), encoding="utf-8")
