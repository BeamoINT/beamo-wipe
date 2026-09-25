"""The GTK review starts only after its first frame is shown.

The local Mac has no ``gi``. A disposable subprocess supplies a minimal GTK
surface and fake clock; it exercises the real AccessibleWizard.render method.
"""

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_accessible_first_review_frame_restarts_full_countdown():
    script = r'''
import sys
from types import ModuleType, SimpleNamespace

class Widget:
    clock = None
    def __init__(self, text=""):
        self.text = text
        self.sensitive = True
    def get_child(self): return None
    def get_children(self): return []
    def get_accessible(self): return self
    def get_style_context(self): return self
    def get_text(self): return self.text
    def set_text(self, text): self.text = text
    def set_sensitive(self, value): self.sensitive = value
    def get_sensitive(self): return self.sensitive
    def get_window(self): return None
    def show_all(self):
        if self.clock is not None: self.clock.advance(6)
    def __getattr__(self, _name): return lambda *_args, **_kwargs: None

gtk = SimpleNamespace(
    Box=lambda **_kw: Widget(), ScrolledWindow=lambda: Widget(),
    Grid=lambda: Widget(),
    Orientation=SimpleNamespace(VERTICAL=1, HORIZONTAL=2),
    PolicyType=SimpleNamespace(NEVER=1, AUTOMATIC=2),
)
repo = ModuleType('gi.repository')
repo.Gtk = gtk
repo.Gdk = SimpleNamespace(CURRENT_TIME=0)
repo.GLib = SimpleNamespace()
repo.Pango = SimpleNamespace()
repo.Atk = SimpleNamespace(Role=SimpleNamespace(PANEL=1, ALERT=2))
gi = ModuleType('gi')
gi.require_version = lambda *_args: None
gi.repository = repo
sys.modules['gi'] = gi
sys.modules['gi.repository'] = repo

from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen
from beamo_wipe.nwipe_runner import DryRunRunner
from beamo_wipe.wizard import Wizard
from beamo_wipe.ui import accessible_wizard as accessible

class Clock:
    def __init__(self): self.value = 0.0
    def __call__(self): return self.value
    def advance(self, amount): self.value += amount

clock = Clock()
wizard = Wizard(make_demo_wizard().discovery, DryRunRunner(clock=clock),
                clock=clock, dry_run=True)
wizard.skip_intro()
wizard.set_owner(True)
wizard.continue_owner()
wizard.select_disk(wizard.selectable[0].path)
wizard.continue_pick()
wizard.set_confirm_input(wizard.confirm.token)
wizard.continue_confirm()
wizard.continue_method()
assert wizard.screen == Screen.LAST_CHANCE

ui = object.__new__(accessible.AccessibleWizard)
ui.w = wizard
ui.window = Widget()
ui.window.clock = clock
ui.generation = 0
ui.shown = Screen.METHOD
ui._style = Widget()
ui._apply_type_css = lambda: None
ui._style_tree = lambda _tree: None
ui.identity = lambda: None
ui.support_identity_labels = lambda: None
ui.label = lambda text, **_kw: Widget(text)
ui.button = lambda text, _action, **_kw: Widget(text)
accessible.emit_serial_marker = lambda _marker: None
ui.render()
assert clock.value == 6
assert not wizard.erase_enabled, 'first frame consumed visible review'
assert wizard.countdown_display == 5
assert ui.primary is not None and not ui.primary.get_sensitive()
'''
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
