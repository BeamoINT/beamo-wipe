# SPDX-License-Identifier: GPL-3.0-or-later
"""Real fake-disk UI regressions: identity visibility and details keyboard access."""
from dataclasses import replace

import pytest

from beamo_wipe import copy as C
from beamo_wipe.models import Screen
from beamo_wipe.ui.tk_wizard import _Button
from test_tk_runtime import ui, _drive_to  # noqa: F401


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


@pytest.mark.parametrize('size', [(1024, 740), (1280, 820)])
def test_full_device_identity_wraps_in_rows_and_summaries(ui, size):  # noqa: F811
    wiz, app = ui(size=size)
    _drive_to(wiz, app, Screen.PICK)
    disk = replace(wiz.selectable[0], model='Long model ' * 11, serial='ABCDEFGH12345678' * 8)
    parent = app._column(app._body, fill_height=True)
    row = app._disk_row(parent, disk, False)
    summary = app._disk_summary(parent, disk)
    summary.pack(fill='x')
    for _ in range(5):
        app.root.update()
    for container in (row, summary):
        labels = [w for w in descendants(container) if w.winfo_class() == 'Label'
                  and str(w.cget('text')).replace('\n', '') in (disk.display_name, disk.serial)]
        assert len(labels) == 2
        for label in labels:
            assert label.winfo_ismapped()
            assert label.winfo_reqwidth() <= label.winfo_width() + 2
            assert label.winfo_reqheight() <= label.winfo_height() + 2
            assert int(label.cget('wraplength')) > 0


def test_more_details_is_keyboard_control_and_keeps_focus(ui):  # noqa: F811
    wiz, app = ui()
    _drive_to(wiz, app, Screen.PICK)
    controls = [w for w in descendants(app.root) if isinstance(w, _Button)
                and w.itemcget(w._label, 'text') == C.BTN_MORE]
    assert len(controls) == 1
    controls[0].focus_force()
    app.root.update()
    app._on_return()
    app.root.update()
    assert wiz.screen == Screen.PICK
    assert app._show_more
    focus = app.root.focus_get()
    assert isinstance(focus, _Button)
    assert focus.itemcget(focus._label, 'text') == C.BTN_LESS
    app._on_return_release()
    app.root.update()
    app._on_return()
    app.root.update()
    assert not app._show_more
    assert wiz.screen == Screen.PICK


@pytest.mark.parametrize('screen', [Screen.CONFIRM, Screen.DONE])
def test_long_selected_identity_keeps_actions_visible(ui, screen):  # noqa: F811
    from test_tk_runtime import MIN_WINDOW, _clipping_problems, _off_window_problems
    wiz, app = ui(size=MIN_WINDOW)
    _drive_to(wiz, app, Screen.CONFIRM)
    wiz.selected = replace(wiz.selected, model='M' * 128, serial='A' * 128)
    wiz.screen = screen  # presentation only, no runner starts
    app._draw()
    for _ in range(5):
        app.root.update()
    assert not _clipping_problems(app)
    assert not _off_window_problems(app)
    assert app._primary.winfo_ismapped()


def test_result_tab_order_reaches_report_without_shutdown(ui, tmp_path):  # noqa: F811
    from unittest.mock import Mock
    from test_usb_report_workflow import _done_wizard, _success_receipt

    _, app = ui()
    app.w = wiz = _done_wizard(_success_receipt, tmp_path)
    save = Mock()
    app._click_save_report = save
    app._draw()
    app.root.update()
    assert app.root.focus_get() is app._primary
    assert app._primary.itemcget(app._primary._label, 'text') == C.BTN_SHUTDOWN
    # QEMU uses these same two Tab presses: the new keyboard-accessible
    # details control participates in the normal Tk traversal order.
    for title in (C.BTN_MORE, C.BTN_SAVE_REPORT):
        next_control = app.root.focus_get().tk_focusNext()
        next_control.focus_force()
        app.root.update()
        assert isinstance(next_control, _Button)
        assert next_control.itemcget(next_control._label, 'text') == title
    next_control._key()
    save.assert_called_once_with()
    assert not wiz.wants_shutdown


@pytest.mark.parametrize('screen', [Screen.PICK, Screen.CONFIRM, Screen.LAST_CHANCE, Screen.WORKING, Screen.DONE])
def test_device_path_is_visible_without_expanding_details(ui, screen):  # noqa: F811
    wiz, app = ui(size=(1024, 740))
    _drive_to(wiz, app, Screen.CONFIRM)
    wiz.screen = screen  # presentation only
    app._draw()
    app.root.update()
    assert not app._show_more
    view = wiz.disk_view(wiz.selected)
    texts = [w.cget('text') for w in descendants(app.root) if w.winfo_class() == 'Label']
    assert view.title in texts
    assert view.id_value in texts
    assert any(view.connection in (text or '') for text in texts)
    assert wiz.selected.path not in texts
    assert view.system_path == wiz.selected.path


def test_countdown_ready_still_explains_nothing_started(ui):  # noqa: F811
    from test_tk_runtime import _button_named
    wiz, app = ui(size=(1024, 740))
    _drive_to(wiz, app, Screen.LAST_CHANCE)
    assert 'Nothing starts automatically' in app._countdown_label.cget('text')
    wiz._erase_until = 0
    app._refresh_last_chance()
    assert 'Nothing has started' in app._countdown_label.cget('text')
    assert app._countdown_num.cget('text') == '0'
    assert app.root.focus_get() is _button_named(app, C.BTN_BACK)
    assert not wiz.runner.started


def test_wheel_over_disk_identity_scrolls_without_selecting(ui):  # noqa: F811
    wiz, app = ui(size=(1024, 740))
    _drive_to(wiz, app, Screen.PICK)
    canvas = app._pick_canvas
    canvas.yview_moveto(0)
    selected = wiz.selected
    label = next(w for w in descendants(app._pick_cards[selected.path])
                 if w.winfo_class() == 'Label' and w.cget('text') == selected.serial)
    before = canvas.yview()[0]
    label.event_generate('<MouseWheel>', delta=-120)
    app.root.update()
    assert canvas.yview()[0] > before
    assert wiz.selected == selected
    assert wiz.screen == Screen.PICK


@pytest.mark.parametrize('size', [(1366, 768), (1920, 1080)])
@pytest.mark.parametrize('screen', list(Screen))
def test_wizard_fits_supported_desktop_sizes(ui, size, screen):  # noqa: F811
    from test_tk_runtime import _clipping_problems, _off_window_problems
    wiz, app = ui(size=size)
    _drive_to(wiz, app, Screen.CONFIRM)
    wiz.screen = screen  # presentation only
    app._draw()
    app.root.update()
    assert not _clipping_problems(app)
    assert not _off_window_problems(app)
