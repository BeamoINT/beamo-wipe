"""Deterministic picker geometry and Tcl callback lifetime regressions."""

from types import SimpleNamespace

import pytest

try:
    import tkinter as tk
    from beamo_wipe.ui.tk_wizard import TkWizard
except ImportError:
    pytest.skip("tkinter not available", allow_module_level=True)


class Canvas(tk.Misc):
    """Real Tcl timers plus the Canvas geometry/clamping needed by restoration."""

    def __init__(self):
        self.interpreter = tk.Tcl()
        self.tk = self.interpreter.tk
        self._tclCommands = []
        self.height = 400
        self.content = 1000
        self.top = 0.0

    def bbox(self, _tag):
        return (0, 0, 500, self.content)

    def winfo_height(self):
        return self.height

    def yview(self):
        return (self.top / self.content, min(1.0, (self.top + self.height) / self.content))

    def yview_moveto(self, fraction):
        self.top = max(0.0, min(self.content - self.height, fraction * self.content))

    def geometry(self, *, height, content):
        self.height = height
        self.content = content
        # Canvas clamps a previously valid origin when its viewport/content changes.
        self.yview_moveto(self.top / self.content)


class Card:
    y = 900
    height = 60

    def winfo_y(self):
        return self.y

    def winfo_height(self):
        return self.height


def picker():
    app = object.__new__(TkWizard)
    canvas = Canvas()
    card = Card()
    app.w = SimpleNamespace(selected=SimpleNamespace(path="fake-disk"))
    app._pick_canvas = canvas
    app._pick_cards = {"fake-disk": card}
    app._pick_restore_pending = True
    app._pick_ensure_visible = True
    app._pick_applied = None
    app._pick_applied_geometry = None
    app._pick_after_ids = []
    app._pick_scroll = 0.0
    app._pick_gen = 1
    return app, canvas, card


@pytest.mark.parametrize("change", ["viewport", "content"])
def test_layout_clamping_does_not_cancel_selected_card_restoration(change):
    app, canvas, card = picker()
    app._pick_restore_scroll()
    assert canvas.top == 560
    if change == "viewport":
        canvas.geometry(height=1000, content=1000)
    else:
        canvas.geometry(height=400, content=500)
        card.y = 420
    app._pick_restore_scroll()
    assert app._pick_restore_pending, "layout clamping was mistaken for manual scrolling"
    card.y = 900
    canvas.geometry(height=400, content=1000)
    app._pick_restore_scroll()
    assert canvas.top <= card.y
    assert card.y + card.height <= canvas.top + canvas.height


def test_direct_scroll_with_stable_geometry_keeps_user_position():
    app, canvas, _card = picker()
    app._pick_restore_scroll()
    canvas.yview_moveto(0.1)
    app._pick_restore_scroll()
    app._pick_restore_tick(1, final=True)
    assert canvas.top == 100
    assert not app._pick_restore_pending


class RedrawReachedClear(Exception):
    pass


def test_redraw_cancels_canvas_timers_before_destroying_tcl_commands():
    app, canvas, _card = picker()
    errors = []
    canvas.tk.createcommand("bgerror", errors.append)
    app._pick_after_ids = [canvas.after(0, lambda: app._pick_restore_tick(1))]
    app._draw_generation = 0
    app._body = object()
    app._footer = object()

    def clear(_frame):
        canvas.destroy()
        raise RedrawReachedClear

    app._clear = clear
    with pytest.raises(RedrawReachedClear):
        app._draw()
    canvas.tk.eval("update")
    assert errors == [], "redraw left an after event whose Tcl command was deleted"


def test_teardown_cancels_canvas_timers_before_destroying_tcl_commands():
    app, canvas, _card = picker()
    errors = []
    canvas.tk.createcommand("bgerror", errors.append)
    app._pick_after_ids = [canvas.after(0, lambda: app._pick_restore_tick(1))]
    app.root = canvas
    app._return_release_after = None
    app._space_release_after = None
    app._after_id = None
    app._teardown()
    canvas.tk.eval("update")
    assert errors == [], "teardown left an after event whose Tcl command was deleted"
