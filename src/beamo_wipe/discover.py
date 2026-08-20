# SPDX-License-Identifier: GPL-3.0-or-later
"""Turn lsblk JSON into Disk objects. No wiping. No guessing when unsure."""

from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from beamo_wipe.models import Disk, DiskKind, DiscoveryResult

HIDDEN_TYPES = frozenset({"loop", "ram", "rom"})
HIDDEN_NAME_RE = re.compile(r"^(loop|ram|zram|sr|fd)", re.IGNORECASE)
LIVE_NAME_RE = re.compile(r"(live|casper|overlay)", re.IGNORECASE)
BOOT_LABELS = frozenset({"BEAMO_WIPE", "BEAMO-WIPE", "BEAMOWIPE"})

LIVE_MOUNTS = (
    "/run/live/medium",
    "/lib/live/mount/medium",
    "/run/initramfs/live",
    "/cdrom",
    "/mnt/live",
)

CANNOT_IDENTIFY = (
    "Cannot tell which disk is this USB. Unplug extra USB drives and reboot."
)

# Kernel cmdline keys that name the live medium. Matched as whole tokens so
# a substring like debug=bootfrom= cannot steal identification.
CMDLINE_BOOT_RE = re.compile(
    r"(?:^|\s)(?:bootfrom|img_dev|live-media|boot_image)=(\S+)"
)
KERNEL_NAME_RE = re.compile(r"^[a-zA-Z0-9._+-]+$")
LSBLK_TIMEOUT_S = 15
FINDMNT_TIMEOUT_S = 8


def size_gb_label(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "0"
    gb = int(round(size_bytes / 1_000_000_000))
    return str(max(1, gb))


def classify_kind(name: str, tran: Optional[str], rota: Any) -> DiskKind:
    tran_l = (tran or "").lower()
    name_l = (name or "").lower()
    if "nvme" in tran_l or name_l.startswith("nvme"):
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
    key = tran.lower()
    mapping = {
        "nvme": "NVMe",
        "sata": "SATA",
        "ata": "SATA",
        "usb": "USB",
        "sas": "SAS",
        "spi": "other",
        "virtio": "other",
    }
    return mapping.get(key, tran.upper())


def _as_bool(value: Any) -> Optional[bool]:
    if value is True or value is False:
        return value
    if value in (1, "1", "true", "True"):
        return True
    if value in (0, "0", "false", "False"):
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
    try:
        return int(text)
    except ValueError:
        try:
            return int(float(text))
        except ValueError:
            return 0


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def node_path(node: Dict[str, Any]) -> str:
    return _clean(node.get("path")) or f"/dev/{_clean(node.get('name'))}"


def flatten_blockdevices(
    blockdevices: Sequence[Dict[str, Any]], parent: Optional[Dict[str, Any]] = None
) -> Iterable[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]]:
    for node in blockdevices:
        yield node, parent
        children = node.get("children") or []
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
    except OSError:
        pass
    return aliases


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
    for disk in disk_nodes(blockdevices):
        for candidate in paths_under(disk):
            if aliases & _path_aliases(candidate):
                return node_path(disk)
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


def node_to_disk(node: Dict[str, Any], is_boot: bool) -> Disk:
    name = _clean(node.get("name"))
    path = _clean(node.get("path")) or f"/dev/{name}"
    label = _clean(node.get("label"))
    if not label:
        for child in node.get("children") or []:
            child_label = _clean(child.get("label"))
            if child_label:
                label = child_label
                break
    return Disk(
        path=path,
        name=name,
        model=_clean(node.get("model")) or label or "Unknown model",
        serial=_clean(node.get("serial")),
        size_bytes=_as_int(node.get("size")),
        size_gb_label=size_gb_label(_as_int(node.get("size"))),
        kind=classify_kind(name, node.get("tran"), node.get("rota")),
        bus=classify_bus(node.get("tran")),
        label=label,
        is_boot=is_boot,
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
    """Map a /dev path to the boot disk/rom, or None if it cannot be identified."""
    if not raw:
        return None
    raw = normalize_mount_source(raw)
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
        if parent_node is None or not _looks_like_live_medium(parent_node):
            continue
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
    seen = set()
    for source in mount_sources or ():
        resolved = _resolve_boot_path(source, blockdevices) if source else None
        if resolved and resolved not in seen:
            seen.add(resolved)
            mount_hits.append(resolved)
    if len(mount_hits) > 1:
        return None
    if len(mount_hits) == 1:
        if resolved_env and resolved_env != mount_hits[0]:
            return None
        return mount_hits[0]
    if resolved_env:
        return resolved_env

    match = CMDLINE_BOOT_RE.search(cmdline or "")
    if match:
        resolved = _resolve_boot_path(match.group(1), blockdevices)
        if resolved:
            return resolved

    labels = _label_boot_disks(blockdevices)
    if len(labels) == 1:
        return labels[0]
    return None


def should_hide(node: Dict[str, Any], boot_path: Optional[str]) -> bool:
    typ = (node.get("type") or "").lower()
    name = _clean(node.get("name"))
    path = _clean(node.get("path")) or f"/dev/{name}"
    if boot_path and path == boot_path:
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
    if require_boot and not boot_path:
        return DiscoveryResult(error=CANNOT_IDENTIFY, boot_identified=False)

    disks: List[Disk] = []
    for node in disk_nodes(blockdevices):
        is_boot = _node_is_boot(node, boot_path)
        if should_hide(node, boot_path) and not is_boot:
            continue
        disks.append(node_to_disk(node, is_boot=is_boot))

    # Boot medium might be type=rom (ISO in a VM). Still surface it, marked.
    if boot_path and not any(d.is_boot for d in disks):
        for node, _parent in flatten_blockdevices(blockdevices):
            if _node_type(node) == "loop":
                continue
            if not _node_is_boot(node, boot_path):
                continue
            if _node_type(node) in {"rom", "disk"}:
                disks.append(node_to_disk(node, is_boot=True))
                break
        else:
            if require_boot:
                return DiscoveryResult(error=CANNOT_IDENTIFY, boot_identified=False)

    boot = next((d for d in disks if d.is_boot), None)
    if require_boot and boot is None:
        return DiscoveryResult(error=CANNOT_IDENTIFY, boot_identified=False)
    selectable = tuple(d for d in disks if not d.is_boot and d.size_bytes > 0)
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
    cmd = [
        "lsblk",
        "-J",
        "-b",
        "-o",
        "NAME,PATH,SIZE,TYPE,TRAN,ROTA,MODEL,SERIAL,RM,HOTPLUG,MOUNTPOINT,LABEL,FSTYPE,VENDOR,PKNAME",
    ]
    proc = subprocess.run(
        cmd, check=True, capture_output=True, text=True, timeout=LSBLK_TIMEOUT_S
    )
    return load_lsblk_json_text(proc.stdout)


def read_cmdline(path: str = "/proc/cmdline") -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def read_mount_sources(paths: Sequence[str] = LIVE_MOUNTS) -> List[str]:
    sources: List[str] = []
    for mountpoint in paths:
        try:
            proc = subprocess.run(
                ["findmnt", "-n", "-o", "SOURCE", mountpoint],
                capture_output=True,
                text=True,
                check=False,
                timeout=FINDMNT_TIMEOUT_S,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        src = normalize_mount_source((proc.stdout or "").strip())
        if src:
            sources.append(src)
    return sources


def discover(
    *,
    lsblk_payload: Optional[Dict[str, Any]] = None,
    boot_path: Optional[str] = None,
    mount_sources: Optional[Sequence[str]] = None,
    cmdline: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
) -> DiscoveryResult:
    if env is None:
        env = os.environ
    try:
        payload = lsblk_payload if lsblk_payload is not None else run_lsblk()
        if not isinstance(payload, dict):
            raise ValueError("lsblk JSON root must be an object")
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
        json.JSONDecodeError,
    ):
        return DiscoveryResult(error=CANNOT_IDENTIFY, boot_identified=False)
