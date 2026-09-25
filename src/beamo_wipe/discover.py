# SPDX-License-Identifier: GPL-3.0-or-later
"""Turn lsblk JSON into Disk objects. No wiping. No guessing when unsure."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import unicodedata
from dataclasses import replace
from typing import Callable, Mapping, Any, Dict, Iterable, List, Optional, Sequence, Tuple

from beamo_wipe import copy as _copy
from beamo_wipe.startup_stages import STAGE_BOOT_USB, STAGE_FINDING
from beamo_wipe.models import (
    CONTENTS_DATA,
    CONTENTS_SYSTEM,
    CONTENTS_UNKNOWN,
    CONTENTS_WINDOWS,
    Disk,
    DiskKind,
    DiscoveryResult,
)
from beamo_wipe.safety import possible_hardware_alias

IDENTITY_UNAVAILABLE = "Device identity unavailable"
IDENTITY_UNCONFIRMED = "identity could not be confirmed"
UNKNOWN_MODEL = "Unknown model"

HIDDEN_TYPES = frozenset({"loop", "ram", "rom"})
# eMMC boot/RPMB hardware areas are type=disk siblings of mmcblk0. They are
# a few MiB and must never appear as "1 GB" wipe targets.
HIDDEN_NAME_RE = re.compile(
    r"^(loop|ram|zram|sr|fd|mmcblk\d+(?:boot\d+|rpmb))", re.IGNORECASE
)
LIVE_NAME_RE = re.compile(r"(live|casper|overlay)", re.IGNORECASE)
BOOT_LABELS = frozenset({"BEAMO_WIPE", "BEAMO-WIPE", "BEAMOWIPE"})
# GPT firmware partitions. Used only when the disk has no model: skip these
# so a Windows disk is not shown as "EFI".
FIRMWARE_LABELS = frozenset(
    {
        "EFI",
        "ESP",
        "BOOT",
        "GRUB",
        "BIOS",
        "SYSTEM",
        "BIOSBOOT",
        "EFI SYSTEM PARTITION",
        "SYSTEM RESERVED",
        "BIOS BOOT",
        "BIOS BOOT PARTITION",
    }
)
UDEV_BY_PREFIXES = (
    ("/dev/disk/by-uuid/", "UUID"),
    ("/dev/disk/by-partuuid/", "PARTUUID"),
    ("/dev/disk/by-label/", "LABEL"),
    ("/dev/disk/by-partlabel/", "PARTLABEL"),
)

LIVE_MOUNTS = (
    "/run/live/medium",
    "/lib/live/mount/medium",
    "/run/initramfs/live",
    "/cdrom",
    "/mnt/live",
    "/live/image",
    "/run/live/fromiso",
    "/lib/live/mount/fromiso",
)

# Kernel cmdline keys that name the live medium. Matched as whole tokens so
# a substring like debug=bootfrom= cannot steal identification.
CMDLINE_BOOT_RE = re.compile(
    r"(?:^|\s)(?:bootfrom|img_dev|live-media|boot_image)=(\S+)"
)
# Bare findmnt SOURCE names we will promote to /dev/*. Overlay/tmpfs/udev
# must not become /dev/overlay — that would look like a resolved boot path.
KERNEL_NAME_RE = re.compile(
    r"^(?:"
    r"sd[a-z]+\d*|hd[a-z]+\d*|vd[a-z]+\d*|xvd[a-z]+\d*|dasd[a-z]+\d*|"
    r"nvme\d+n\d+(?:p\d+)?|"
    r"mmcblk\d+(?:p\d+|boot\d+|rpmb)?|"
    r"sr\d+"
    r")$"
)
LSBLK_TIMEOUT_S = 15
FINDMNT_TIMEOUT_S = 8
# Absolute paths only. A PATH stub named `lsblk` must not feed fake JSON.
LSBLK_BINARIES = ("/usr/bin/lsblk",)
FINDMNT_BINARIES = ("/usr/bin/findmnt",)
MOUNTINFO_PATH = "/proc/self/mountinfo"
# PARTTYPE and PARTTYPENAME are read by classify_contents. Bookworm
# util-linux 2.38 supports both; dropping them makes Windows GUID evidence
# invisible and a real OS disk look like a data disk.
LSBLK_COLUMNS = (
    "NAME,PATH,SIZE,TYPE,TRAN,ROTA,MODEL,SERIAL,RM,HOTPLUG,"
    "MOUNTPOINT,MOUNTPOINTS,LABEL,FSTYPE,FSVER,VENDOR,PKNAME,UUID,WWN,"
    "PARTTYPE,PARTTYPENAME,PARTUUID,PARTLABEL,RO"
)
TYPED_SOURCE_KEYS = frozenset({"LABEL", "UUID", "PARTUUID", "PARTLABEL"})


def size_gb_label(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "0"
    # Integer half-up in decimal GB. Python 3 round() is banker's rounding, so
    # 2.5e9 became "2 GB" and collided with a 1.5e9 disk also labeled "2 GB".
    # Do not force a sub-0.5 GB disk up to 1: that shared a confirm token
    # with a real 1 GB disk.
    gb = (int(size_bytes) + 500_000_000) // 1_000_000_000
    return str(gb)


def classify_kind(name: str, tran: Optional[str], rota: Any) -> DiskKind:
    tran_l = (tran or "").lower().strip()
    # Harden: only exact tran tokens, not substring. Untrusted lsblk TRAN
    # could be spoofed as "my-nvme-evil". Require allowlisted values.
    if tran_l == "nvme":
        return DiskKind.NVME
    # name prefix is kernel name (e.g. nvme0n1), not model — still
    # cross-check with tran to avoid USB firmware spoofing tran="nvme"
    name_l = (name or "").lower().strip()
    if name_l.startswith("nvme") and tran_l in ("", "nvme"):
        return DiskKind.NVME
    rotational = _as_bool(rota)
    if rotational is False:
        return DiskKind.SSD
    if rotational is True:
        return DiskKind.HDD
    return DiskKind.UNKNOWN


def classify_bus(tran: Optional[str]) -> str:
    if not tran:
        return "other"
    # lsblk TRAN is untrusted padding-wise; strip like classify_kind does so
    # " usb " still groups as USB instead of a padded raw fallback.
    key = tran.lower().strip()
    if not key:
        return "other"
    mapping = {
        "nvme": "NVMe",
        "sata": "SATA",
        "ata": "SATA",
        "usb": "USB",
        "sas": "SAS",
        "spi": "other",
        # Distinct from empty TRAN ("other"): virtio-blk/scsi must stay
        # wipeable, while sd*/hd* with no proven local bus must not.
        "virtio": "virtio",
    }
    if key in mapping:
        return mapping[key]
    # Unknown transports stay visible but sanitized: strip control chars
    # (lsblk TRAN is untrusted; ANSI must not reach the UI or evidence)
    # and bound the length. The upper() shape is load-bearing:
    # safety.is_remote_disk matches bus.casefold() against remote tokens,
    # so this must never become UNKNOWN/"other" (that would make iSCSI/FC
    # wipeable).
    fallback = "".join(ch for ch in key if not _unsafe_text_character(ch)).upper()[:32]
    return fallback or "other"


def _as_bool(value: Any) -> Optional[bool]:
    if value is True or value is False:
        return value
    if isinstance(value, str):
        value = value.strip().lower()
    if value in (1, "1", "true"):
        return True
    if value in (0, "0", "false"):
        return False
    return None


def _as_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if not text:
        return 0
    try:
        return int(text)
    except (ValueError, OverflowError):
        try:
            return int(float(text))
        except (ValueError, OverflowError):
            try:
                from beamo_wipe.diagnostics import log_diag

                log_diag("discover", "size_parse_failed", f"type={type(value).__name__} length={len(text)}")
            except Exception:
                pass
            return 0


def _clean(value: Any) -> str:
    s = _clean_unbounded(value)
    if len(s) > 128:
        s = s[:128]
    return s


def _clean_unbounded(value: Any) -> str:
    if value is None:
        return ""
    # Untrusted lsblk metadata (model/serial/wwn/label) may contain control
    # chars, ANSI, newlines, or HTML. Strip control codes (0x00-0x1F, 0x7F),
    # truncate to 128 (display/evidence limit), and never pass raw to innerHTML.
    s = str(value)
    # Unicode line/paragraph separators (Zl/Zp) also create visual line
    # breaks, despite not being control characters. A drive must not use one
    # to impersonate another line in the picker or in a report.
    s = "".join(ch for ch in s if not _unsafe_text_character(ch))
    s = s.strip()
    return s


def _unsafe_text_character(ch: str) -> bool:
    category = unicodedata.category(ch)
    return category.startswith("C") or category in {"Zl", "Zp"}


def _bounded_identity_metadata(value: Any, field: str) -> str:
    """Sanitize display metadata without shortening the rediscovery identity."""
    if value is not None and any(
        _unsafe_text_character(ch) for ch in str(value)
    ):
        # Deleting controls can make two distinct raw labels, models or
        # vendors compare equal at the final rediscovery boundary.
        raise ValueError(f"lsblk {field} contains control characters")
    text = _clean_unbounded(value)
    if len(text) > 128:
        raise ValueError(f"lsblk {field} is too long")
    return text


def _layout_label(value: Any, field: str) -> str:
    """Keep raw label edges in the layout hash; UI cleanup happens elsewhere."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"lsblk {field} must be text")
    if len(value) > 128:
        raise ValueError(f"lsblk {field} is too long")
    if any(_unsafe_text_character(ch) for ch in value):
        raise ValueError(f"lsblk {field} contains control characters")
    return value


def _identity_text(value: Any, field: str) -> str:
    """Read an lsblk identity field without repairing it into another device."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"lsblk {field} must be text")
    if not value or not value.strip():
        return ""
    if any(_unsafe_text_character(ch) for ch in value):
        raise ValueError(f"lsblk {field} contains control characters")
    text = value.strip()
    if text != value or not text or len(text) > 128:
        raise ValueError(f"lsblk {field} is malformed")
    return text


def _hardware_identity(value: Any, field: str) -> str:
    """Keep a hardware ID intact or refuse it; an abbreviated ID is unsafe."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"lsblk {field} must be text")
    if any(_unsafe_text_character(ch) for ch in value):
        raise ValueError(f"lsblk {field} contains control characters")
    text = value.strip()
    if len(text) > 128:
        raise ValueError(f"lsblk {field} is too long")
    return text


def _node_mountpoints(node: Dict[str, Any]) -> List[str]:
    found: List[str] = []
    mps = node.get("mountpoints")
    if isinstance(mps, list):
        found.extend(_clean(x) for x in mps if x)
    elif mps is not None:
        # Some util-linux/schema variants emit a scalar. Treat it as mounted,
        # never as an empty list; malformed containers are rejected below.
        if not isinstance(mps, str):
            raise ValueError("lsblk mountpoints has invalid shape")
        mp = _clean(mps)
        if mp:
            found.append(mp)
    mp = _clean(node.get("mountpoint"))
    if mp:
        found.append(mp)
    for child in node.get("children") or []:
        found.extend(_node_mountpoints(child))
    return list(dict.fromkeys(x for x in found if x))


def node_path(node: Dict[str, Any]) -> str:
    path = _identity_text(node.get("path"), "path") if node.get("path") is not None else ""
    name = _identity_text(node.get("name"), "name") if node.get("name") is not None else ""
    return path or (f"/dev/{name}" if name else "")


def flatten_blockdevices(
    blockdevices: Sequence[Dict[str, Any]], parent: Optional[Dict[str, Any]] = None
) -> Iterable[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]]:
    if not isinstance(blockdevices, (list, tuple)):
        raise ValueError("lsblk JSON blockdevices must be a list")
    for node in blockdevices:
        if not isinstance(node, dict):
            raise ValueError("lsblk JSON node must be an object")
        yield node, parent
        children = node.get("children") or []
        if children and not isinstance(children, (list, tuple)):
            raise ValueError("lsblk JSON children must be a list")
        for child_pair in flatten_blockdevices(children, node):
            yield child_pair


def paths_under(node: Dict[str, Any]) -> List[str]:
    found = [node_path(node)]
    for child in node.get("children") or []:
        found.extend(paths_under(child))
    return found


def disk_nodes(blockdevices: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    disks = []
    for node, _parent in flatten_blockdevices(blockdevices):
        if (node.get("type") or "") == "disk":
            disks.append(node)
    return disks


def _path_aliases(path: str) -> set:
    aliases = {path}
    try:
        aliases.add(os.path.realpath(path))
    except OSError as exc:
        try:
            from beamo_wipe.diagnostics import log_diag

            log_diag("discover", "alias_realpath_failed", type(exc).__name__)
        except Exception:
            pass
        # Fallback to stderr for visibility
        try:
            import sys

            print(f"beamo-wipe [discover] alias_realpath_failed: {type(exc).__name__}", file=sys.stderr)
        except Exception:
            pass
    return aliases


def _disk_identity_contradicts(blockdevices: Sequence[Dict[str, Any]]) -> bool:
    """Reject a physical device path with conflicting kernel identities."""
    by_path: Dict[str, set[Tuple[str, str]]] = {}
    physical_paths: set[str] = set()
    for node, _parent in flatten_blockdevices(blockdevices):
        kind = _node_type(node)
        name = _clean(node.get("name"))
        path = _clean(node.get("path"))
        if kind in {"disk", "rom"} and name and path and not (
            _path_aliases(path) & _path_aliases(f"/dev/{name}")
        ):
            return True
        try:
            resolved = node_path(node)
        except ValueError:
            # The parser skips a malformed row per-node below. A malformed
            # identity cannot prove a path collision with a valid sibling.
            continue
        if resolved:
            canonical = os.path.realpath(resolved)
            by_path.setdefault(canonical, set()).add((name, kind))
            if kind in {"disk", "rom"}:
                physical_paths.add(canonical)
    if any(len(by_path[path]) > 1 for path in physical_paths):
        # A mounted mapper may claim the same /dev path as a different raw
        # disk whose own row lacks the mount. Neither identity can be trusted.
        return True
    return False


def _udev_decode(name: str) -> str:
    """Decode udev \\xHH escapes in by-label / by-uuid path tails."""
    out: List[str] = []
    i = 0
    while i < len(name):
        if (
            name[i] == "\\"
            and i + 3 < len(name)
            and name[i + 1] in "xX"
            and all(c in "0123456789abcdefABCDEF" for c in name[i + 2 : i + 4])
        ):
            out.append(chr(int(name[i + 2 : i + 4], 16)))
            i += 4
        else:
            out.append(name[i])
            i += 1
    return "".join(out)


def _dev_disk_typed_source(raw: str) -> Optional[Tuple[str, str]]:
    """Map /dev/disk/by-uuid/… (etc.) to the typed resolver without needing udev."""
    src = raw or ""
    for prefix, key in UDEV_BY_PREFIXES:
        if src.startswith(prefix):
            value = _udev_decode(src[len(prefix) :])
            if value and value.strip():
                return key, value
    return None


def normalize_mount_source(raw: str) -> str:
    """Turn findmnt SOURCE into a /dev path. LABEL=/UUID= values stay unresolved."""
    src = raw or ""
    if not src.strip():
        return ""
    # A typed value may contain spaces or brackets. Removing them could turn
    # the live source into a different disk's label/UUID. By-* path tails are
    # typed values too. The bracket suffix on ordinary /dev nodes remains a
    # findmnt subvolume annotation and is removed below.
    if ("=" in src and not src.startswith("/dev/")) or any(
        src.startswith(prefix) for prefix, _key in UDEV_BY_PREFIXES
    ):
        return src
    # findmnt annotates a direct kernel source as /dev/sdX1[subvolume].
    # An alias under /dev/disk/by-id can itself contain '['; shortening it
    # could resolve a different link and protect the wrong disk.
    bare = src.split("[", 1)[0]
    if bare != src and (
        KERNEL_NAME_RE.fullmatch(bare)
        or (bare.startswith("/dev/") and KERNEL_NAME_RE.fullmatch(bare[5:]))
    ):
        src = bare
    if src.startswith("/dev/"):
        return src
    src = src.strip()
    if "=" in src:
        return src
    if KERNEL_NAME_RE.fullmatch(src):
        return f"/dev/{src}"
    return src


def _looks_like_live_medium(node: Dict[str, Any]) -> bool:
    """Label fallback may only point at USB or optical media, never SATA/NVMe."""
    if _node_type(node) == "rom":
        return True
    name = _clean(node.get("name")).lower()
    if name.startswith("sr"):
        return True
    # lsblk TRAN is untrusted padding-wise; strip like classify_bus so
    # " usb " still counts as USB live media instead of a leftover winning.
    tran = (node.get("tran") or "").lower().strip()
    return tran == "usb"


def _could_be_live_medium(node: Dict[str, Any]) -> bool:
    """Treat every target-sized whole disk as a possible live bridge.

    USB-SATA/NVMe enclosures can report a fixed internal transport, no
    hotplug flag, and any capacity. No lsblk transport or size threshold can
    prove a second selectable disk is not the running live medium. A zero-size
    node cannot become a wipe target and need not compete for boot identity.
    """
    return _node_type(node) in {"disk", "rom"} and _as_int(node.get("size")) > 0


def _node_type(node: Dict[str, Any]) -> str:
    return (node.get("type") or "").lower()


# lsblk hangs a mounted RAID or multipath volume off one member. The other
# member stays a normal disk unless the whole inventory is refused.
# ``linear`` is md's level name, not a ``raid*`` type. Mounted LVM, linear,
# and bcache stacks are refused because member metadata may be incomplete.
# util-linux 2.38 lowercases the device-mapper UUID prefix and the md level,
# so DMRAID- is ``dmraid`` and md levels ``faulty`` / ``multipath`` do not
# start with ``raid``. One PKNAME still hides the other member.
_UNRESOLVED_HOLDER_TYPES = frozenset({
    "mpath", "md", "dmraid", "faulty", "multipath",
})
_STACKED_HOLDER_TYPES = frozenset({"lvm", "linear"})


def _mounted_holder_hides_members(kind: str) -> bool:
    return kind.startswith("raid") or kind in _UNRESOLVED_HOLDER_TYPES


def _cover_mounted_identifier_aliases(disks: Sequence[Disk]) -> List[Disk]:
    """Copy a mount onto paths sharing a hardware identifier with that disk.

    Multipath can record the mount on one path only. A repeated meaningful
    WWN or serial makes another path ambiguous, so it must not stay selectable.
    """
    mounted = [disk for disk in disks if disk.mountpoints]
    if not mounted:
        return list(disks)
    covered: List[Disk] = []
    for disk in disks:
        extra = [
            mountpoint
            for source in mounted
            if possible_hardware_alias(source, disk)
            for mountpoint in source.mountpoints
        ]
        if not extra:
            covered.append(disk)
            continue
        mounts = tuple(dict.fromkeys((*disk.mountpoints, *extra)))
        if mounts == disk.mountpoints:
            covered.append(disk)
            continue
        covered.append(replace(disk, mountpoints=mounts))
    return covered


def _resolve_owner_disk(
    node: Mapping[str, Any],
    parent: Optional[Dict[str, Any]],
    by_name: Mapping[str, Sequence[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]]],
) -> Tuple[str, bool]:
    """Return (physical disk name, ambiguous).

    PKNAME is followed through holders. A name shared by two nodes is
    ambiguous: the caller must not guess which disk owns the filesystem.
    """
    own_pk = ""
    if node.get("pkname") is not None:
        own_pk = _identity_text(node.get("pkname"), "pkname")
    if _node_type(node) in {"disk", "rom"} and not own_pk:
        if node.get("name") is None:
            return "", False
        return _identity_text(node.get("name"), "name"), False
    seen: set[str] = set()
    current = own_pk
    if not current and parent is not None and parent.get("name") is not None:
        current = _identity_text(parent.get("name"), "name")
    while current:
        if current in seen:
            return "", False
        seen.add(current)
        ancestors = list(by_name.get(current) or ())
        if len(ancestors) > 1:
            return "", True
        if len(ancestors) != 1:
            return "", False
        ancestor, tree_parent = ancestors[0]
        ancestor_pk = ""
        if ancestor.get("pkname") is not None:
            ancestor_pk = _identity_text(ancestor.get("pkname"), "pkname")
        if _node_type(ancestor) in {"disk", "rom"} and not ancestor_pk:
            return current, False
        if ancestor_pk:
            current = ancestor_pk
            continue
        if tree_parent is not None and tree_parent.get("name") is not None:
            current = _identity_text(tree_parent.get("name"), "name")
            continue
        return "", False
    return "", False


def _owner_disk_name(
    node: Mapping[str, Any],
    parent: Optional[Dict[str, Any]],
    by_name: Mapping[str, Sequence[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]]],
) -> str:
    """Physical disk that owns this node, following PKNAME through holders."""
    return _resolve_owner_disk(node, parent, by_name)[0]


def _reject_shared_device_ancestry(
    flat_nodes: Sequence[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]],
    by_name: Mapping[str, Sequence[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]]],
) -> None:
    """Refuse a repeated mapper whose copies name different physical disks.

    lsblk can repeat one dependency device below each of its members. Mount
    and filesystem metadata can be absent from one copy, so assigning those
    facts to only one backing disk would leave another member selectable.
    """
    groups: Dict[Tuple[str, str], List[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]]] = {}
    for node, parent in flat_nodes:
        if _node_type(node) in {"disk", "rom", "part", "loop", "ram"}:
            continue
        name = _identity_text(node.get("name"), "name")
        path = node_path(node)
        if name:
            groups.setdefault(("name", name), []).append((node, parent))
        if path:
            groups.setdefault(("path", os.path.realpath(path)), []).append((node, parent))
    for copies in groups.values():
        if len(copies) < 2:
            continue
        if not any(
            _node_mountpoints(node)
            or _filesystem_layout_row(node, partition=False)
            or any(_clean(node.get(key)) for key in ("partlabel", "parttypename", "parttype"))
            for node, _parent in copies
        ):
            # An unmounted mapping without content evidence is an ordinary
            # wipeable source. There is no mount or layout claim to assign to
            # the wrong physical member.
            continue
        for node, parent in copies:
            if parent is None or node.get("pkname") is None:
                continue
            named_parent = _identity_text(node.get("pkname"), "pkname")
            tree_parent_name = _identity_text(parent.get("name"), "name")
            if named_parent and named_parent != tree_parent_name:
                # One copy may omit every mount/filesystem field while its
                # tree still identifies a second physical member.
                raise ValueError("lsblk shared device ancestry contradicts PKNAME")
        owners = {
            _resolve_owner_disk(node, parent, by_name)[0]
            for node, parent in copies
        }
        if len(owners) > 1:
            raise ValueError("lsblk shared device ancestry is unresolved")


def _cover_shared_filesystem_members(
    flat_nodes: Sequence[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]],
    flat_mounts: Dict[str, List[str]],
    by_name: Mapping[str, Sequence[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]]],
) -> None:
    """Copy a mount onto every disk that shows the same filesystem UUID.

    lsblk records a multi-device filesystem mount on one member. The other
    member keeps the UUID and an empty mount list, and it may not have filled
    in fstype yet. An empty UUID is not an identity. A different fstype is a
    different filesystem and must not be glued on.
    """
    mounted: Dict[Tuple[str, str], List[str]] = {}
    mounted_uuid: Dict[str, List[str]] = {}
    for node, _parent in flat_nodes:
        fs = _clean(node.get("fstype")).casefold()
        uuid = _clean(node.get("uuid")).casefold()
        mounts = _node_mountpoints(node)
        if not uuid or not mounts:
            continue
        if fs:
            mounted.setdefault((fs, uuid), []).extend(mounts)
        mounted_uuid.setdefault(uuid, []).extend(mounts)
    if not mounted and not mounted_uuid:
        return
    for node, parent in flat_nodes:
        fs = _clean(node.get("fstype")).casefold()
        uuid = _clean(node.get("uuid")).casefold()
        if not uuid:
            continue
        mounts = mounted.get((fs, uuid)) if fs else None
        if not mounts and not fs:
            mounts = mounted_uuid.get(uuid)
        if not mounts:
            continue
        owner = _owner_disk_name(node, parent, by_name)
        if not owner:
            continue
        flat_mounts.setdefault(owner, []).extend(mounts)


def _is_stacked_holder(node: Mapping[str, Any]) -> bool:
    kind = _node_type(node)
    name = _clean(node.get("name")).lower()
    return kind in _STACKED_HOLDER_TYPES or name.startswith("bcache")


def _has_stacked_holder(
    node: Mapping[str, Any],
    parent: Optional[Dict[str, Any]],
    by_name: Mapping[str, Sequence[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]]],
) -> bool:
    """True when this node is an LVM, md-linear, or bcache device, or sits on one.

    A mount on the opened filesystem above that holder still belongs to every
    physical member. An unrelated LUKS volume does not.
    """
    if _is_stacked_holder(node):
        return True
    seen: set[str] = set()
    current = ""
    if node.get("pkname") is not None:
        current = _identity_text(node.get("pkname"), "pkname")
    if not current and parent is not None and parent.get("name") is not None:
        current = _identity_text(parent.get("name"), "name")
    while current:
        if current in seen:
            return False
        seen.add(current)
        ancestors = list(by_name.get(current) or ())
        if len(ancestors) != 1:
            return False
        ancestor, tree_parent = ancestors[0]
        if _is_stacked_holder(ancestor):
            return True
        nxt = ""
        if ancestor.get("pkname") is not None:
            nxt = _identity_text(ancestor.get("pkname"), "pkname")
        if not nxt and tree_parent is not None and tree_parent.get("name") is not None:
            nxt = _identity_text(tree_parent.get("name"), "name")
        current = nxt
    return False


def parent_disk_path(
    path: str, blockdevices: Sequence[Dict[str, Any]]
) -> Optional[str]:
    """Return the type=disk (or type=rom) path that owns `path`.

    Loop devices are not boot media. Partitions resolve to their disk.
    A path that is not in the tree returns None (fail closed).
    """
    aliases = _path_aliases(path)
    owners: List[str] = []
    for disk in disk_nodes(blockdevices):
        for candidate in paths_under(disk):
            if aliases & _path_aliases(candidate):
                owner = node_path(disk)
                if owner not in owners:
                    owners.append(owner)
    if len(owners) == 1:
        return owners[0]
    if len(owners) > 1:
        return None
    for node, parent in flatten_blockdevices(blockdevices):
        if not (aliases & _path_aliases(node_path(node))):
            continue
        typ = _node_type(node)
        if typ == "loop":
            return None
        if typ in {"disk", "rom"}:
            return node_path(node)
        pk = _clean(node.get("pkname"))
        if pk:
            for disk in disk_nodes(blockdevices):
                if _clean(disk.get("name")) == pk:
                    return node_path(disk)
        if parent is not None and _node_type(parent) in {"disk", "rom"}:
            return node_path(parent)
        return None
    return None


def _partition_parent_contradicts(
    node: Dict[str, Any], parent: Optional[Dict[str, Any]]
) -> bool:
    """Reject a partition whose explicit parent contradicts its device name."""
    if _node_type(node) != "part":
        return False
    pk = _clean(node.get("pkname"))
    if not pk and parent is None:
        return False
    owner_name = pk
    if not owner_name and parent is not None:
        owner_name = _clean(parent.get("name"))
    if not owner_name:
        return True
    name = _identity_text(node.get("name"), "name") if node.get("name") is not None else ""
    if not name:
        return True
    if not _name_is_partition_of(name, owner_name):
        return True
    if parent is not None and _clean(parent.get("name")) != owner_name:
        return True
    return not (_path_aliases(node_path(node)) & _path_aliases(f"/dev/{name}"))


def _name_is_partition_of(name: str, owner_name: str) -> bool:
    if not name or not owner_name:
        return False
    prefix = owner_name + ("p" if owner_name[-1].isdigit() else "")
    return name.startswith(prefix) and name[len(prefix):].isdigit()


def _unresolved_live_source(path: str, blockdevices: Sequence[Dict[str, Any]]) -> bool:
    """A stacked live source cannot be assigned to one physical member.

    lsblk may nest a RAID/LVM holder under only one of its backing disks.
    Resolving that holder through paths_under() would wrongly identify that
    one member as the entire boot medium and offer the other member to erase.
    """
    if not path:
        return False
    aliases = _path_aliases(path)
    return any(
        node_path(node)
        and aliases & _path_aliases(node_path(node))
        and (
            _clean(node.get("fstype")).casefold() == "btrfs"
            or _node_type(node) not in {"disk", "rom", "part"}
            or _partition_parent_contradicts(node, parent)
            or (
                _node_type(node) in {"disk", "rom"}
                and (parent is not None or _clean(node.get("pkname")))
            )
            or (
                _node_type(node) == "part"
                and parent is not None
                and _node_type(parent) not in {"disk", "rom"}
            )
        )
        for node, parent in flatten_blockdevices(blockdevices)
    )


def _shared_live_uuid(path: str, blockdevices: Sequence[Dict[str, Any]]) -> bool:
    """A direct live source with the same UUID on another path is ambiguous.

    findmnt may see the live mount while lsblk has empty mountpoint fields.
    Distinct device paths must not be merged merely because one stale PKNAME
    makes them appear to have the same owner.
    """
    if not path:
        return False
    aliases = _path_aliases(path)
    nodes = list(flatten_blockdevices(blockdevices))
    for node, parent in nodes:
        source_path = node_path(node)
        if not source_path or not (aliases & _path_aliases(source_path)):
            continue
        uuid = _clean(node.get("uuid")).casefold()
        if not uuid:
            continue
        for other, _other_parent in nodes:
            if other is node or _clean(other.get("uuid")).casefold() != uuid:
                continue
            other_path = node_path(other)
            if not other_path:
                return True
            if _path_aliases(source_path) & _path_aliases(other_path):
                continue
            # ISO-hybrid media can expose one ISO9660 superblock as both the
            # physical disk and its direct partition. Their tree relationship
            # proves they are one physical boot medium. PKNAME alone does not.
            same_disk_child = (
                (_node_type(node) in {"disk", "rom"} and _node_type(other) == "part"
                 and _other_parent is node)
                or (_node_type(other) in {"disk", "rom"} and _node_type(node) == "part"
                    and parent is other)
            )
            if not same_disk_child:
                return True
    return False


def nesting_parent_path(
    path: str,
    node: Dict[str, Any],
    parent: Optional[Dict[str, Any]],
    blockdevices: Sequence[Dict[str, Any]],
    by_name: Mapping[
        str, Sequence[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]]
    ],
) -> str:
    """Physical disk/rom that owns this node for display nesting.

    Empty when parentage is missing or ambiguous. Never infers a parent from
    kernel-name patterns. Display-only; boot identity still uses
    parent_disk_path.
    """
    try:
        typ = _node_type(node)
        if typ in {"disk", "rom"}:
            return ""
        owner = parent_disk_path(path, blockdevices)
        if owner and owner != path:
            return owner
        seen: set[str] = set()
        current = ""
        if node.get("pkname") is not None:
            current = _identity_text(node.get("pkname"), "pkname")
        if not current and parent is not None and parent.get("name") is not None:
            current = _identity_text(parent.get("name"), "name")
        while current:
            if current in seen:
                return ""
            seen.add(current)
            ancestors = list(by_name.get(current) or ())
            if len(ancestors) != 1:
                return ""
            ancestor, tree_parent = ancestors[0]
            if _node_type(ancestor) in {"disk", "rom"}:
                ap = node_path(ancestor)
                return ap if ap and ap != path else ""
            nxt = ""
            if ancestor.get("pkname") is not None:
                nxt = _identity_text(ancestor.get("pkname"), "pkname")
            if (
                not nxt
                and tree_parent is not None
                and tree_parent.get("name") is not None
            ):
                nxt = _identity_text(tree_parent.get("name"), "name")
            current = nxt
        return ""
    except ValueError:
        return ""


def _first_descendant_field(node: Dict[str, Any], key: str) -> str:
    for child in node.get("children") or []:
        if not isinstance(child, dict):
            continue
        if key in {"serial", "wwn"}:
            got = _hardware_identity(child.get(key), key)
        elif key == "vendor":
            got = _bounded_identity_metadata(child.get(key), key)
        else:
            got = _clean(child.get(key))
        if got:
            return got
        nested = _first_descendant_field(child, key)
        if nested:
            return nested
    return ""


def _volume_label(node: Dict[str, Any]) -> str:
    """Disk label, else a child volume label — never an EFI/boot firmware name
    when a real volume label exists (otherwise a Windows disk shows as 'EFI')."""
    label = _clean(node.get("label"))
    if label:
        return label
    all_labels: List[str] = []
    for child in node.get("children") or []:
        if isinstance(child, dict):
            all_labels.extend(labels_for(child))
    usable = [x for x in all_labels if x.upper() not in FIRMWARE_LABELS]
    if usable:
        return usable[0]
    return ""


_POSIX_FS = frozenset({"ext4", "ext3", "xfs", "btrfs", "f2fs"})
_WINDOWS_LABELS = frozenset(
    {"recovery", "winre", "windows", "system reserved", "windows recovery"}
)
_EFI_PARTTYPES = frozenset(
    {
        "c12a7328-f81f-11d2-ba4b-00a0c93ec93b",
        "ef00",
    }
)
_WINDOWS_OS_PARTTYPES = frozenset(
    {
        "de94bba4-06d1-4d40-a16a-bfd50179d6ac",  # Windows recovery
        "e3c9e316-0b5c-4db8-817d-f92df00215ae",  # Microsoft reserved
    }
)


_WINDOWS_PARTNAMES = (
    "microsoft reserved",
    "windows recovery",
    "windows recovery environment",
)


def _record_partition_evidence(
    item: Mapping[str, Any],
    fstypes: set[str],
    labels: set[str],
    partnames: set[str],
    parttypes: set[str],
) -> None:
    fs = _clean(item.get("fstype")).casefold()
    if fs:
        fstypes.add(fs)
    lab = _clean(item.get("label")).casefold()
    if lab:
        labels.add(lab)
    # PARTLABEL is the GPT name lsblk already returns. PARTTYPENAME is
    # the type's human name. Windows often leaves LABEL empty, so both
    # names are partition evidence, not a guess from the filesystem.
    for key in ("parttypename", "partlabel"):
        name = _clean(item.get(key)).casefold()
        if name:
            partnames.add(name)
            labels.add(name)
    ptype = _clean(item.get("parttype")).casefold()
    if ptype:
        parttypes.add(ptype)


def _record_opened_filesystem(
    item: Mapping[str, Any], fstypes: set[str], labels: set[str]
) -> None:
    """Filesystem identity on an opened LUKS or LVM volume."""
    fs = _clean(item.get("fstype")).casefold()
    if fs:
        fstypes.add(fs)
    lab = _clean(item.get("label")).casefold()
    if lab:
        labels.add(lab)


def _contents_from_evidence(
    fstypes: set[str],
    labels: set[str],
    partnames: set[str],
    parttypes: set[str],
) -> str:
    windows_marks = bool(
        labels & _WINDOWS_LABELS
        or "bitlocker" in fstypes
        or any(any(mark in name for mark in _WINDOWS_PARTNAMES) for name in partnames)
        or parttypes & _WINDOWS_OS_PARTTYPES
    )
    efi = bool(
        labels & {item.casefold() for item in FIRMWARE_LABELS}
        or any("efi" in name or name == "esp" for name in partnames)
        or parttypes & _EFI_PARTTYPES
    )
    posix = bool(fstypes & _POSIX_FS)
    if windows_marks or (bool(fstypes & {"ntfs"}) and efi):
        return CONTENTS_WINDOWS
    if efi and posix:
        return CONTENTS_SYSTEM
    if fstypes:
        return CONTENTS_DATA
    return CONTENTS_UNKNOWN


def _content_evidence(
    node: Mapping[str, Any],
) -> Tuple[set[str], set[str], set[str], set[str]]:
    fstypes: set[str] = set()
    labels: set[str] = set()
    partnames: set[str] = set()
    parttypes: set[str] = set()

    if _node_type(node) == "disk":
        # A partition table is optional: a filesystem may occupy the entire
        # physical disk. Its FSTYPE proves data is present, while its label
        # alone does not prove an installed operating system.
        whole_disk_fs = _clean(node.get("fstype")).casefold()
        if whole_disk_fs:
            fstypes.add(whole_disk_fs)

    def walk(item: object) -> None:
        if not isinstance(item, dict):
            return
        kind = _node_type(item)
        if kind == "part":
            _record_partition_evidence(item, fstypes, labels, partnames, parttypes)
        elif item is not node and kind not in {"loop", "rom"}:
            # bcache is type=disk. That filesystem is not the physical
            # disk's own fstype, which stays unknown with no partitions.
            _record_opened_filesystem(item, fstypes, labels)
        for child in item.get("children") or []:
            walk(child)

    walk(node)
    return fstypes, labels, partnames, parttypes


def classify_contents(node: Mapping[str, Any]) -> str:
    """Classify disk contents from filesystem and partition evidence only."""
    return _contents_from_evidence(*_content_evidence(node))


def classify_disk_contents(
    disk_node: Mapping[str, Any],
    flat_nodes: Sequence[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]],
    by_name: Mapping[str, Sequence[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]]],
) -> str:
    """Same classification, including partitions emitted as their own rows."""
    fstypes, labels, partnames, parttypes = _content_evidence(disk_node)
    if not isinstance(disk_node, dict) or disk_node.get("name") is None:
        return _contents_from_evidence(fstypes, labels, partnames, parttypes)
    disk_name = _identity_text(disk_node.get("name"), "name")
    if not disk_name:
        return _contents_from_evidence(fstypes, labels, partnames, parttypes)
    disk_path = node_path(disk_node)
    for node, parent in flat_nodes:
        if not isinstance(node, dict):
            continue
        kind = _node_type(node)
        if kind in {"loop", "rom"}:
            continue
        owner, ambiguous = _resolve_owner_disk(node, parent, by_name)
        if ambiguous or owner != disk_name:
            continue
        path = node_path(node)
        if disk_path and path == disk_path:
            continue
        if kind == "part":
            _record_partition_evidence(node, fstypes, labels, partnames, parttypes)
        else:
            # A type=disk holder such as bcache carries the opened filesystem.
            _record_opened_filesystem(node, fstypes, labels)
    return _contents_from_evidence(fstypes, labels, partnames, parttypes)


def _layout_id(node: Mapping[str, Any]) -> str:
    """Stable hash of filesystem identity. Empty when the disk has none.

    A blank serial and WWN cannot tell two disks apart. Partition UUID,
    opened-volume UUID, type, label, and partition size can. The hash is
    not a confirmation token.
    """
    return _hash_layout_rows(_layout_rows(node))


def _hash_layout_rows(rows: Sequence[str]) -> str:
    kept = [row for row in rows if row]
    if not kept:
        return ""
    return hashlib.sha256("\n".join(sorted(kept)).encode("utf-8")).hexdigest()


def _filesystem_layout_row(item: Mapping[str, Any], *, partition: bool) -> str:
    # These values enter the final rediscovery fingerprint. Truncating one
    # could make two different filesystem layouts compare equal.
    fstype = _hardware_identity(item.get("fstype"), "fstype").casefold()
    uuid = _hardware_identity(item.get("uuid"), "uuid").casefold()
    partuuid = _hardware_identity(item.get("partuuid"), "partuuid").casefold()
    label = _layout_label(item.get("label"), "label")
    parttype = _hardware_identity(item.get("parttype"), "parttype").casefold()
    parttypename = _bounded_identity_metadata(item.get("parttypename"), "parttypename")
    partlabel = _layout_label(item.get("partlabel"), "partlabel")
    size = str(_as_int(item.get("size"))) if partition else ""
    if not partition and not (fstype or uuid or partuuid or label or parttype or parttypename or partlabel):
        return ""
    # JSON preserves field boundaries even if a malformed identifier or a
    # user-chosen volume label contains the old `|` separator.
    return json.dumps(
        ("p" if partition else "d", fstype, uuid, partuuid, label, size,
         parttype, parttypename, partlabel),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _remember_layout_row(
    rows: List[str],
    seen: set[Tuple[str, str]],
    item: Mapping[str, Any],
    *,
    partition: bool,
) -> None:
    row = _filesystem_layout_row(item, partition=partition)
    if not row or not isinstance(item, dict):
        return
    key = (os.path.realpath(node_path(item)), row)
    if key in seen:
        return
    seen.add(key)
    # Sorting rows must not erase which physical partition owns a filesystem.
    # Mapper nodes such as dm-0 can be renumbered without a layout change.
    stable_path = key[0] if partition else ""
    rows.append(json.dumps((stable_path, row), ensure_ascii=False, separators=(",", ":")))


def _collect_tree_layout(
    node: Mapping[str, Any],
    rows: List[str],
    seen: set[Tuple[str, str]],
) -> None:
    """Filesystem rows for this node and devices nested under it."""

    def walk(item: object) -> None:
        if not isinstance(item, dict):
            return
        kind = _node_type(item)
        if kind == "part":
            _remember_layout_row(rows, seen, item, partition=True)
        elif item is not node and kind not in {"loop", "rom"}:
            # crypto_LUKS / LVM2_member keep a header UUID on the partition.
            # The filesystem UUID of an opened volume is on the mapper child.
            _remember_layout_row(rows, seen, item, partition=False)
        for child in item.get("children") or []:
            walk(child)

    if isinstance(node, dict):
        _remember_layout_row(rows, seen, node, partition=False)
    walk(node)


def _layout_rows(node: Mapping[str, Any]) -> List[str]:
    rows: List[str] = []
    _collect_tree_layout(node, rows, set())
    return rows


def _flat_layout_id(
    disk_node: Mapping[str, Any],
    flat_nodes: Sequence[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]],
    by_name: Mapping[str, Sequence[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]]],
) -> str:
    """Layout of this disk, including flat rows and opened mapper filesystems."""
    rows: List[str] = []
    seen: set[Tuple[str, str]] = set()
    _collect_tree_layout(disk_node, rows, seen)
    if not isinstance(disk_node, dict) or disk_node.get("name") is None:
        return _hash_layout_rows(rows)
    disk_name = _identity_text(disk_node.get("name"), "name")
    if not disk_name:
        return _hash_layout_rows(rows)
    disk_path = node_path(disk_node)
    for node, parent in flat_nodes:
        if not isinstance(node, dict):
            continue
        kind = _node_type(node)
        if kind in {"loop", "rom"}:
            continue
        owner, ambiguous = _resolve_owner_disk(node, parent, by_name)
        # A repeated parent name hides which disk owns this filesystem.
        # Listing the disk anyway would erase past an unbound volume UUID.
        if ambiguous and _filesystem_layout_row(node, partition=(kind == "part")):
            raise ValueError("lsblk layout ancestry is unresolved")
        if owner != disk_name:
            continue
        path = node_path(node)
        if disk_path and path == disk_path:
            continue
        _remember_layout_row(rows, seen, node, partition=(kind == "part"))
    return _hash_layout_rows(rows)


def node_to_disk(node: Dict[str, Any], is_boot: bool) -> Disk:
    name = _identity_text(node.get("name"), "name") if node.get("name") is not None else ""
    path = node_path(node)
    if not path or path == "/dev/":
        # Fail closed on malformed lsblk nodes: never mint Disk(path="/dev/").
        # Callers skip the node (per-node, so one bad node cannot hide the
        # whole bus) with a diagnostic for maintainer triage.
        raise ValueError("lsblk node has no usable device path")
    label = _volume_label(node)
    raw_model = _bounded_identity_metadata(node.get("model"), "model")
    mountpoints = tuple(mp for mp in _node_mountpoints(node) if mp)
    if not is_boot:
        from beamo_wipe.safety import is_protected_mountpoint

        is_boot = any(is_protected_mountpoint(mp) for mp in mountpoints)
    return Disk(
        path=path,
        name=name,
        model=raw_model or label or UNKNOWN_MODEL,
        serial=_hardware_identity(node.get("serial"), "serial")
        or _first_descendant_field(node, "serial"),
        size_bytes=_as_int(node.get("size")),
        size_gb_label=size_gb_label(_as_int(node.get("size"))),
        kind=classify_kind(name, node.get("tran"), node.get("rota")),
        bus=classify_bus(node.get("tran")),
        label=label,
        is_boot=is_boot,
        # lsblk RO missing (older fakes) means writable: exclude only an
        # explicit read-only flag, never on unknown.
        read_only=_as_bool(node.get("ro")) is True,
        wwn=_hardware_identity(node.get("wwn"), "wwn")
        or _first_descendant_field(node, "wwn"),
        vendor=_bounded_identity_metadata(node.get("vendor"), "vendor")
        or _first_descendant_field(node, "vendor"),
        mountpoints=mountpoints,
        raw_model=raw_model,
        contents=classify_contents(node),
        hotplug=(
            _as_bool(node.get("rm")) is True
            or _as_bool(node.get("hotplug")) is True
        ),
        layout_id=_layout_id(node),
    )


def labels_for(node: Dict[str, Any], *, exact: bool = False) -> List[str]:
    found = []
    # Boot identification must compare the reported label itself. Display
    # cleanup could otherwise turn a different label into BEAMO_WIPE.
    label = (
        _layout_label(node.get("label"), "label")
        if exact else _clean(node.get("label"))
    )
    if label:
        found.append(label)
    for child in node.get("children") or []:
        found.extend(labels_for(child, exact=exact))
    return found


def _is_loop_path(path: str, blockdevices: Sequence[Dict[str, Any]]) -> bool:
    aliases = _path_aliases(path)
    for node, _parent in flatten_blockdevices(blockdevices):
        if aliases & _path_aliases(node_path(node)):
            return _node_type(node) == "loop"
    return bool(re.match(r"^loop", os.path.basename(path), re.IGNORECASE))


def _resolve_boot_path(
    raw: str, blockdevices: Sequence[Dict[str, Any]], *, require_device_link: bool = True
) -> Optional[str]:
    """Map a /dev path or LABEL=/UUID= source to the boot disk/rom, or None."""
    if not raw:
        return None
    raw = normalize_mount_source(raw)
    typed_path = _dev_disk_typed_source(raw)
    typed = _split_typed_source(raw) or typed_path
    if typed:
        resolved = _resolve_typed_source(typed[0], typed[1], blockdevices)
        if typed_path:
            # A by-* mount source is also a device link. If it resolves to a
            # listed node, its physical owner must agree with the lsblk
            # identifier; stale labels must never protect the wrong disk.
            # If the link is absent, matching only the reported identifier
            # could protect a newly inserted disk and expose the real boot USB.
            try:
                link_target = os.path.realpath(raw)
            except OSError:
                return None
            if link_target == raw and require_device_link:
                return None
            if link_target != raw:
                actual = parent_disk_path(link_target, blockdevices)
                if not actual or not resolved or os.path.realpath(actual) != os.path.realpath(resolved):
                    return None
        return resolved
    if not raw.startswith("/dev/"):
        return None
    if _unresolved_live_source(raw, blockdevices) or _shared_live_uuid(raw, blockdevices):
        return None
    parent = parent_disk_path(raw, blockdevices)
    candidate = parent or raw
    if _is_loop_path(candidate, blockdevices):
        return None
    if _unresolved_live_source(candidate, blockdevices):
        return None
    aliases = _path_aliases(candidate)
    for node, _parent in flatten_blockdevices(blockdevices):
        if not (aliases & _path_aliases(node_path(node))):
            continue
        if _node_type(node) == "loop":
            return None
        if _node_type(node) in {"disk", "rom"}:
            return node_path(node)
        resolved = parent_disk_path(node_path(node), blockdevices)
        return resolved
    return None


def _split_typed_source(raw: str) -> Optional[Tuple[str, str]]:
    if "=" not in (raw or ""):
        return None
    key, value = raw.split("=", 1)
    key_u = key.upper()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    if key_u in TYPED_SOURCE_KEYS and value and value.strip():
        return key_u, value
    return None


def _resolve_typed_source(
    key: str, value: str, blockdevices: Sequence[Dict[str, Any]]
) -> Optional[str]:
    """Unique parent disk whose node (or partition) matches LABEL=/UUID=/…."""
    want = value
    if not want or not want.strip():
        return None
    found: List[str] = []
    seen = set()
    for node, _parent in flatten_blockdevices(blockdevices):
        try:
            got = _typed_field(node, key)
        except ValueError:
            # An invalid value might be the live source. Ignore no row when
            # that could make a different physical disk look uniquely matched.
            return None
        if not got:
            continue
        if key in {"UUID", "PARTUUID"}:
            match = got.casefold() == want.casefold()
        else:
            # Volume and partition labels can differ only by case. A
            # case-insensitive fallback can assign a typed live source to
            # the wrong disk and leave the actual boot medium selectable.
            match = got == want
        if not match:
            continue
        # Every matching row is a possible live source. Ignoring an orphan
        # partition or loop would let a stale physical match win a UUID/LABEL
        # lookup and expose the actual boot medium as a target.
        if (_unresolved_live_source(node_path(node), blockdevices)
                or _shared_live_uuid(node_path(node), blockdevices)):
            return None
        parent = parent_disk_path(node_path(node), blockdevices)
        if not parent or _is_loop_path(parent, blockdevices) or _unresolved_live_source(parent, blockdevices):
            return None
        if parent not in seen:
            seen.add(parent)
            found.append(parent)
    if len(found) == 1:
        return found[0]
    return None


def _typed_field(node: Dict[str, Any], key: str) -> str:
    mapping = {
        "LABEL": "label",
        "UUID": "uuid",
        "PARTUUID": "partuuid",
        "PARTLABEL": "partlabel",
    }
    # Match the raw filesystem identifier. Trimming, truncating, or removing
    # controls can turn a different volume into the reported live source.
    return _layout_label(node.get(mapping[key]), mapping[key])


def _label_boot_disks(blockdevices: Sequence[Dict[str, Any]]) -> List[str]:
    found: List[str] = []
    seen = set()

    for node, _parent in flatten_blockdevices(blockdevices):
        if _node_type(node) == "loop":
            continue
        matched = False
        try:
            labels = labels_for(node, exact=True)
        except ValueError:
            # An invalid label could itself be the boot label. Do not make
            # another device look uniquely identified by ignoring this one.
            return []
        for label in labels:
            if label.isascii() and label.upper() in BOOT_LABELS:
                matched = True
                break
        if not matched:
            continue
        if (_unresolved_live_source(node_path(node), blockdevices)
                or _shared_live_uuid(node_path(node), blockdevices)):
            return []
        parent = parent_disk_path(node_path(node), blockdevices)
        if not parent or _is_loop_path(parent, blockdevices):
            continue
        if _unresolved_live_source(parent, blockdevices):
            return []
        parent_node = None
        parent_aliases = _path_aliases(parent)
        for disk in disk_nodes(blockdevices):
            if parent_aliases & _path_aliases(node_path(disk)):
                parent_node = disk
                break
        if parent_node is None:
            for cand, _p in flatten_blockdevices(blockdevices):
                if parent_aliases & _path_aliases(node_path(cand)):
                    parent_node = cand
                    break
        if parent_node is None:
            continue
        if not _looks_like_live_medium(parent_node):
            # A product label on internal / SATA-bridge media makes the USB
            # leftover look "unique". Do not guess.
            return []
        if parent not in seen:
            seen.add(parent)
            found.append(parent)
    if len(found) != 1:
        return found
    labeled_aliases = _path_aliases(found[0])
    for node, _parent in flatten_blockdevices(blockdevices):
        if _node_type(node) not in {"disk", "rom"}:
            continue
        if labeled_aliases & _path_aliases(node_path(node)):
            continue
        if _could_be_live_medium(node):
            return []
    return found


def identify_boot_path(
    blockdevices: Sequence[Dict[str, Any]],
    *,
    env_boot: Optional[str] = None,
    mount_sources: Optional[Sequence[str]] = None,
    cmdline: str = "",
    require_device_link: bool = True,
) -> Optional[str]:
    """Return the parent disk/rom path of the live medium, or None if unsure.

    Live mounts are ground truth. An env/CLI override must agree with them.
    Filesystem labels are used only when they uniquely identify one USB or
    optical disk. Loop devices are never the boot USB.
    """
    if _disk_identity_contradicts(blockdevices):
        return None
    resolved_env = (
        _resolve_boot_path(env_boot, blockdevices, require_device_link=require_device_link)
        if env_boot else None
    )
    # A supplied override is a competing identity claim. If it cannot be
    # resolved, a valid mount must not silently make that contradiction vanish.
    if env_boot and not resolved_env:
        return None

    mount_hits: List[str] = []
    unresolved_sources: List[str] = []
    seen = set()
    for source in mount_sources or ():
        if not source:
            continue
        resolved = _resolve_boot_path(source, blockdevices, require_device_link=require_device_link)
        if resolved:
            if resolved not in seen:
                seen.add(resolved)
                mount_hits.append(resolved)
        else:
            unresolved_sources.append(source)
    if unresolved_sources:
        from beamo_wipe.diagnostics import emit_serial_marker

        emit_serial_marker("BEAMO_WIPE_BOOT_SOURCE_UNRESOLVED")
        for source in unresolved_sources:
            if source.startswith("/dev/loop"):
                marker = "BEAMO_WIPE_BOOT_SOURCE_LOOP"
            elif _split_typed_source(source):
                marker = "BEAMO_WIPE_BOOT_SOURCE_TYPED"
            elif source.startswith("/dev/"):
                marker = "BEAMO_WIPE_BOOT_SOURCE_DEVICE"
            elif source == "overlay":
                marker = "BEAMO_WIPE_BOOT_SOURCE_OVERLAY"
            else:
                marker = "BEAMO_WIPE_BOOT_SOURCE_OTHER"
            emit_serial_marker(marker)
    if len(mount_hits) > 1:
        from beamo_wipe.diagnostics import emit_serial_marker

        emit_serial_marker("BEAMO_WIPE_BOOT_SOURCE_CONFLICT")
    # Every observed live source must have a known physical owner. A known
    # source does not establish the owner of a second UUID or loop mount.
    if unresolved_sources or len(mount_hits) > 1:
        return None
    if len(mount_hits) == 1:
        if resolved_env and resolved_env != mount_hits[0]:
            return None
        return mount_hits[0]
    if resolved_env:
        return resolved_env

    cmdline_sources = CMDLINE_BOOT_RE.findall(cmdline or "")
    if cmdline_sources:
        cmdline_hits: List[str] = []
        for source in cmdline_sources:
            resolved = _resolve_boot_path(source, blockdevices, require_device_link=require_device_link)
            if not resolved:
                return None
            if resolved not in cmdline_hits:
                cmdline_hits.append(resolved)
        if len(cmdline_hits) != 1:
            return None
        # A stale bootloader label or path can name an internal disk. Without
        # mount evidence, another plausible live medium makes that identity
        # ambiguous, including when both paths report a small SATA disk.
        hit = cmdline_hits[0]
        hit_aliases = _path_aliases(hit)
        hit_node = None
        for node in disk_nodes(blockdevices):
            if hit_aliases & _path_aliases(node_path(node)):
                hit_node = node
                break
        if hit_node is not None:
            for node in disk_nodes(blockdevices):
                if hit_aliases & _path_aliases(node_path(node)):
                    continue
                if _could_be_live_medium(node):
                    return None
        return hit

    labels = _label_boot_disks(blockdevices)
    if len(labels) == 1:
        return labels[0]
    return None


def should_hide(node: Dict[str, Any], boot_path: Optional[str]) -> bool:
    typ = (node.get("type") or "").lower()
    name = _clean(node.get("name"))
    path = _clean(node.get("path")) or f"/dev/{name}"
    if boot_path:
        # Boot exception must be robust to realpath aliasing (e.g. /dev/disk/by-id/*).
        # Path equality here is the fast path; the full alias check is in
        # _node_is_boot. If realpath fails, we still hide the boot
        # candidate safely (fail-closed) but emit a diagnostic for ops.
        try:
            if _path_aliases(path) & _path_aliases(boot_path):
                return False
        except Exception:
            try:
                from beamo_wipe.diagnostics import log_diag

                log_diag("discover", "should_hide_alias_failed", "alias probe failed")
            except Exception:
                pass
        if path == boot_path:
            return False
    if typ in HIDDEN_TYPES:
        return True
    if HIDDEN_NAME_RE.match(name):
        return True
    if LIVE_NAME_RE.search(name):
        return True
    return typ != "disk"


def _node_is_boot(node: Dict[str, Any], boot_path: Optional[str]) -> bool:
    if not boot_path:
        return False
    boot_aliases = _path_aliases(boot_path)
    if _path_aliases(node_path(node)) & boot_aliases:
        return True
    return any(_path_aliases(candidate) & boot_aliases for candidate in paths_under(node))


def parse_lsblk_json(
    payload: Dict[str, Any],
    *,
    boot_path: Optional[str],
    require_boot: bool = True,
) -> DiscoveryResult:
    blockdevices = payload.get("blockdevices") or []
    if blockdevices and not isinstance(blockdevices, (list, tuple)):
        raise ValueError("lsblk JSON blockdevices must be a list")
    if require_boot and _disk_identity_contradicts(blockdevices):
        return DiscoveryResult(error=_copy.IDENTIFY_ERROR, boot_identified=False)
    if require_boot and not boot_path:
        return DiscoveryResult(error=_copy.IDENTIFY_ERROR, boot_identified=False)

    flat_mounts: Dict[str, List[str]] = {}
    flat_nodes = list(flatten_blockdevices(blockdevices))
    by_name: Dict[str, List[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]]] = {}
    for candidate, parent in flat_nodes:
        name = _identity_text(candidate.get("name"), "name")
        if name:
            by_name.setdefault(name, []).append((candidate, parent))
    known_disk_names = {
        _identity_text(node.get("name"), "name")
        for node in disk_nodes(blockdevices)
    }
    for candidate, parent in flat_nodes:
        kind = _node_type(candidate)
        mounts = _node_mountpoints(candidate)
        if _partition_parent_contradicts(candidate, parent):
            # A false flat PKNAME or tree parent can assign a mounted volume
            # to the wrong disk. Even when unmounted, it can move filesystem
            # identity and OS-content evidence onto another wipe candidate.
            if mounts:
                raise ValueError("lsblk mounted ancestry contradicts partition identity")
            raise ValueError("lsblk partition ancestry contradicts identity")
        if kind == "part" and parent is None and not _identity_text(
            candidate.get("pkname"), "pkname"
        ):
            # A root-level partition with no PKNAME has no proven owner. If
            # its kernel name or path matches a listed disk, silently dropping
            # its filesystem/OS evidence would make that disk look blank or
            # change the confirmed layout hash. An orphan with no possible
            # listed parent remains an excluded standalone inventory row.
            name = _identity_text(candidate.get("name"), "name")
            path_name = os.path.basename(node_path(candidate))
            if any(
                _name_is_partition_of(name, disk_name)
                or _name_is_partition_of(path_name, disk_name)
                for disk_name in known_disk_names
            ):
                raise ValueError("lsblk partition ancestry is unresolved")
        if mounts and parent is not None and candidate.get("pkname") is not None:
            named_parent = _identity_text(candidate.get("pkname"), "pkname")
            tree_parent_name = _identity_text(parent.get("name"), "name")
            if named_parent and named_parent != tree_parent_name:
                # Mapper and holder names do not encode their physical parent.
                # A mounted child with disagreeing PKNAME/tree ancestry could
                # otherwise mark only the wrong disk as mounted.
                raise ValueError("lsblk mounted ancestry contradicts PKNAME")
        if (
            kind in _UNRESOLVED_HOLDER_TYPES
            or kind in _STACKED_HOLDER_TYPES
            or kind in {"crypt", "dm", "bcache"}
            or kind.startswith("raid")
        ) and (
            _filesystem_layout_row(candidate, partition=False)
            or any(
                _clean(candidate.get(key))
                for key in ("partlabel", "parttypename", "parttype")
            )
        ):
            if parent is not None and candidate.get("pkname") is not None:
                named_parent = _identity_text(candidate.get("pkname"), "pkname")
                tree_parent_name = _identity_text(parent.get("name"), "name")
                if named_parent and named_parent != tree_parent_name:
                    # An unmounted opened volume still contributes OS content
                    # and layout identity; its parent cannot be assigned by
                    # contradictory PKNAME and tree observations.
                    raise ValueError("lsblk filesystem ancestry contradicts PKNAME")
            owner, _ambiguous = _resolve_owner_disk(candidate, parent, by_name)
            if not owner:
                # An opened filesystem with no physical ancestry can belong
                # to any candidate disk. Omitting it would hide contents and
                # weaken the layout identity presented for confirmation.
                raise ValueError("lsblk filesystem ancestry is unresolved")
        if mounts and _clean(candidate.get("fstype")).casefold() == "btrfs":
            # lsblk may show a mount on only one Btrfs member. A second
            # member can have an empty or stale UUID/fstype, so the inventory
            # alone cannot prove any other disk is outside that filesystem.
            raise ValueError("mounted Btrfs membership is unresolved")
        if mounts and _clean(candidate.get("name")).casefold().startswith("bcache"):
            # A mounted bcache holder names its backing device in PKNAME, but
            # its cache device may have empty or stale member metadata. The
            # complete set of physical members is not proven by lsblk.
            raise ValueError("mounted bcache membership is unresolved")
        if mounts and _has_stacked_holder(candidate, parent, by_name):
            # LVM and linear holders can span physical disks that have an
            # empty/stale member FSTYPE. A mount on a filesystem opened above
            # the holder has the same ambiguity, even if one PKNAME resolves.
            raise ValueError("mounted stacked volume membership is unresolved")
        if _mounted_holder_hides_members(kind):
            # Nested lsblk -J trees attach the array under one member. The
            # sibling stays a normal unmounted disk unless we refuse the
            # whole inventory. Flat pkname rows have the same PKNAME gap.
            if _node_mountpoints(candidate):
                raise ValueError("lsblk mounted ancestry is unresolved")
    for candidate, parent in flat_nodes:
        if parent is not None:
            continue
        # A holder such as bcache can be type=disk with PKNAME and its own
        # mount. Skipping every disk row left that backing disk selectable.
        if _node_type(candidate) == "disk":
            holder_parent = ""
            if candidate.get("pkname") is not None:
                holder_parent = _identity_text(candidate.get("pkname"), "pkname")
            if not holder_parent:
                continue
        pkname = _identity_text(candidate.get("pkname"), "pkname")
        mounts = _node_mountpoints(candidate)
        if not mounts:
            continue
        if not pkname:
            # Optical, loop and RAM devices can be standalone mounted roots.
            # Every other non-disk row needs a known physical ancestor;
            # missing PKNAME must not leave its backing disk selectable.
            if _node_type(candidate) in {"rom", "loop", "ram"}:
                continue
            raise ValueError("lsblk mounted ancestry is unresolved")
        kind = _node_type(candidate)
        if _mounted_holder_hides_members(kind):
            # lsblk exposes one PKNAME. The other member stays a normal
            # unmounted disk unless we refuse the whole inventory.
            raise ValueError("lsblk mounted ancestry is unresolved")
        # Flat lsblk rows can describe disk -> partition -> crypt/LVM chains.
        # Exclude every possible whole-disk ancestor; an unknown or cyclic
        # mounted chain must not silently become an unmounted physical disk.
        pending: List[Tuple[str, frozenset[str]]] = [(pkname, frozenset())]
        while pending:
            ancestor_name, trail = pending.pop()
            if ancestor_name in trail:
                raise ValueError("lsblk mounted ancestry contains a cycle")
            ancestors = by_name.get(ancestor_name)
            if not ancestors:
                raise ValueError("lsblk mounted ancestry is unresolved")
            for ancestor, tree_parent in ancestors:
                if tree_parent is not None and ancestor.get("pkname") is not None:
                    named_parent = _identity_text(ancestor.get("pkname"), "pkname")
                    tree_name = _identity_text(tree_parent.get("name"), "name")
                    if named_parent and named_parent != tree_name:
                        # This ancestor need not carry the mount itself: a
                        # flat mounted mapper can name an unmounted mapper
                        # whose PKNAME disagrees with its nested tree parent.
                        raise ValueError("lsblk mounted ancestry contradicts PKNAME")
                kind = _node_type(ancestor)
                if _is_stacked_holder(ancestor):
                    # A duplicated mapper name can make the earlier ancestor
                    # probe ambiguous. This mounted-chain walk visits every
                    # candidate, so reject any LVM/linear/bcache holder here.
                    raise ValueError("mounted stacked volume membership is unresolved")
                # One PKNAME on multipath or RAID hides the other leg.
                if _mounted_holder_hides_members(kind):
                    raise ValueError("lsblk mounted ancestry is unresolved")
                if kind in {"disk", "rom"}:
                    flat_mounts.setdefault(ancestor_name, []).extend(mounts)
                    # bcache and similar holders are type=disk and still
                    # name the physical disk in PKNAME.
                    holder_pk = ""
                    if ancestor.get("pkname") is not None:
                        holder_pk = _identity_text(ancestor.get("pkname"), "pkname")
                    if holder_pk and holder_pk != ancestor_name:
                        pending.append((holder_pk, trail | {ancestor_name}))
                    continue
                next_name = _identity_text(ancestor.get("pkname"), "pkname")
                if not next_name and tree_parent is not None:
                    next_name = _identity_text(tree_parent.get("name"), "name")
                if not next_name:
                    raise ValueError("lsblk mounted ancestry is unresolved")
                pending.append((next_name, trail | {ancestor_name}))

    _cover_shared_filesystem_members(flat_nodes, flat_mounts, by_name)
    _reject_shared_device_ancestry(flat_nodes, by_name)

    disks: List[Disk] = []
    identified_boot: Optional[Disk] = None
    for node in disk_nodes(blockdevices):
        try:
            matched_boot = _node_is_boot(node, boot_path)
            if should_hide(node, boot_path) and not matched_boot:
                continue
            disk = node_to_disk(node, is_boot=matched_boot)
            disk = replace(
                disk,
                layout_id=_flat_layout_id(node, flat_nodes, by_name),
                contents=classify_disk_contents(node, flat_nodes, by_name),
            )
        except ValueError:
            try:
                from beamo_wipe.diagnostics import log_diag

                log_diag("discover", "node_skipped_no_path", str(node.get("type"))[:32])
            except Exception:
                pass
            continue
        extra_mounts = flat_mounts.get(disk.name, [])
        if extra_mounts:
            merged = tuple(dict.fromkeys((*disk.mountpoints, *extra_mounts)))
            disk = replace(disk, mountpoints=merged)
        disks.append(disk)
        if matched_boot and identified_boot is None:
            identified_boot = disk

    # Boot medium might be type=rom (ISO in a VM). Still surface it, marked.
    # Run this even if a data disk was flagged is_boot via a protected mount;
    # discovery.boot must be the path we identified, not "the first is_boot".
    if boot_path and identified_boot is None:
        for node, _parent in flatten_blockdevices(blockdevices):
            if _node_type(node) == "loop":
                continue
            if not _node_is_boot(node, boot_path):
                continue
            if _node_type(node) in {"rom", "disk"}:
                try:
                    disk = node_to_disk(node, is_boot=True)
                    disk = replace(
                disk,
                layout_id=_flat_layout_id(node, flat_nodes, by_name),
                contents=classify_disk_contents(node, flat_nodes, by_name),
            )
                except ValueError:
                    try:
                        from beamo_wipe.diagnostics import log_diag

                        log_diag("discover", "node_skipped_no_path", str(node.get("type"))[:32])
                    except Exception:
                        pass
                    continue
                disks.append(disk)
                identified_boot = disk
                break

    # A protected-mount disk may still be flagged is_boot. discovery.boot is
    # only the path identify_boot_path resolved. An unmatched boot_path must
    # not fall through to "first is_boot" (that made an internal disk the
    # --exclude= target and left the live USB selectable).
    boot = identified_boot
    if require_boot and boot is None:
        return DiscoveryResult(error=_copy.IDENTIFY_ERROR, boot_identified=False)
    from beamo_wipe.safety import is_wipeable_disk

    # A distinct path sharing the boot medium's WWN, or its serial without
    # distinct WWNs, may be an alias. Mark ambiguous paths as protected.
    if boot is not None:
        disks = [
            replace(d, is_boot=True)
            if possible_hardware_alias(boot, d)
            else d
            for d in disks
        ]
        boot = next((d for d in disks if d.path == boot.path), boot)
    # lsblk can repeat a device in its dependency tree. Reconcile observations
    # before filtering: otherwise a mounted/read-only copy disappears while a
    # conflicting writable copy passes the final unique-target identity check.
    observed_disks: Dict[str, Disk] = {}
    for disk in disks:
        canonical = os.path.realpath(disk.path)
        previous = observed_disks.get(canonical)
        if previous is not None and disk != previous:
            raise ValueError("lsblk has conflicting observations for one disk")
        observed_disks[canonical] = disk
    # A second path with a mounted disk's identifier may be the same LUN.
    disks = _cover_mounted_identifier_aliases(disks)
    if boot is not None:
        boot = next((item for item in disks if item.path == boot.path), boot)
    # Retain even identical rows: final identity validation requires exactly
    # one observation and must continue refusing an ambiguous target.
    selectable = tuple(d for d in disks if is_wipeable_disk(d))
    # Health reporting: empty selectable while boot is identified is fail-closed
    # but opaque. Distinguish "no disks on bus" from "all nodes hidden".
    if boot is not None and not selectable and blockdevices:
        total_disk_nodes = sum(1 for _ in disk_nodes(blockdevices))
        # If disks is empty but there were disk nodes, they were all hidden/filtered.
        if total_disk_nodes and not disks:
            all_hidden = all(
                should_hide(n, boot_path) and not _node_is_boot(n, boot_path)
                for n in disk_nodes(blockdevices)
            )
            if all_hidden:
                try:
                    from beamo_wipe.diagnostics import log_diag

                    log_diag("discover", "all_hidden", f"nodes={total_disk_nodes} boot_known={bool(boot_path)}")
                except Exception:
                    pass
    # Preserve explanations separately from the safety-owned target collection.
    # No excluded node is added to disks/selectable or used for confirmation.
    from beamo_wipe.inventory import excluded_device
    from beamo_wipe.models import ExcludedDevice

    eligible_paths = {d.path for d in selectable}
    classified = {d.path: d for d in disks}
    excluded = []
    for node, tree_parent in flatten_blockdevices(blockdevices):
        try:
            path = node_path(node)
            if path in eligible_paths:
                continue
            inventory_disk = classified.get(path)
            if inventory_disk is None:
                inventory_disk = node_to_disk(node, is_boot=_node_is_boot(node, boot_path))
                extra = flat_mounts.get(inventory_disk.name, [])
                if extra:
                    inventory_disk = replace(inventory_disk, mountpoints=tuple(dict.fromkeys((*inventory_disk.mountpoints, *extra))))
            parent_path = nesting_parent_path(
                path, node, tree_parent, blockdevices, by_name
            )
            excluded.append(excluded_device(
                inventory_disk, unsupported=should_hide(node, boot_path),
                capacity_unknown=node.get("size") not in (0, "0") and inventory_disk.size_bytes <= 0,
                parent_path=parent_path,
                node_type=_node_type(node),
            ))
        except ValueError:
            excluded.append(ExcludedDevice(IDENTITY_UNAVAILABLE, (IDENTITY_UNCONFIRMED,)))
    return DiscoveryResult(
        excluded=tuple(excluded),
        disks=tuple(disks),
        selectable=selectable,
        boot=boot,
        error=None,
        boot_identified=True,
    )


def load_lsblk_json_text(text: str) -> Dict[str, Any]:
    def unique_pairs(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                # A later duplicate can replace mount/RO/identity evidence
                # before the structural checks see the earlier observation.
                raise ValueError("lsblk JSON has a duplicate field")
            result[key] = value
        return result

    data = json.loads(text, object_pairs_hook=unique_pairs)
    if not isinstance(data, dict):
        raise ValueError("lsblk JSON root must be an object")
    return data


def run_lsblk() -> Dict[str, Any]:
    from beamo_wipe.safety import CLEAN_SUBPROCESS_ENV

    args = ["-J", "-b", "-o", LSBLK_COLUMNS]
    proc = None
    last_exc: Optional[BaseException] = None
    for binary in LSBLK_BINARIES:
        try:
            proc = subprocess.run(
                [binary, *args],
                check=True,
                capture_output=True,
                text=True,
                timeout=LSBLK_TIMEOUT_S,
                shell=False,
                env=CLEAN_SUBPROCESS_ENV,
            )
            break
        except FileNotFoundError as exc:
            last_exc = exc
            continue
        except subprocess.CalledProcessError as exc:
            # Preserve stderr snippet (sanitized, truncated) for diagnostics
            try:
                from beamo_wipe.diagnostics import log_diag

                detail = (exc.stderr or exc.stdout or "")
                log_diag(
                    "discover",
                    "lsblk_failed",
                    f"exit={exc.returncode} stderr_bytes={len(detail.encode('utf-8', 'replace'))}",
                )
            except Exception:
                pass
            raise
        except subprocess.TimeoutExpired:
            try:
                from beamo_wipe.diagnostics import log_diag

                log_diag("discover", "lsblk_timeout", f"timeout={LSBLK_TIMEOUT_S}s")
            except Exception:
                pass
            raise
    if proc is None:
        if last_exc is not None:
            try:
                from beamo_wipe.diagnostics import log_diag

                log_diag("discover", "lsblk_missing", type(last_exc).__name__)
            except Exception:
                pass
            raise last_exc
        raise FileNotFoundError("lsblk")
    # Even on success, log stderr if any (lsblk warnings like "failed to access")
    if getattr(proc, "stderr", None):
        try:
            from beamo_wipe.diagnostics import log_diag

            detail = (proc.stderr or "").strip()
            if detail:
                log_diag(
                    "discover",
                    "lsblk_stderr",
                    f"stderr_bytes={len(detail.encode('utf-8', 'replace'))}",
                )
        except Exception:
            pass
    return load_lsblk_json_text(proc.stdout)


def _validate_real_lsblk_metadata(payload: Dict[str, Any]) -> None:
    """Require safety-critical columns from the real lsblk invocation.

    Missing RO or mountpoint data must not silently mean writable/unmounted.
    Explicit fixture payloads are validated by their callers and do not use
    this production-only gate.
    """
    blockdevices = payload.get("blockdevices")
    if not isinstance(blockdevices, list):
        raise ValueError("lsblk JSON blockdevices must be a list")
    for node, _parent in flatten_blockdevices(blockdevices):
        if "type" not in node or "path" not in node or "name" not in node:
            raise ValueError("lsblk omitted required identity metadata")
        if "mountpoints" not in node and "mountpoint" not in node:
            raise ValueError("lsblk omitted mountpoint metadata")
        mps = node.get("mountpoints")
        if mps is not None and not isinstance(mps, (list, str)):
            raise ValueError("lsblk mountpoints has invalid shape")
        if isinstance(mps, list) and any(
            mp is not None and not isinstance(mp, str) for mp in mps
        ):
            raise ValueError("lsblk mountpoints has invalid entry")
        if _node_type(node) == "disk" and _as_bool(node.get("ro")) is None:
            raise ValueError("lsblk omitted read-only metadata")


def read_cmdline(path: str = "/proc/cmdline") -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        try:
            from beamo_wipe.diagnostics import log_diag

            log_diag("discover", "cmdline_unreadable", type(exc).__name__)
        except Exception:
            pass
        return ""


def read_mount_sources(paths: Sequence[str] = LIVE_MOUNTS) -> List[str]:
    sources: List[str] = []
    seen = set()
    failures: List[str] = []

    def _add(raw: str) -> None:
        src = normalize_mount_source(raw)
        if src and src not in seen:
            seen.add(src)
            sources.append(src)

    for mountpoint in paths:
        try:
            proc = _run_findmnt(mountpoint)
        except (OSError, subprocess.TimeoutExpired) as exc:
            failures.append(type(exc).__name__)
            proc = None
        if proc is not None:
            if proc.returncode == 0:
                rows = [row for row in (proc.stdout or "").splitlines() if row.strip()]
                if len(rows) > 1:
                    from beamo_wipe.diagnostics import emit_serial_marker

                    emit_serial_marker("BEAMO_WIPE_BOOT_FINDMNT_MULTIROW")
                for row in rows:
                    _add(row)
            elif proc.returncode != 0:
                # Non-zero findmnt (not a mountpoint) is expected; only log if stderr present
                detail = getattr(proc, "stderr", "") or ""
                if detail:
                    failures.append(f"exit={proc.returncode} stderr_bytes={len(detail.encode('utf-8', 'replace'))}")
        elif proc is None and mountpoint in LIVE_MOUNTS:
            # _run_findmnt returned None without exception -> OSError/Timeout already logged per-mountpoint
            pass
    for src in read_mountinfo_sources(paths):
        _add(src)
    if failures:
        try:
            from beamo_wipe.diagnostics import log_diag

            log_diag("discover", "findmnt_failures", "; ".join(failures)[:300])
        except Exception:
            pass
    return sources


def _run_findmnt(mountpoint: str):
    from beamo_wipe.safety import CLEAN_SUBPROCESS_ENV

    last_exc: Optional[BaseException] = None
    for binary in FINDMNT_BINARIES:
        try:
            proc = subprocess.run(
                # A positional path can be interpreted as either mountpoint
                # or bind source. Only an exact live-medium mount is evidence.
                [binary, "-n", "-o", "SOURCE", "--mountpoint", mountpoint],
                capture_output=True,
                text=True,
                check=False,
                timeout=FINDMNT_TIMEOUT_S,
                shell=False,
                env=CLEAN_SUBPROCESS_ENV,
            )
            # Log stderr on unexpected failure for maintainers (sanitized, truncated)
            if proc.returncode != 0 and getattr(proc, "stderr", None):
                try:
                    from beamo_wipe.diagnostics import log_diag

                    detail = proc.stderr or ""
                    if detail:
                        log_diag("discover", "findmnt_stderr", f"exit={proc.returncode} stderr_bytes={len(detail.encode('utf-8', 'replace'))}")
                except Exception:
                    pass
            return proc
        except FileNotFoundError as exc:
            last_exc = exc
            continue
        except (OSError, subprocess.TimeoutExpired) as exc:
            try:
                from beamo_wipe.diagnostics import log_diag

                log_diag("discover", "findmnt_error", type(exc).__name__)
            except Exception:
                pass
            return None
    if last_exc is not None:
        try:
            from beamo_wipe.diagnostics import log_diag

            log_diag("discover", "findmnt_missing", type(last_exc).__name__)
        except Exception:
            pass
        raise last_exc
    return None


def _mountinfo_unescape(value: str) -> str:
    out: List[str] = []
    i = 0
    while i < len(value):
        if value[i] == "\\" and i + 3 < len(value) and value[i + 1 : i + 4].isdigit():
            out.append(chr(int(value[i + 1 : i + 4], 8)))
            i += 4
        else:
            out.append(value[i])
            i += 1
    return "".join(out)


def parse_mountinfo(text: str) -> List[Tuple[str, str]]:
    """Return (source, mountpoint) pairs from /proc/self/mountinfo contents."""
    pairs: List[Tuple[str, str]] = []
    for line in (text or "").splitlines():
        if " - " not in line:
            continue
        left, right = line.split(" - ", 1)
        left_parts = left.split()
        right_parts = right.split()
        if len(left_parts) < 5 or len(right_parts) < 2:
            continue
        mountpoint = _mountinfo_unescape(left_parts[4])
        source = _mountinfo_unescape(right_parts[1])
        pairs.append((source, mountpoint))
    return pairs


def read_mountinfo_sources(
    paths: Sequence[str] = LIVE_MOUNTS, text: Optional[str] = None
) -> List[str]:
    if text is None:
        try:
            with open(MOUNTINFO_PATH, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            try:
                from beamo_wipe.diagnostics import log_diag

                log_diag("discover", "mountinfo_unreadable", type(exc).__name__)
            except Exception:
                pass
            return []
    wanted = set(paths)
    found: List[str] = []
    for source, mountpoint in parse_mountinfo(text):
        if mountpoint in wanted:
            found.append(source)
    return found


def live_medium_is_mounted(
    *,
    text: Optional[str] = None,
    paths: Sequence[str] = LIVE_MOUNTS,
) -> bool:
    """True when a known live-medium path is mounted from a block device.

    Directory presence is not enough (`mkdir /run/live/medium`). The source
    must be a /dev node, a typed LABEL=/UUID= source, or a kernel disk name.
    tmpfs/overlay sources do not count.
    """
    if text is None:
        try:
            with open(MOUNTINFO_PATH, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            try:
                from beamo_wipe.diagnostics import log_diag

                log_diag("discover", "mountinfo_unreadable", type(exc).__name__)
            except Exception:
                pass
            return False
    pairs = parse_mountinfo(text)
    if len(pairs) != sum(bool(line.strip()) for line in text.splitlines()):
        # A dropped row might be a later mount covering the apparent live
        # medium. Incomplete mountinfo cannot establish a real live session.
        return False
    wanted = set(paths)
    live_rows = [(source, mountpoint) for source, mountpoint in pairs if mountpoint in wanted]
    if not live_rows or len({mountpoint for _source, mountpoint in live_rows}) != len(live_rows):
        # Two mounts at one path leave an older, hidden source in mountinfo.
        # Without resolving the effective mount, neither proves boot media.
        return False
    for source, _mountpoint in live_rows:
        raw = (source or "").split("[", 1)[0].strip()
        if not raw:
            return False
        if raw.startswith("/dev/"):
            continue
        if _split_typed_source(raw):
            continue
        if KERNEL_NAME_RE.fullmatch(raw):
            continue
        return False
    return True


def discover(
    *,
    lsblk_payload: Optional[Dict[str, Any]] = None,
    boot_path: Optional[str] = None,
    mount_sources: Optional[Sequence[str]] = None,
    cmdline: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> DiscoveryResult:
    if env is None:
        env = os.environ

    def _report(stage: str) -> None:
        # Stage display must never break discovery or identification.
        if progress is None:
            return
        try:
            progress(stage)
        except Exception:
            pass

    try:
        # Injected inventory describes an entirely fake machine. Never combine
        # it with the developer host's mounts or kernel boot arguments.
        if lsblk_payload is not None:
            payload = lsblk_payload
            mount_sources = [] if mount_sources is None else mount_sources
            cmdline = "" if cmdline is None else cmdline
        else:
            # Boot evidence first: the same reads identify_boot_path would
            # perform below, hoisted unchanged so the checking stage reports
            # genuine work. Boot media mounts do not change during startup.
            _report(STAGE_BOOT_USB)
            if mount_sources is None:
                mount_sources = read_mount_sources()
            if cmdline is None:
                cmdline = read_cmdline()
            _report(STAGE_FINDING)
            payload = run_lsblk()
        if not isinstance(payload, dict):
            raise ValueError("lsblk JSON root must be an object")
        if lsblk_payload is None and not (
            env.get("BEAMO_WIPE_DRY_RUN") == "1" or env.get("BEAMO_WIPE_DEMO") == "1"
        ):
            _validate_real_lsblk_metadata(payload)
        blockdevices = payload.get("blockdevices") or []
        # The manual boot path is a preview/test hook. On a real inventory,
        # it could name an internal disk when mount probing is unavailable,
        # leaving the actual boot USB selectable. Production must establish
        # boot identity from live mounts, kernel arguments, or the USB label.
        preview_inventory = lsblk_payload is not None or (
            env.get("BEAMO_WIPE_DRY_RUN") == "1"
            or env.get("BEAMO_WIPE_DEMO") == "1"
        )
        boot_override = (
            boot_path or env.get("BEAMO_WIPE_BOOT_DEVICE")
            if preview_inventory else None
        )
        identified = identify_boot_path(
            blockdevices,
            env_boot=boot_override,
            mount_sources=mount_sources,
            cmdline=cmdline,
            require_device_link=lsblk_payload is None,
        )
        return parse_lsblk_json(payload, boot_path=identified, require_boot=True)
    except (
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        ValueError,
        TypeError,
        AttributeError,
        json.JSONDecodeError,
    ) as exc:
        # Visible diagnostic for maintainers; UI stays generic and fail-closed.
        # Exception messages can contain device paths and serials from lsblk.
        try:
            from beamo_wipe.diagnostics import log_diag

            detail = type(exc).__name__
            if isinstance(exc, subprocess.TimeoutExpired):
                detail += " lsblk timeout"
            if isinstance(exc, OSError) and exc.errno is not None:
                detail += f" errno={exc.errno}"
            if isinstance(exc, subprocess.CalledProcessError) and getattr(exc, "stderr", None):
                detail += f" stderr_bytes={len(str(exc.stderr).encode('utf-8', 'replace'))}"
            log_diag("discover", "failed", detail)
        except Exception:
            pass
        diagnostic = f"{type(exc).__name__}: {str(exc)[:120]}".strip()
        from beamo_wipe.diagnostic_report import exception_code
        return DiscoveryResult(error=_copy.IDENTIFY_ERROR, boot_identified=False, diagnostic=diagnostic, error_code=exception_code(exc))
    except Exception as exc:  # noqa: BLE001 — catch unexpected, still fail-closed
        try:
            from beamo_wipe.diagnostics import log_diag

            log_diag("discover", "unexpected", type(exc).__name__)
        except Exception:
            pass
        diagnostic = f"{type(exc).__name__}: {str(exc)[:120]}".strip()
        from beamo_wipe.diagnostic_report import exception_code
        return DiscoveryResult(error=_copy.IDENTIFY_ERROR, boot_identified=False, diagnostic=diagnostic, error_code=exception_code(exc))
