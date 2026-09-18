# SPDX-License-Identifier: GPL-3.0-or-later
"""Display-only serial comparisons; all disks are synthetic."""
from dataclasses import replace

import pytest

from beamo_wipe.identity import present_disk
from beamo_wipe.models import Disk, DiskKind
from beamo_wipe.safety import SafetyError, confirm_spec


def comparison_view(disk, peers):
    return present_disk(disk, peers, compare_serials=True)


def disks(*serials):
    return tuple(Disk(path=f"/dev/sd{chr(99+i)}", name=f"sd{chr(99+i)}",
                      model="Same model", serial=serial, size_bytes=500_000_000_000,
                      size_gb_label="500", kind=DiskKind.HDD, bus="SATA", label="")
                 for i, serial in enumerate(serials))


@pytest.mark.parametrize("serials, spans", [
    (("ABC123XYZ", "ABC124XYZ"), ((5, 6), (5, 6))),
    (("ABC123XYZ", "ABC124XYZ", "ABC923XYZ"), ((3, 6),) * 3),
    (("A", "AB"), ((0, 0), (1, 2))),
    (("ABC", "ABCD"), ((0, 0), (3, 4))),
    (("ABC", "ABXC"), ((0, 0), (2, 3))),
    (("A" * 240 + "X" + "Z" * 80, "A" * 240 + "Y" + "Z" * 80),
     ((240, 241), (240, 241))),
    (("ABCD", "WXYZ"), ((0, 4), (0, 4))),
    (("aBC1", "AbC2"), ((3, 4), (3, 4))),
])
def test_comparison_preserves_all_differences_and_raw_identity(serials, spans):
    peers = disks(*serials)
    before = [confirm_spec(d, peers) for d in peers]
    for disk, (start, end) in zip(peers, spans):
        view = comparison_view(disk, peers)
        assert (view.comparison_start, view.comparison_end) == (start, end)
        assert view.id_value == disk.serial
        assert view.comparison_note in view.notes
        assert view.comparison_note in view.announcement
        if end:
            assert view.marked_id == disk.serial[:start] + '[' + disk.serial[start:end] + ']' + disk.serial[end:]
            assert f"character{'s' if end-start > 1 else ''} {start+1}" in view.comparison_note
        else:
            assert view.marked_id == disk.serial
            assert f"Serial has {len(disk.serial)} character" in view.comparison_note
        assert "Check the full ID before choosing" in view.comparison_note
    assert [confirm_spec(d, peers) for d in peers] == before


@pytest.mark.parametrize("serials", [("ABC", "ABC"), ("ABC", "abc"), ("ABC", ""), ("", "")])
def test_no_highlight_for_duplicate_or_incomplete_comparison(serials):
    peers = disks(*serials)
    for disk in peers:
        view = comparison_view(disk, peers)
        assert view.marked_id == view.id_value
        assert view.comparison_note == ""
        if all(serials):
            assert view.duplicate_note
            assert not view.confirmable
            with pytest.raises(SafetyError):
                confirm_spec(disk, peers)


def test_duplicate_pair_with_unique_third_serial():
    peers = disks("ABC1", "ABC1", "ABC2")
    assert not comparison_view(peers[0], peers).comparison_note
    assert comparison_view(peers[2], peers).marked_id == "ABC[2]"


def test_group_matches_displayed_size_and_ignores_model():
    a, b = disks("ABC1", "ABC2")
    assert not comparison_view(a, (a,)).comparison_note
    assert not comparison_view(a, (a, replace(b, size_gb_label="501"))).comparison_note
    b = replace(b, model="Different model", size_bytes=b.size_bytes + 1)
    assert comparison_view(a, (a, b)).marked_id == "ABC[1]"
    assert not comparison_view(replace(a, is_boot=True), (a, b)).comparison_note


def test_missing_serial_hardware_id_is_not_marked():
    a, b = disks("", "ABC2")
    a = replace(a, wwn="hardware-123")
    view = comparison_view(a, (a, b))
    assert view.id_value == "hardware-123"
    assert view.marked_id == view.id_value
    assert view.missing_note and not view.comparison_note


def test_highlight_is_not_confirmation_token():
    peers = disks("ABC123XYZ", "ABC124XYZ")
    for disk in peers:
        view = comparison_view(disk, peers)
        assert view.id_value[view.comparison_start:view.comparison_end] != confirm_spec(disk, peers).token


def test_gallery_and_console_share_comparison(monkeypatch):
    from beamo_wipe import gallery
    from beamo_wipe.ui.console_wizard import _pick_blocks

    wizard = comparison_wizard()
    from beamo_wipe.models import Screen
    wizard.screen = Screen.PICK
    peers = wizard.selectable
    monkeypatch.setattr(gallery, "discovery_for_scenario", lambda _: wizard.discovery)
    payload = gallery._disks_payload()
    lines = '\n'.join(line for _, block in _pick_blocks(wizard, 76) for line in block)
    for disk in peers:
        view = comparison_view(disk, peers)
        item = next(d for d in payload if d['path'] == disk.path)
        assert item['serial'] == disk.serial
        assert item['markedSerial'] == view.marked_id
        assert item['comparisonNote'] == view.comparison_note
        assert "Compare serial character 6:" in lines
    html = gallery.gallery_html()
    assert 'esc(screen === "pick" && !d.isBoot ? d.markedSerial || d.serial : d.serial)' in html
    assert 'd.comparisonNote' in html


def comparison_wizard(serials=("ABC123XYZ", "ABC124XYZ")):
    from beamo_wipe.demo import discovery_for_scenario
    from beamo_wipe.nwipe_runner import DryRunRunner
    from beamo_wipe.wizard import Wizard
    peers = disks(*serials)
    base = discovery_for_scenario("happy")
    discovery = replace(base, selectable=peers,
                        disks=(*peers, next(d for d in base.disks if d.is_boot)))
    wizard = Wizard(discovery, DryRunRunner(), dry_run=True, rediscover=lambda: discovery)
    wizard.preview = True
    return wizard


def test_comparison_never_bypasses_owner_token_or_delay():
    from beamo_wipe.models import Screen
    wizard = comparison_wizard()
    wizard.skip_intro()
    wizard.accept_what()
    wizard.continue_owner()
    assert wizard.screen == Screen.OWNER
    wizard.set_owner(True)
    wizard.continue_owner()
    wizard.select_disk(wizard.discovery.boot.path)
    assert wizard.selected is None
    wizard.select_disk(wizard.selectable[0].path)
    view = wizard.disk_view()
    wizard.continue_pick()
    assert wizard.screen == Screen.CONFIRM
    for value in (view.id_value[view.comparison_start:view.comparison_end], view.marked_id):
        wizard.set_confirm_input(value)
        assert not wizard.token_ok
        wizard.continue_confirm()
        assert wizard.screen == Screen.CONFIRM
        assert not wizard.erase_enabled
    assert wizard.countdown_left == 5
    wizard.set_confirm_input(wizard.confirm.token)
    assert wizard.token_ok


@pytest.mark.parametrize("serials", [
    ("A" * 240 + "X" + "Z" * 80, "A" * 240 + "Y" + "Z" * 80),
    ('ABC<img src=x onerror="window.injected=true">1',
     'ABC<img src=x onerror="window.injected=true">2'),
])
def test_browser_comparison_wraps_and_escapes_metadata(monkeypatch, tmp_path, serials):
    import json
    import os
    import re
    import shutil
    import signal
    import subprocess
    from html import unescape
    from beamo_wipe import gallery

    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    if not chrome:
        pytest.skip("Chrome is unavailable")
    wizard = comparison_wizard(serials)
    monkeypatch.setattr(gallery, "discovery_for_scenario", lambda _: wizard.discovery)
    check = '''<script>
    window.addEventListener('load', () => {
      const rows = [...document.querySelectorAll('.pickable')].map(card => {
        const label = card.querySelector('.serial-label');
        const serial = card.querySelector('.ser');
        const range = document.createRange(); range.selectNodeContents(label);
        return {labelLines: range.getClientRects().length,
                injected: !!window.injected || !!card.querySelector('img'),
                serial: serial.textContent,
                fits: serial.getBoundingClientRect().right <= card.getBoundingClientRect().right};
      });
      document.documentElement.setAttribute('data-serial-check', JSON.stringify(rows));
    });
    </script>'''
    page = tmp_path / "gallery.html"
    page.write_text(gallery.gallery_html().replace('</body>', check + '</body>'))
    proc = subprocess.Popen(
        [chrome, '--headless=new', '--no-sandbox', '--disable-gpu',
         '--disable-dev-shm-usage', '--no-first-run',
         f'--user-data-dir={tmp_path / "chrome"}', '--window-size=1024,1160',
         '--dump-dom', page.as_uri() + '#s=pick'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=40)
    except subprocess.TimeoutExpired as exc:
        # Headless Chrome 148 can dump the DOM then hang until timeout.
        stdout, stderr = exc.stdout, exc.stderr
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", "replace")
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", "replace")
    stdout = stdout or ""
    stderr = stderr or ""
    match = re.search(r'data-serial-check="([^"]*)"', stdout)
    assert match, stderr
    rows = json.loads(unescape(match.group(1)))
    assert len(rows) == 2
    for row, disk in zip(rows, wizard.selectable):
        assert not row['injected']
        assert row['labelLines'] == 1
        assert row['fits']
        assert row['serial'] == comparison_view(disk, wizard.listed_disks).marked_id


def test_comparison_is_only_shown_while_choosing():
    from beamo_wipe.models import Screen
    wizard = comparison_wizard()
    disk = wizard.selectable[0]
    for screen in Screen:
        wizard.screen = screen
        view = wizard.disk_view(disk)
        assert bool(view.comparison_note) == (screen == Screen.PICK)
        assert view.id_value == disk.serial
        if screen != Screen.PICK:
            assert view.marked_id == disk.serial


def test_default_presentation_and_evidence_do_not_gain_picker_markers():
    peers = disks("ABC123XYZ", "ABC124XYZ")
    view = present_disk(peers[0], peers)
    assert not view.comparison_note
    assert view.marked_id == view.id_value == peers[0].serial
    assert "Compare serial" not in view.payload()["announcement"]


def test_duplicate_serial_at_another_capacity_is_not_highlighted():
    a, b, duplicate = disks("ABC1", "ABC2", "ABC1")
    peers = (a, b, replace(duplicate, size_gb_label="1000", size_bytes=1_000_000_000_000))
    view = comparison_view(a, peers)
    assert view.duplicate_note
    assert view.marked_id == view.id_value
    assert not view.comparison_note
    assert comparison_view(b, peers).marked_id == "ABC[2]"
