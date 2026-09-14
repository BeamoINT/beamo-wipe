# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only Linux power telemetry. Readings are reports, never safety gates."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
import threading
from typing import Callable

LOW_PERCENT = 20
REFRESH_SECONDS = 5.0
STALE_SECONDS = 10.0
EXTERNAL_TYPES = {'Mains', 'USB', 'USB_DCP', 'USB_CDP', 'USB_ACA', 'USB_C', 'USB_PD', 'USB_PD_DRP', 'Wireless'}


@dataclass(frozen=True)
class PowerStatus:
    ac: bool | None = None
    batteries: tuple[int | None, ...] = ()
    complete: bool = False

    @property
    def low(self) -> bool:
        return any(value is not None and value <= LOW_PERCENT for value in self.batteries)

    @property
    def text(self) -> str:
        ac = {True: 'connected (reported)', False: 'not detected (reported)', None: 'unknown'}[self.ac]
        parts = [f'Wall power: {ac}.']
        if len(self.batteries) == 1:
            value = self.batteries[0]
            parts.append('Battery charge: unknown.' if value is None else f'Battery: {value}% reported.')
        elif self.batteries:
            known = [v for v in self.batteries if v is not None]
            parts.append(f'{len(self.batteries)} batteries reported; ' +
                         (f'lowest available charge: {min(known)}%.' if known else 'charge unknown.'))
            missing = self.batteries.count(None)
            if missing:
                parts.append(f'{missing} charge reading unavailable.' if missing == 1 else f'{missing} charge readings unavailable.')
        elif self.complete:
            parts.append('No system battery reported.')
        if not self.complete:
            parts.append('Some power information is unavailable.')
        if self.low:
            parts.append('Low battery. Check wall power now.')
        elif self.ac is False and self.batteries:
            parts.append('Connect wall power now.')
        return ' '.join(parts)


def _event(folder: Path) -> dict[str, str]:
    # sysfs provides one coherent event record. Bound reads and reject
    # duplicates rather than combining conflicting values or raw device text.
    with (folder / 'uevent').open('rb') as stream:
        data = stream.read(8193)
    if len(data) > 8192:
        raise ValueError('oversized power record')
    result: dict[str, str] = {}
    for line in data.decode('ascii').splitlines():
        key, sep, value = line.partition('=')
        key = key.removeprefix('POWER_SUPPLY_')
        if not sep or key in result:
            raise ValueError('malformed power record')
        result[key] = value
    return result


def read_power(root: Path = Path('/sys/class/power_supply')) -> PowerStatus:
    try:
        folders = sorted(root.iterdir())
    except OSError:
        return PowerStatus()
    if len(folders) > 32:
        return PowerStatus()
    external: list[bool | None] = []
    batteries: list[int | None] = []
    complete = True
    for folder in folders:
        try:
            event = _event(folder)
        except (OSError, ValueError, UnicodeError):
            complete = False
            continue
        if event.get('SCOPE') == 'Device':
            continue
        if event.get('SCOPE') not in (None, 'System'):
            complete = False
            continue
        kind = event.get('TYPE')
        if kind == 'Battery':
            if event.get('PRESENT') == '0':
                continue
            raw = event.get('CAPACITY', '')
            value = int(raw) if raw.isascii() and raw.isdecimal() and len(raw) <= 3 else -1
            batteries.append(value if event.get('PRESENT') == '1' and 0 <= value <= 100 else None)
        elif kind in EXTERNAL_TYPES:
            external.append({'0': False, '1': True}.get(event.get('ONLINE', '')))
        else:
            complete = False
    ac = True if True in external else (False if external and all(v is False for v in external) and complete else None)
    return PowerStatus(ac=ac, batteries=tuple(batteries), complete=complete)


class PowerMonitor:
    """One bounded worker; UI polls cached state, never waits on a driver.

    A stuck driver can retain one daemon worker, but no replacement workers
    accumulate. Late results expire, and failure replaces earlier good data.
    The worker captures only a reader and queue, never a wizard/Tk interpreter.
    """
    def __init__(self, reader: Callable[[], PowerStatus] | None = None):
        self.reader = reader
        self.status = PowerStatus()
        self.pending = False
        self._results: Queue[PowerStatus] = Queue(maxsize=1)
        self._started = 0.0
        self._sampled: float | None = None
        self._next = 0.0
        self._lock = threading.Lock()

    def tick(self, now: float) -> None:
        with self._lock:
            self._tick(now)

    def _tick(self, now: float) -> None:
        if self.reader is None:
            return
        if self.pending:
            try:
                result = self._results.get_nowait()
            except Empty:
                pass
            else:
                self.pending = False
                self.status = result if now - self._started <= STALE_SECONDS else PowerStatus()
                self._sampled = self._started
                self._next = now + REFRESH_SECONDS
        if self._sampled is not None and now - self._sampled > STALE_SECONDS:
            self.status = PowerStatus()
        if self.pending and now - self._started > STALE_SECONDS:
            self.status = PowerStatus()
        if not self.pending and now >= self._next:
            reader, results = self.reader, self._results
            def read() -> None:
                try:
                    value = reader()
                    if not isinstance(value, PowerStatus):
                        value = PowerStatus()
                except Exception:
                    value = PowerStatus()
                results.put_nowait(value)
            self.pending = True
            self._started = now
            try:
                threading.Thread(target=read, daemon=True, name='beamo-power').start()
            except RuntimeError:
                self.pending = False
                self.status = PowerStatus()
                self._next = now + REFRESH_SECONDS
