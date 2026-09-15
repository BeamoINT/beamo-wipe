# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared disk identity for every owner-facing screen.

Kernel device names are for binding a wipe, never stable identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from beamo_wipe.copy import kind_label
from beamo_wipe.models import Disk

UNKNOWN_MODEL = "Unknown model"
CONNECTION_UNKNOWN = "Connection unknown"
SERIAL_NOT_REPORTED = "Serial not reported"
HARDWARE_ID_LABEL = "Hardware ID"
SERIAL_LABEL = "Serial"
MISSING_SERIAL = (
    "This disk did not report a serial number. "
    "Do not treat the connection name as the disk."
)
MISSING_SERIAL_HARDWARE_ID = (
    "This disk did not report a serial number. The hardware ID is shown instead."
)
CONFIRM_HARDWARE_ID = "Use the hardware ID shown here to identify this disk."
DUPLICATE_ID = (
    "Two disks report the same serial or hardware ID. "
    "If you cannot tell them apart, shut down and disconnect the extra drives."
)
AMBIGUOUS_IDENTITY = (
    "These disks look too similar to tell apart safely. "
    "Shut down. Disconnect the drives you do not want to erase. "
    "Start from this USB again. Do not guess."
)
SYSTEM_PATH_NOTE = "System name (not a stable identity)"

_CONNECTION = {
    "USB": "USB",
    "SATA": "SATA",
    "NVMe": "NVMe",
    "SAS": "SAS",
}


@dataclass(frozen=True)
class DiskIdentityView:
    title: str
    capacity: str
    connection: str
    kind_chip: str
    id_label: str
    id_value: str
    missing_note: str
    duplicate_note: str
    ambiguous_note: str
    system_path: str
    confirmable: bool
    comparison_start: int = 0
    comparison_end: int = 0
    comparison_note: str = ""

    @property
    def marked_id(self) -> str:
        if self.comparison_end <= self.comparison_start:
            return self.id_value
        a, b = self.comparison_start, self.comparison_end
        return f"{self.id_value[:a]}[{self.id_value[a:b]}]{self.id_value[b:]}"

    @property
    def announcement(self) -> str:
        parts = [self.title, self.capacity]
        if self.kind_chip:
            parts.append(self.kind_chip)
        if self.connection:
            parts.append(self.connection)
        parts.append(f"{self.id_label}: {self.id_value}")
        parts.extend(self.notes)
        return "; ".join(parts)

    @property
    def compact_line(self) -> str:
        return f"{self.title}  {self.capacity}  {self.connection}  {self.id_label} {self.id_value}"

    @property
    def notes(self) -> tuple[str, ...]:
        return tuple(
            note
            for note in (self.missing_note, self.duplicate_note, self.ambiguous_note, self.comparison_note)
            if note
        )

    def payload(self) -> dict[str, str | bool]:
        return {
            "title": self.title,
            "capacity": self.capacity,
            "connection": self.connection,
            "kind": self.kind_chip,
            "id_label": self.id_label,
            "id_value": self.id_value,
            "missing_note": self.missing_note,
            "duplicate_note": self.duplicate_note,
            "ambiguous_note": self.ambiguous_note,
            "announcement": self.announcement,
            "confirmable": self.confirmable,
        }


def display_title(disk: Disk) -> str:
    title = (disk.model or "").strip() or (disk.label or "").strip()
    return title or UNKNOWN_MODEL


def connection_label(disk: Disk) -> str:
    bus = (disk.bus or "").strip()
    if bus in _CONNECTION:
        return _CONNECTION[bus]
    return CONNECTION_UNKNOWN


def strongest_identifier(disk: Disk) -> tuple[str, str]:
    serial = (disk.serial or "").strip()
    if serial:
        return "serial", serial
    wwn = (disk.wwn or "").strip()
    if wwn:
        return "wwn", wwn
    return "missing", ""


def _norm(value: str) -> str:
    return (value or "").strip().casefold()


def duplicate_identifier(disk: Disk, peers: Sequence[Disk]) -> bool:
    serial = _norm(disk.serial)
    wwn = _norm(disk.wwn)
    for other in peers:
        if other.path == disk.path:
            continue
        if serial and _norm(other.serial) == serial:
            return True
        if wwn and _norm(other.wwn) == wwn:
            return True
    return False


def present_disk(
    disk: Disk, peers: Iterable[Disk] = (), *, compare_serials: bool = False
) -> DiskIdentityView:
    """Present raw identity; pickers may opt into comparison guidance."""
    from beamo_wipe.safety import SafetyError, confirm_spec
    from beamo_wipe.inventory import serial_comparison

    listed = tuple(peers)
    kind, value = strongest_identifier(disk)
    try:
        spec = confirm_spec(disk, listed)
    except SafetyError:
        spec = None
    if spec is not None and spec.identity_field == "wwn":
        kind, value = "wwn", (disk.wwn or "").strip()
    if kind == "serial":
        id_label, id_value, missing = SERIAL_LABEL, value, ""
    elif kind == "wwn":
        id_label, id_value = HARDWARE_ID_LABEL, value
        missing = CONFIRM_HARDWARE_ID if (disk.serial or "").strip() else MISSING_SERIAL_HARDWARE_ID
    else:
        id_label, id_value, missing = SERIAL_LABEL, SERIAL_NOT_REPORTED, MISSING_SERIAL
    start, end, comparison = serial_comparison(disk, listed) if compare_serials else (0, 0, "")
    confirmable = spec is not None

    return DiskIdentityView(
        title=display_title(disk),
        capacity=disk.size_phrase,
        connection=connection_label(disk),
        kind_chip=kind_label(disk.kind),
        id_label=id_label,
        id_value=id_value,
        missing_note=missing,
        duplicate_note=DUPLICATE_ID if duplicate_identifier(disk, listed) else "",
        ambiguous_note="" if confirmable else AMBIGUOUS_IDENTITY,
        system_path=disk.path,
        confirmable=confirmable,
        comparison_start=start,
        comparison_end=end,
        comparison_note=comparison,
    )


def identity_confirmable(disk: Disk, peers: Sequence[Disk]) -> bool:
    from beamo_wipe.safety import SafetyError, confirm_spec

    try:
        confirm_spec(disk, peers)
    except SafetyError:
        return False
    return True
