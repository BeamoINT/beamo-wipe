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
    if isinstance(value, int):
        return value
    text = str(value).strip()
    try:
        return int(text)
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


def parent_disk_path(
    path: str, blockdevices: Sequence[Dict[str, Any]]
) -> Optional[str]:
    """Return the type=disk path that owns `path` (itself, or its ancestor)."""
    aliases = {path}
    try:
        aliases.add(os.path.realpath(path))
    except OSError:
        pass
    for disk in disk_nodes(blockdevices):
        for candidate in paths_under(disk):
            names = {candidate}
            try:
                names.add(os.path.realpath(candidate))
            except OSError:
                pass
            if aliases & names:
                return node_path(disk)
    for node, _parent in flatten_blockdevices(blockdevices):
        if node_path(node) in aliases:
            return node_path(node)
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
        model=_clean(node.get("model")) or "Unknown model",
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


def identify_boot_path(
    blockdevices: Sequence[Dict[str, Any]],
    *,
    env_boot: Optional[str] = None,
    mount_sources: Optional[Sequence[str]] = None,
    cmdline: str = "",
) -> Optional[str]:
    """Return the parent disk path of the live medium, or None if unsure."""
    if env_boot:
        parent = parent_disk_path(env_boot, blockdevices)
        return parent or env_boot

    def _norm(label: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", (label or "").upper())

    for node, _parent in flatten_blockdevices(blockdevices):
        for label in labels_for(node):
            if _norm(label) == "BEAMOWIPE" or label.upper() in BOOT_LABELS:
                parent = parent_disk_path(node_path(node), blockdevices)
                if parent:
                    return parent

    for source in mount_sources or ():
        if not source:
            continue
        # SOURCE may be /dev/sda1 or /dev/sr0
        raw = source.split("[", 1)[0].strip()
        if not raw.startswith("/dev/"):
            continue
        parent = parent_disk_path(raw, blockdevices)
        if parent:
            return parent
        # Optical / whole-device mounts
        if raw:
            return raw

    # live-boot sometimes puts bootfrom=/dev/sda1 on the kernel command line
    for key in ("bootfrom=", "img_dev=", "live-media=", "boot_image="):
        if key in cmdline:
            part = cmdline.split(key, 1)[1].split(" ", 1)[0].strip()
            if part.startswith("/dev/"):
                parent = parent_disk_path(part, blockdevices)
                return parent or part
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
        path = _clean(node.get("path")) or f"/dev/{_clean(node.get('name'))}"
        is_boot = bool(boot_path and path == boot_path)
        if should_hide(node, boot_path) and not is_boot:
            continue
        disks.append(node_to_disk(node, is_boot=is_boot))

    # Boot medium might be type=rom (ISO in a VM). Still surface it, marked.
    if boot_path and not any(d.path == boot_path for d in disks):
        for node, _parent in flatten_blockdevices(blockdevices):
            path = _clean(node.get("path")) or f"/dev/{_clean(node.get('name'))}"
            if path == boot_path:
                disks.append(node_to_disk(node, is_boot=True))
                break
        else:
            # We know the path from mounts but lsblk missed it: synthesize.
            name = os.path.basename(boot_path)
            disks.append(
                Disk(
                    path=boot_path,
                    name=name,
                    model="Beamo boot device",
                    serial="",
                    size_bytes=0,
                    size_gb_label="0",
                    kind=DiskKind.UNKNOWN,
                    bus="USB",
                    label="BEAMO_WIPE",
                    is_boot=True,
                )
            )

    boot = next((d for d in disks if d.is_boot), None)
    selectable = tuple(d for d in disks if not d.is_boot)
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
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
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
            )
        except OSError:
            continue
        src = (proc.stdout or "").strip()
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
    payload = lsblk_payload if lsblk_payload is not None else run_lsblk()
    blockdevices = payload.get("blockdevices") or []
    identified = boot_path or identify_boot_path(
        blockdevices,
        env_boot=env.get("BEAMO_WIPE_BOOT_DEVICE") or boot_path,
        mount_sources=mount_sources if mount_sources is not None else read_mount_sources(),
        cmdline=cmdline if cmdline is not None else read_cmdline(),
    )
    return parse_lsblk_json(payload, boot_path=identified, require_boot=True)
