# SPDX-License-Identifier: GPL-3.0-or-later
"""Turn lsblk JSON into Disk objects. No wiping. No guessing when unsure."""

from __future__ import annotations

import json
import os
import re
import subprocess
import unicodedata
from dataclasses import replace
from typing import Mapping, Any, Dict, Iterable, List, Optional, Sequence, Tuple

from beamo_wipe.copy import IDENTIFY_ERROR as CANNOT_IDENTIFY
from beamo_wipe.models import Disk, DiskKind, DiscoveryResult

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
LSBLK_COLUMNS = (
    "NAME,PATH,SIZE,TYPE,TRAN,ROTA,MODEL,SERIAL,RM,HOTPLUG,"
    "MOUNTPOINT,MOUNTPOINTS,LABEL,FSTYPE,FSVER,VENDOR,PKNAME,UUID,WWN,PARTUUID,PARTLABEL,RO"
)
TYPED_SOURCE_KEYS = frozenset({"LABEL", "UUID", "PARTUUID", "PARTLABEL"})


def size_gb_label(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "0"
    gb = int(round(size_bytes / 1_000_000_000))
    return str(max(1, gb))


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
        "virtio": "other",
    }
    if key in mapping:
        return mapping[key]
    # Unknown transports stay visible but sanitized: strip control chars
    # (lsblk TRAN is untrusted; ANSI must not reach the UI or evidence)
    # and bound the length. The upper() shape is load-bearing:
    # safety.is_remote_disk matches bus.casefold() against remote tokens,
    # so this must never become UNKNOWN/"other" (that would make iSCSI/FC
    # wipeable).
    fallback = re.sub(r"[\x00-\x1f\x7f]", "", key).upper()[:32]
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

                log_diag("discover", "size_parse_failed", str(value)[:64])
            except Exception:
                pass
            return 0


def _clean(value: Any) -> str:
    if value is None:
        return ""
    # Untrusted lsblk metadata (model/serial/wwn/label) may contain control
    # chars, ANSI, newlines, or HTML. Strip control codes (0x00-0x1F, 0x7F),
    # truncate to 128 (display/evidence limit), and never pass raw to innerHTML.
    s = str(value)
    # Remove every Unicode control/format/surrogate/private-use/unassigned
    # character.  C0-only filtering leaves C1 CSI and bidi overrides that can
    # make an untrusted drive model/serial visually impersonate another disk.
    s = "".join(ch for ch in s if not unicodedata.category(ch).startswith("C"))
    s = s.strip()
    if len(s) > 128:
        s = s[:128]
    return s


def _identity_text(value: Any, field: str) -> str:
    """Read an lsblk identity field without repairing it into another device."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"lsblk {field} must be text")
    if not value or not value.strip():
        return ""
    if any(unicodedata.category(ch).startswith("C") for ch in value):
        raise ValueError(f"lsblk {field} contains control characters")
    text = value.strip()
    if text != value or not text or len(text) > 128:
        raise ValueError(f"lsblk {field} is malformed")
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

            log_diag("discover", "alias_realpath_failed", f"{type(exc).__name__}:{path[:32]}")
        except Exception:
            pass
        # Fallback to stderr for visibility
        try:
            import sys

            print(f"beamo-wipe [discover] alias_realpath_failed: {path[:32]}", file=sys.stderr)
        except Exception:
            pass
    return aliases


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
    src = (raw or "").strip()
    for prefix, key in UDEV_BY_PREFIXES:
        if src.startswith(prefix):
            value = _udev_decode(src[len(prefix) :]).strip()
            if value:
                return key, value
    return None


def normalize_mount_source(raw: str) -> str:
    """Turn findmnt SOURCE into a /dev path. LABEL=/UUID= values stay unresolved."""
    src = (raw or "").split("[", 1)[0].strip()
    if not src:
        return ""
    if src.startswith("/dev/"):
        return src
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
    tran = (node.get("tran") or "").lower()
    return tran == "usb"


def _node_type(node: Dict[str, Any]) -> str:
    return (node.get("type") or "").lower()


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


def _first_descendant_field(node: Dict[str, Any], key: str) -> str:
    for child in node.get("children") or []:
        if not isinstance(child, dict):
            continue
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


def node_to_disk(node: Dict[str, Any], is_boot: bool) -> Disk:
    name = _identity_text(node.get("name"), "name") if node.get("name") is not None else ""
    path = node_path(node)
    if not path or path == "/dev/":
        # Fail closed on malformed lsblk nodes: never mint Disk(path="/dev/").
        # Callers skip the node (per-node, so one bad node cannot hide the
        # whole bus) with a diagnostic for maintainer triage.
        raise ValueError("lsblk node has no usable device path")
    label = _volume_label(node)
    raw_model = _clean(node.get("model"))
    mountpoints = tuple(mp for mp in _node_mountpoints(node) if mp)
    if not is_boot:
        from beamo_wipe.safety import is_protected_mountpoint

        is_boot = any(is_protected_mountpoint(mp) for mp in mountpoints)
    return Disk(
        path=path,
        name=name,
        model=raw_model or label or "Unknown model",
        serial=_clean(node.get("serial")) or _first_descendant_field(node, "serial"),
        size_bytes=_as_int(node.get("size")),
        size_gb_label=size_gb_label(_as_int(node.get("size"))),
        kind=classify_kind(name, node.get("tran"), node.get("rota")),
        bus=classify_bus(node.get("tran")),
        label=label,
        is_boot=is_boot,
        # lsblk RO missing (older fakes) means writable: exclude only an
        # explicit read-only flag, never on unknown.
        read_only=_as_bool(node.get("ro")) is True,
        wwn=_clean(node.get("wwn")) or _first_descendant_field(node, "wwn"),
        vendor=_clean(node.get("vendor")) or _first_descendant_field(node, "vendor"),
        mountpoints=mountpoints,
        raw_model=raw_model,
    )


def labels_for(node: Dict[str, Any]) -> List[str]:
    found = []
    label = _clean(node.get("label"))
    if label:
        found.append(label)
    for child in node.get("children") or []:
        found.extend(labels_for(child))
    return found


def _is_loop_path(path: str, blockdevices: Sequence[Dict[str, Any]]) -> bool:
    aliases = _path_aliases(path)
    for node, _parent in flatten_blockdevices(blockdevices):
        if aliases & _path_aliases(node_path(node)):
            return _node_type(node) == "loop"
    return bool(re.match(r"^loop", os.path.basename(path), re.IGNORECASE))


def _resolve_boot_path(
    raw: str, blockdevices: Sequence[Dict[str, Any]]
) -> Optional[str]:
    """Map a /dev path or LABEL=/UUID= source to the boot disk/rom, or None."""
    if not raw:
        return None
    raw = normalize_mount_source(raw)
    typed = _split_typed_source(raw) or _dev_disk_typed_source(raw)
    if typed:
        return _resolve_typed_source(typed[0], typed[1], blockdevices)
    if not raw.startswith("/dev/"):
        return None
    parent = parent_disk_path(raw, blockdevices)
    candidate = parent or raw
    if _is_loop_path(candidate, blockdevices):
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
    key_u = key.strip().upper()
    value = value.strip().strip('"').strip("'")
    if key_u in TYPED_SOURCE_KEYS and value:
        return key_u, value
    return None


def _resolve_typed_source(
    key: str, value: str, blockdevices: Sequence[Dict[str, Any]]
) -> Optional[str]:
    """Unique parent disk whose node (or partition) matches LABEL=/UUID=/…."""
    want = value.strip()
    if not want:
        return None
    found: List[str] = []
    seen = set()
    for node, _parent in flatten_blockdevices(blockdevices):
        if _node_type(node) == "loop":
            continue
        got = _typed_field(node, key)
        if not got:
            continue
        if key in {"UUID", "PARTUUID"}:
            match = got.casefold() == want.casefold()
        else:
            match = got == want or got.casefold() == want.casefold()
        if not match:
            continue
        parent = parent_disk_path(node_path(node), blockdevices)
        if not parent or _is_loop_path(parent, blockdevices):
            continue
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
    return _clean(node.get(mapping[key]))


def _label_boot_disks(blockdevices: Sequence[Dict[str, Any]]) -> List[str]:
    found: List[str] = []
    seen = set()

    def _norm(label: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", (label or "").upper())

    for node, _parent in flatten_blockdevices(blockdevices):
        if _node_type(node) == "loop":
            continue
        matched = False
        for label in labels_for(node):
            if _norm(label) == "BEAMOWIPE" or label.upper() in BOOT_LABELS:
                matched = True
                break
        if not matched:
            continue
        parent = parent_disk_path(node_path(node), blockdevices)
        if not parent or _is_loop_path(parent, blockdevices):
            continue
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
    return found


def identify_boot_path(
    blockdevices: Sequence[Dict[str, Any]],
    *,
    env_boot: Optional[str] = None,
    mount_sources: Optional[Sequence[str]] = None,
    cmdline: str = "",
) -> Optional[str]:
    """Return the parent disk/rom path of the live medium, or None if unsure.

    Live mounts are ground truth. An env/CLI override must agree with them.
    Filesystem labels are used only when they uniquely identify one USB or
    optical disk. Loop devices are never the boot USB.
    """
    resolved_env = _resolve_boot_path(env_boot, blockdevices) if env_boot else None

    mount_hits: List[str] = []
    unresolved_sources: List[str] = []
    seen = set()
    for source in mount_sources or ():
        if not source:
            continue
        resolved = _resolve_boot_path(source, blockdevices)
        if resolved:
            if resolved not in seen:
                seen.add(resolved)
                mount_hits.append(resolved)
        else:
            unresolved_sources.append(source)
    if len(mount_hits) > 1:
        return None
    if len(mount_hits) == 1:
        if resolved_env and resolved_env != mount_hits[0]:
            return None
        return mount_hits[0]
    # Caller named a live mount we cannot map. Do not guess via labels —
    # that is how a leftover BEAMO_WIPE USB becomes "the boot stick" and
    # the real live medium becomes a wipe target.
    if unresolved_sources:
        return None
    if env_boot and not resolved_env:
        return None
    if resolved_env:
        return resolved_env

    cmdline_sources = CMDLINE_BOOT_RE.findall(cmdline or "")
    if cmdline_sources:
        cmdline_hits: List[str] = []
        for source in cmdline_sources:
            resolved = _resolve_boot_path(source, blockdevices)
            if not resolved:
                return None
            if resolved not in cmdline_hits:
                cmdline_hits.append(resolved)
        return cmdline_hits[0] if len(cmdline_hits) == 1 else None

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

                log_diag("discover", "should_hide_alias_failed", f"path={path[:32]}")
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
    if require_boot and not boot_path:
        return DiscoveryResult(error=CANNOT_IDENTIFY, boot_identified=False)

    flat_mounts: Dict[str, List[str]] = {}
    for candidate, parent in flatten_blockdevices(blockdevices):
        if parent is not None or _node_type(candidate) == "disk":
            continue
        pkname = _clean(candidate.get("pkname"))
        if not pkname:
            continue
        flat_mounts.setdefault(pkname, []).extend(_node_mountpoints(candidate))

    disks: List[Disk] = []
    identified_boot: Optional[Disk] = None
    for node in disk_nodes(blockdevices):
        try:
            matched_boot = _node_is_boot(node, boot_path)
            if should_hide(node, boot_path) and not matched_boot:
                continue
            disk = node_to_disk(node, is_boot=matched_boot)
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
        return DiscoveryResult(error=CANNOT_IDENTIFY, boot_identified=False)
    from beamo_wipe.safety import is_wipeable_disk

    # A distinct path with the boot medium's WWN may be a multipath/LUN alias.
    # Mark every such node as boot so none can become selectable.
    if boot is not None and (boot.wwn or "").strip():
        boot_wwn = boot.wwn.strip().casefold()
        disks = [
            replace(d, is_boot=True)
            if (d.wwn or "").strip().casefold() == boot_wwn
            else d
            for d in disks
        ]
        boot = next((d for d in disks if d.path == boot.path), boot)
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

                    log_diag("discover", "all_hidden", f"nodes={total_disk_nodes} boot={boot_path}")
                except Exception:
                    pass
    return DiscoveryResult(
        disks=tuple(disks),
        selectable=selectable,
        boot=boot,
        error=None,
        boot_identified=True,
    )


def load_lsblk_json_text(text: str) -> Dict[str, Any]:
    data = json.loads(text)
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

                detail = (exc.stderr or exc.stdout or "")[:300].replace("\n", " ").strip()
                log_diag("discover", "lsblk_failed", f"exit={exc.returncode} {detail}")
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

                log_diag("discover", "lsblk_missing", str(last_exc)[:200])
            except Exception:
                pass
            raise last_exc
        raise FileNotFoundError("lsblk")
    # Even on success, log stderr if any (lsblk warnings like "failed to access")
    if getattr(proc, "stderr", None):
        try:
            from beamo_wipe.diagnostics import log_diag

            detail = (proc.stderr or "")[:300].replace("\n", " ").strip()
            if detail:
                log_diag("discover", "lsblk_stderr", detail)
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
        if _node_type(node) == "disk" and _as_bool(node.get("ro")) is None:
            raise ValueError("lsblk omitted read-only metadata")


def read_cmdline(path: str = "/proc/cmdline") -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        try:
            from beamo_wipe.diagnostics import log_diag

            log_diag("discover", "cmdline_unreadable", f"{path}: {type(exc).__name__}")
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
            failures.append(f"{mountpoint}:{type(exc).__name__}")
            proc = None
        if proc is not None:
            if proc.returncode == 0:
                _add((proc.stdout or "").strip())
            elif proc.returncode != 0:
                # Non-zero findmnt (not a mountpoint) is expected; only log if stderr present
                detail = (getattr(proc, "stderr", "") or "")[:200].replace("\n", " ").strip()
                if detail:
                    failures.append(f"{mountpoint}:exit{proc.returncode}:{detail[:80]}")
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
                [binary, "-n", "-o", "SOURCE", mountpoint],
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

                    detail = (proc.stderr or "")[:200].replace("\n", " ").strip()
                    if detail:
                        log_diag("discover", "findmnt_stderr", f"{mountpoint}: {detail[:120]}")
                except Exception:
                    pass
            return proc
        except FileNotFoundError as exc:
            last_exc = exc
            continue
        except (OSError, subprocess.TimeoutExpired) as exc:
            try:
                from beamo_wipe.diagnostics import log_diag

                log_diag("discover", "findmnt_error", f"{mountpoint}:{type(exc).__name__}")
            except Exception:
                pass
            return None
    if last_exc is not None:
        try:
            from beamo_wipe.diagnostics import log_diag

            log_diag("discover", "findmnt_missing", str(last_exc)[:200])
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
    wanted = set(paths)
    for source, mountpoint in parse_mountinfo(text):
        if mountpoint not in wanted:
            continue
        raw = (source or "").split("[", 1)[0].strip()
        if not raw:
            continue
        if raw.startswith("/dev/"):
            return True
        if _split_typed_source(raw):
            return True
        if KERNEL_NAME_RE.fullmatch(raw):
            return True
    return False


def discover(
    *,
    lsblk_payload: Optional[Dict[str, Any]] = None,
    boot_path: Optional[str] = None,
    mount_sources: Optional[Sequence[str]] = None,
    cmdline: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> DiscoveryResult:
    if env is None:
        env = os.environ
    try:
        payload = lsblk_payload if lsblk_payload is not None else run_lsblk()
        if not isinstance(payload, dict):
            raise ValueError("lsblk JSON root must be an object")
        if lsblk_payload is None and not (
            env.get("BEAMO_WIPE_DRY_RUN") == "1" or env.get("BEAMO_WIPE_DEMO") == "1"
        ):
            _validate_real_lsblk_metadata(payload)
        blockdevices = payload.get("blockdevices") or []
        identified = identify_boot_path(
            blockdevices,
            env_boot=boot_path or env.get("BEAMO_WIPE_BOOT_DEVICE"),
            mount_sources=(
                mount_sources if mount_sources is not None else read_mount_sources()
            ),
            cmdline=cmdline if cmdline is not None else read_cmdline(),
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
        # Never log full lsblk payload (may contain serials), only type and truncated message.
        try:
            from beamo_wipe.diagnostics import log_diag

            # Sanitize: type + first 250 chars of message, no payload dump
            detail = f"{type(exc).__name__}: {str(exc)[:200]}"
            if isinstance(exc, subprocess.CalledProcessError) and getattr(exc, "stderr", None):
                detail += f" stderr:{str(exc.stderr)[:120].replace(chr(10), ' ')}"
            log_diag("discover", "failed", detail[:300])
        except Exception:
            pass
        diagnostic = f"{type(exc).__name__}: {str(exc)[:120]}".strip()
        return DiscoveryResult(error=CANNOT_IDENTIFY, boot_identified=False, diagnostic=diagnostic)
    except Exception as exc:  # noqa: BLE001 — catch unexpected, still fail-closed
        try:
            from beamo_wipe.diagnostics import log_diag

            log_diag("discover", "unexpected", f"{type(exc).__name__}: {str(exc)[:200]}")
        except Exception:
            pass
        diagnostic = f"{type(exc).__name__}: {str(exc)[:120]}".strip()
        return DiscoveryResult(error=CANNOT_IDENTIFY, boot_identified=False, diagnostic=diagnostic)
