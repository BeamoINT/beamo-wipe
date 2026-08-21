# SPDX-License-Identifier: GPL-3.0-or-later
"""Plain data types. No I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple


class DiskKind(str, Enum):
    HDD = "HDD"
    SSD = "SSD"
    NVME = "NVMe"
    UNKNOWN = "Unknown"


class MethodId(str, Enum):
    EVERYDAY = "everyday"
    EXTRA = "extra"
    QUICK_ZERO = "quick_zero"


class Screen(str, Enum):
    SPLASH = "splash"
    WHAT = "what"
    OWNER = "owner"
    PICK = "pick"
    PICK_BLOCKED = "pick_blocked"
    PICK_EMPTY = "pick_empty"
    CONFIRM = "confirm"
    METHOD = "method"
    LAST_CHANCE = "last_chance"
    WORKING = "working"
    DONE = "done"
    ADVANCED = "advanced"


@dataclass(frozen=True)
class Disk:
    path: str
    name: str
    model: str
    serial: str
    size_bytes: int
    size_gb_label: str
    kind: DiskKind
    bus: str
    label: str
    is_boot: bool = False
    wwn: str = ""
    vendor: str = ""
    mountpoints: Tuple[str, ...] = ()

    @property
    def display_name(self) -> str:
        return self.model or self.label or self.name

    @property
    def size_phrase(self) -> str:
        return f"{self.size_gb_label} GB"


@dataclass(frozen=True)
class ConfirmSpec:
    token: str
    prompt: str


@dataclass(frozen=True)
class WipeRequest:
    device: str
    method: MethodId
    boot_device: str
    logfile: str
    # Linux st_rdev of the target at confirm time. 0 when the node is absent
    # (unit tests / dry-run). Re-checked immediately before exec.
    device_rdev: int = 0
    device_size_bytes: int = 0


@dataclass(frozen=True)
class WipeResult:
    ok: bool
    exit_code: int
    summary: str
    logfile: str


@dataclass
class DiscoveryResult:
    disks: Tuple[Disk, ...] = field(default_factory=tuple)
    selectable: Tuple[Disk, ...] = field(default_factory=tuple)
    boot: Optional[Disk] = None
    error: Optional[str] = None
    boot_identified: bool = False
