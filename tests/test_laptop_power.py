# SPDX-License-Identifier: GPL-3.0-or-later
"""Power telemetry uses temporary sysfs fixtures and fake operations only."""
import threading
import time

import pytest

from beamo_wipe import copy as C
from beamo_wipe.power import PowerMonitor, PowerStatus, read_power


def supply(root, name, **values):
    folder = root / name
    folder.mkdir(exist_ok=True)
    (folder / 'uevent').write_text(''.join(f'POWER_SUPPLY_{key.upper()}={value}\n' for key, value in values.items()))


@pytest.mark.parametrize('online,expected', [('1', True), ('0', False), ('?', None), ('2', None)])
def test_ac_is_reported_not_inferred(tmp_path, online, expected):
    supply(tmp_path, 'AC', type='Mains', online=online)
    supply(tmp_path, 'BAT0', type='Battery', present=1, capacity=80)
    result = read_power(tmp_path)
    assert result.ac is expected
    assert result.batteries == (80,)
    assert 'reported' in result.text


@pytest.mark.parametrize('value,expected,low', [('0', 0, True), ('19', 19, True), ('20', 20, True), ('21', 21, False), ('100', 100, False), ('101', None, False), ('-1', None, False), ('nan', None, False), ('50.5', None, False)])
def test_charge_boundaries(tmp_path, value, expected, low):
    supply(tmp_path, 'BAT', type='Battery', present=1, capacity=value)
    result = read_power(tmp_path)
    assert result.batteries == (expected,)
    assert result.low is low
    assert ('Low battery' in result.text) is low
    assert result.ac is None  # charging/full are never substitutes for AC data


def test_absent_unknown_desktop_and_peripherals(tmp_path):
    assert read_power(tmp_path).text == 'Wall power: unknown. No system battery reported.'
    assert 'unavailable' in read_power(tmp_path / 'missing').text
    supply(tmp_path, 'mouse', type='Battery', scope='Device', present=1, capacity=1)
    supply(tmp_path, 'BAT', type='Battery', present=0, capacity=70)
    assert read_power(tmp_path).batteries == ()
    supply(tmp_path, 'BAT', type='Battery', capacity=70)
    result = read_power(tmp_path)
    assert result.batteries == (None,)
    assert 'unknown' in result.text


def test_multiple_supplies_and_partial_charge(tmp_path):
    supply(tmp_path, 'BAT0', type='Battery', present=1, capacity=55)
    supply(tmp_path, 'BAT1', type='Battery', present=1, capacity=12)
    supply(tmp_path, 'BAT2', type='Battery', present=1)
    supply(tmp_path, 'AC', type='Mains', online=0)
    supply(tmp_path, 'USB', type='USB_PD', scope='System', online=1)
    result = read_power(tmp_path)
    assert result.ac is True
    assert result.low
    assert 'lowest available charge: 12%' in result.text
    assert '1 charge reading unavailable' in result.text


def test_unreadable_duplicate_and_oversized_data(tmp_path, monkeypatch):
    supply(tmp_path, 'AC', type='Mains', online=1)
    event = tmp_path / 'AC' / 'uevent'
    event.write_text('POWER_SUPPLY_TYPE=Mains\nPOWER_SUPPLY_ONLINE=1\nPOWER_SUPPLY_ONLINE=0\n')
    assert read_power(tmp_path).ac is None
    event.write_text('x' * 9000)
    assert read_power(tmp_path).ac is None
    monkeypatch.setattr('pathlib.Path.open', lambda *a, **kw: (_ for _ in ()).throw(PermissionError()))
    assert read_power(tmp_path).ac is None


def test_unprefixed_uevent_fields_do_not_claim_wall_power(tmp_path):
    # Linux power_supply uevents use POWER_SUPPLY_ keys. A malformed record
    # must not become a reported AC connection just because it says ONLINE=1.
    folder = tmp_path / 'AC'
    folder.mkdir()
    (folder / 'uevent').write_text('TYPE=Mains\nONLINE=1\n')
    status = read_power(tmp_path)
    assert status.ac is None
    assert not status.complete


def test_generic_uevent_metadata_does_not_hide_power_supply_readings(tmp_path):
    # The real sysfs uevent can include a generic DEVTYPE line alongside
    # POWER_SUPPLY_ fields; it is metadata rather than a power reading.
    folder = tmp_path / 'AC'
    folder.mkdir()
    (folder / 'uevent').write_text(
        'DEVTYPE=power_supply\nPOWER_SUPPLY_TYPE=Mains\nPOWER_SUPPLY_ONLINE=1\n'
    )
    status = read_power(tmp_path)
    assert status.ac is True
    assert status.complete


def drain(monitor, now):
    for _ in range(100):
        monitor.tick(now)
        if not monitor.pending:
            return
        time.sleep(.005)
    pytest.fail('fake reader did not finish')


def test_power_changes_during_long_operation_and_failure():
    state = [PowerStatus(ac=True, batteries=(80,), complete=True)]
    def read():
        if isinstance(state[0], Exception):
            raise state[0]
        return state[0]
    monitor = PowerMonitor(read)
    drain(monitor, 0)
    assert monitor.status.ac is True
    for now in range(5, 3601, 5):
        state[0] = PowerStatus(ac=False, batteries=(10,), complete=True)
        drain(monitor, now)
        assert monitor.status.low
    state[0] = OSError('unplugged')
    drain(monitor, 3605)
    assert monitor.status.ac is None
    state[0] = PowerStatus(ac=True, batteries=(30,), complete=True)
    drain(monitor, 3610)
    assert monitor.status.ac is True


def test_slow_reader_expires_without_blocking_or_spawning_more_workers():
    release = threading.Event()
    calls = []
    def read():
        calls.append(1)
        release.wait(2)
        return PowerStatus(ac=True, batteries=(90,), complete=True)
    monitor = PowerMonitor(read)
    try:
        start = time.monotonic()
        monitor.tick(0)
        monitor.tick(11)
        assert time.monotonic() - start < .2
        assert monitor.status.ac is None
        for now in range(12, 20):
            monitor.tick(now)
        assert len(calls) <= 1
    finally:
        release.set()
    drain(monitor, 20)
    assert monitor.status.ac is None  # discard a reading taken before timeout


def test_dry_run_never_reads_host_power(monkeypatch):
    from beamo_wipe.demo import make_demo_wizard
    monkeypatch.setattr('beamo_wipe.power.read_power', lambda: pytest.fail('host read'))
    wizard = make_demo_wizard()
    wizard.tick()
    assert 'Preview' in wizard.power_text
    assert 'unknown' in wizard.power_text


def test_shared_guidance_includes_lid_and_hardware_limits():
    assert 'keep the lid open' in C.POWER_REMINDER.lower()
    assert 'keep the lid open' in C.WORKING_PULSE.lower()
    assert 'held power button' in C.POWER_EVENTS.lower()
    assert 'firmware' in C.POWER_EVENTS.lower()


def test_inhibitor_failure_and_unexpected_exit_never_claim_active(monkeypatch):
    from beamo_wipe.sleep_inhibit import SleepInhibit
    monkeypatch.setenv('BEAMO_WIPE_LIVE', '1')
    monkeypatch.delenv('BEAMO_WIPE_DRY_RUN', raising=False)
    def denied(*args, **kwargs):
        raise OSError('no logind')
    monkeypatch.setattr('beamo_wipe.sleep_inhibit.subprocess.Popen', denied)
    inhibit = SleepInhibit()
    inhibit.start()
    assert not inhibit.active
    inhibit.stop()
    class Exited:
        def poll(self):
            return 1
    monkeypatch.setattr('beamo_wipe.sleep_inhibit.subprocess.Popen', lambda *a, **kw: Exited())
    inhibit.start()
    assert not inhibit.active
    inhibit.stop()
    assert not inhibit.active


def test_wizard_power_changes_do_not_authorize_or_stop_an_operation():
    from beamo_wipe.demo import make_demo_wizard
    from beamo_wipe.models import Screen
    wizard = make_demo_wizard()
    wizard.screen = Screen.WORKING
    wizard.selected = wizard.selectable[0]
    before = (wizard.selected, wizard.confirm_input, wizard.owner_ok, wizard._authorized_operation)
    for state in (PowerStatus(ac=True, batteries=(90,), complete=True), PowerStatus(ac=False, batteries=(0,), complete=True), PowerStatus()):
        wizard.power.status = state
        wizard.tick()
        assert wizard.screen == Screen.WORKING
        assert not wizard.wants_shutdown
        assert (wizard.selected, wizard.confirm_input, wizard.owner_ok, wizard._authorized_operation) == before


def test_concurrent_polling_still_has_one_reader():
    release = threading.Event()
    calls = []
    def read():
        calls.append(1)
        release.wait(2)
        return PowerStatus()
    monitor = PowerMonitor(read)
    pollers = [threading.Thread(target=monitor.tick, args=(0,)) for _ in range(20)]
    try:
        for poller in pollers:
            poller.start()
        for poller in pollers:
            poller.join(1)
            assert not poller.is_alive()
        assert len(calls) == 1
    finally:
        release.set()
    drain(monitor, 0)
