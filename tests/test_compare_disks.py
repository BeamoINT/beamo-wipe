"""Read-only comparison of fake eligible disks."""
from dataclasses import replace

import pytest

from beamo_wipe import inventory
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen
from beamo_wipe.ui import console_wizard as console


def test_comparison_retains_complete_identity_and_uncertainty():
    w = make_demo_wizard()
    disk = w.selectable[0]
    peers = (
        replace(disk, serial="LONG" * 100),
        replace(disk, path="/dev/sdz", model="", label="", serial="", wwn="WWN123", bus=""),
        replace(disk, path="/dev/sdy", serial="", wwn=""),
    )
    text = inventory.comparison_text(peers)
    for value in ("LONG" * 100, "Unknown model", "Serial not reported",
                  "Hardware ID: WWN123", "Connection unknown", "Capacity:", "do not guess"):
        assert value in text
    assert len(inventory.comparison_entries(peers)) == 3


def test_comparison_is_fail_closed_and_does_not_authorize():
    w = make_demo_wizard()
    w.screen = Screen.PICK
    w.select_disk(w.selectable[0].path)
    selected = w.selected
    state = (w.owner_ok, w.screen, w.typing_check)
    text = inventory.comparison_text(w.selectable)
    assert all(d.serial not in text for d in w.listed_disks if d.is_boot and d.serial)
    assert w.selected is selected
    assert (w.owner_ok, w.screen, w.typing_check) == state
    assert not w.runner.started
    w.discovery = replace(w.discovery, boot_identified=False)
    assert not inventory.comparison_entries(w.selectable)


@pytest.mark.parametrize("count,width,columns", [(2,900,2), (7,900,2), (7,500,1)])
def test_tk_comparison_reflow_keyboard_and_continuity(count, width, columns):
    from test_tk_runtime import _needs_display
    _needs_display()
    import tkinter as tk
    from beamo_wipe.ui.tk_wizard import TkWizard
    w = make_demo_wizard()
    sample = w.selectable[0]
    disks = tuple(replace(sample, path=f"/dev/sd{chr(97+i)}", serial=f"SERIAL-{i}-" + "X"*180)
                  for i in range(count))
    w.discovery = replace(w.discovery, disks=disks, selectable=disks)
    w.screen = Screen.PICK
    w.select_disk(w.selectable[-1].path)
    selected = w.selected
    app = TkWizard(w)
    try:
        host = tk.Toplevel(app.root)
        host.geometry(f"{width}x600")
        app._comparison(host)
        host.update()
        section = host.winfo_children()[0]
        from beamo_wipe.ui.tk_wizard import _CheckRow
        toggle = next(c for c in section.winfo_children() if isinstance(c, _CheckRow))
        toggle.invoke()
        host.update()
        content = next(c for c in section.winfo_children() if isinstance(c, tk.Frame))
        grid = next(c for c in content.winfo_children() if isinstance(c, tk.Frame))
        cells = grid.winfo_children()
        readers = [next(c for c in cell.winfo_children() if isinstance(c, tk.Text)) for cell in cells]
        assert len(readers) == count
        assert {int(r.grid_info()["column"]) for r in cells} == set(range(columns))
        assert all(r.winfo_width() <= width for r in readers)
        for r in readers:
            assert "X"*180 in r.get("1.0", "end")
            assert r.cget("state") == "disabled"
        readers[0].focus_force()
        readers[0].event_generate("<Down>")
        readers[0].event_generate("<Return>")
        host.update()
        assert w.selected is selected and w.screen == Screen.PICK
        readers[0].event_generate("<Tab>")
        host.update()
        assert host.focus_get() is readers[1]
        toggle.invoke()
        host.update()
        assert not content.winfo_ismapped()
        assert w.selected is selected and not w.runner.started
    finally:
        app._teardown()


def test_console_offers_read_only_comparison():
    w = make_demo_wizard()
    w.screen = Screen.PICK
    assert any("Compare disks (C)" in line for line in console._primary_footer(w, False))


def test_console_comparison_scroll_and_escape_preserve_selection(monkeypatch):
    from test_console_parity import _draw
    w = make_demo_wizard()
    w.screen = Screen.PICK
    w.select_disk(w.selectable[1].path)
    selected = w.selected
    _, _, terminal = _draw(monkeypatch, w, w=40, h=16,
                          keys=[ord("c"), console.curses.KEY_NPAGE, 10, 27])
    rendered = " ".join(" ".join(frame.values()) for frame in terminal.frames)
    assert inventory.COMPARE_TITLE in rendered
    assert "Model:" in rendered and "Serial:" in rendered
    assert w.selected is selected and w.screen == Screen.PICK
    assert not w.runner.started


@pytest.mark.parametrize("width,columns", [(1100, 2), (390, 1)])
def test_browser_comparison_keyboard_reflow_and_selection(tmp_path, width, columns):
    import shutil
    from beamo_wipe.gallery import write_gallery
    playwright = pytest.importorskip("playwright.sync_api")
    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    if not chrome:
        pytest.skip("Chrome unavailable")
    path = write_gallery(tmp_path / "index.html")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome, args=["--no-sandbox"])
        try:
            page = browser.new_page(viewport={"width": width, "height": 800})
            page.goto(path.as_uri() + "#s=pick&disk=1&owner=1")
            summary = page.get_by_text(inventory.COMPARE_TITLE, exact=True)
            summary.focus()
            page.keyboard.press("Enter")
            assert page.locator("details").evaluate("(e) => e.open")
            cards = page.locator("details pre")
            assert cards.count() == 3
            assert "Model:" in cards.first.inner_text()
            assert page.locator("details").evaluate("(e) => e.scrollWidth <= e.clientWidth")
            boxes = [cards.nth(i).bounding_box() for i in range(2)]
            assert (abs(boxes[0]["y"] - boxes[1]["y"]) < 2) == (columns == 2)
            page.keyboard.press("Tab")
            assert cards.first.evaluate("(e) => document.activeElement === e")
            assert page.evaluate("selected.path") == "/dev/sda"
            summary.focus()
            page.keyboard.press("Enter")
            assert not page.locator("details").evaluate("(e) => e.open")
            assert page.evaluate("selected.path") == "/dev/sda"
            assert page.evaluate("screen") == "pick"
        finally:
            browser.close()


def test_gtk_comparison_disclosure_is_read_only():
    pytest.importorskip("gi")
    from beamo_wipe.ui.accessible_wizard import AccessibleWizard, Gtk
    from test_accessible_runtime import drain, widgets
    w = make_demo_wizard()
    w.screen = Screen.PICK
    w.select_disk(w.selectable[0].path)
    selected = w.selected
    app = AccessibleWizard(w)
    try:
        drain()
        expander = next(widget for widget in widgets(app.window)
                        if isinstance(widget, Gtk.Expander))
        assert expander.get_label() == inventory.COMPARE_TITLE
        expander.set_expanded(True)
        drain()
        reader = expander.get_child()
        assert reader.get_selectable() and reader.get_can_focus()
        assert reader.get_text() == inventory.comparison_text(w.selectable)
        reader.grab_focus()
        drain()
        assert app.window.get_focus() is reader
        expander.set_expanded(False)
        drain()
        assert w.selected is selected and w.screen == Screen.PICK
        assert not w.runner.started
    finally:
        app.close()
        drain()


def test_equal_capacity_candidates_are_adjacent_without_renumbering_picker():
    w = make_demo_wizard()
    entries = inventory.comparison_entries(w.selectable)
    assert {entry.split("\n")[0] for entry in entries[:2]} == {"Disk 1", "Disk 3"}
    assert entries[2].startswith("Disk 2\n")
    assert "Capacity: 256 GB" in entries[0] and "Capacity: 256 GB" in entries[1]


def test_comparison_keeps_duplicate_warning_from_protected_peer():
    from beamo_wipe.identity import DUPLICATE_ID
    w = make_demo_wizard()
    disk = w.selectable[0]
    protected = replace(disk, path="/dev/sdz", is_boot=True)
    entries = inventory.comparison_entries([disk], peers=[disk, protected])
    assert len(entries) == 1
    assert DUPLICATE_ID in entries[0]


def test_real_picker_comparison_keeps_selection_and_reveals_keyboard_focus():
    from test_tk_runtime import _needs_display
    _needs_display()
    import tkinter as tk
    from beamo_wipe.ui.tk_wizard import TkWizard
    w = make_demo_wizard()
    sample = w.selectable[0]
    disks = tuple(replace(sample, path=f"/dev/vd{chr(97+i)}", serial=f"SERIAL-{i}")
                  for i in range(7))
    w.discovery = replace(w.discovery, disks=disks, selectable=disks)
    w.screen = Screen.PICK
    w.select_disk(disks[-1].path)
    selected = w.selected
    app = TkWizard(w)
    def walk(widget):
        yield widget
        for child in widget.winfo_children():
            yield from walk(child)
    try:
        app.root.update()
        from beamo_wipe.ui.tk_wizard import _CheckRow
        toggle = next(widget for widget in walk(app.root)
                      if isinstance(widget, _CheckRow)
                      and widget.cget("text") == inventory.COMPARE_TITLE)
        toggle.focus_force()
        toggle.event_generate("<Return>")
        toggle.event_generate("<KeyRelease-Return>")
        app.root.update()
        readers = [widget for widget in walk(app.root) if isinstance(widget, tk.Text)
                   and widget.get("1.0", "end").startswith("Disk ")]
        assert len(readers) == 7 and readers[0].winfo_ismapped()
        readers[-1].focus_force()
        app.root.update()
        canvas = app._pick_canvas
        assert 0 <= readers[-1].winfo_rooty() - canvas.winfo_rooty() < canvas.winfo_height()
        for key in ("Down", "Return", "space"):
            readers[-1].event_generate(f"<{key}>")
            app.root.update()
        assert w.selected is selected and w.screen == Screen.PICK
        assert not w.runner.started
        toggle.invoke()
        app.root.update()
        assert not readers[0].winfo_ismapped()
        assert w.selected is selected
    finally:
        app._teardown()
