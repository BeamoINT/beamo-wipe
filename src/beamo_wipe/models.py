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
    REPORT_HELP = "report_help"
    LIMITS = "limits"
    REFRESHING = "refreshing"
    DIAGNOSTIC = "diagnostic"


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
    read_only: bool = False
    wwn: str = ""
    vendor: str = ""
    mountpoints: Tuple[str, ...] = ()
    # ``model`` is presentation text and may fall back to a volume label or
    # "Unknown model".  None means a caller did not provide raw identity
    # metadata; discovery always sets this to the exact cleaned lsblk MODEL,
    # including an empty string when MODEL is absent.
    raw_model: Optional[str] = None

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
    # Boot-medium identity recorded at the confirmation boundary. Production
    # rechecks it immediately before exec so a hotplug/rename cannot redirect
    # --exclude to a different node.
    boot_rdev: int = 0


@dataclass(frozen=True)
class WipeResult:
    ok: bool
    exit_code: int
    summary: str
    logfile: str
    reason: str = ""


@dataclass
class DiscoveryResult:
    disks: Tuple[Disk, ...] = field(default_factory=tuple)
    selectable: Tuple[Disk, ...] = field(default_factory=tuple)
    boot: Optional[Disk] = None
    error: Optional[str] = None
    boot_identified: bool = False
    # Legacy local troubleshooting detail, excluded from startup reports.
    # UI shows `error`; startup support exports only the allowlisted error_code.
    diagnostic: Optional[str] = None
    # Display-only inventory. Never a source of selectable Disk objects.
    excluded: Tuple[ExcludedDevice, ...] = ()
    error_code: str = ""


@dataclass(frozen=True)
class ExcludedDevice:
    identity: str
    reasons: Tuple[str, ...]

    @property
    def explanation(self) -> str:
        return f"{self.identity}\nCannot erase: {'; '.join(self.reasons)}."
