"""Capture presentation fixtures; run only on a private Xvfb with dry run set.

These screenshots do not prove execution. Runtime tests exercise the flows.
"""
import argparse
import os
from pathlib import Path
import sys
import time

sys.path[:0] = [str(Path.cwd() / "src"), str(Path.cwd() / "tests")]

import gi

gi.require_version("Gdk", "3.0")
from gi.repository import Gdk
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen
from beamo_wipe.ui.accessible_wizard import AccessibleWizard
from beamo_wipe.ui.tk_wizard import TkWizard
from test_accessible_runtime import drain, wait_for_window_size
from test_result_presentations import CASES, case_evidence

parser = argparse.ArgumentParser()
parser.add_argument("output", type=Path)
parser.add_argument("--view", choices=["tk", "gtk"], required=True)
parser.add_argument("--size", default="800x600")
args = parser.parse_args()
assert os.environ.get("BEAMO_ISOLATED_X11_TEST") == "1"
assert os.environ.get("BEAMO_WIPE_DRY_RUN") == "1"
width, height = map(int, args.size.split("x"))
args.output.mkdir(parents=True, exist_ok=True)


def fixture(screen):
    wizard = make_demo_wizard()
    wizard.skip_splash()
    wizard.accept_what()
    wizard.set_owner(True)
    wizard.continue_owner()
    wizard.select_disk(sorted(wizard.selectable, key=lambda d: d.path)[0].path)
    wizard.continue_pick()
    wizard.set_confirm_input(wizard.confirm.token)
    wizard.continue_confirm()
    wizard.continue_method()
    wizard.screen = screen
    return wizard


fixtures = [(s.value, fixture(s)) for s in Screen]
fixtures += [("result-" + case[0], case_evidence(case)[0]) for case in CASES]
for name, wizard in fixtures:
    if args.view == "gtk":
        app = AccessibleWizard(wizard)
        app.window.move(0, 0)
        app.window.resize(width, height)
        wait_for_window_size(app.window, (width, height))
        pump, close = drain, app.close
    else:
        app = TkWizard(wizard)
        app.root.geometry(f"{width}x{height}+0+0")
        app.root.after_cancel(app._after_id)
        app._after_id = None
        pump, close = app.root.update, app._teardown
    for _ in range(12):
        pump()
        time.sleep(0.02)
    pixbuf = Gdk.pixbuf_get_from_window(
        Gdk.get_default_root_window(), 0, 0, width, height
    )
    pixbuf.savev(str(args.output / f"{args.view}-{name}.png"), "png", [], [])
    close()
print(f"Captured {len(fixtures)} {args.view} states at {args.size}")
