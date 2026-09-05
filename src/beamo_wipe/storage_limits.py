# SPDX-License-Identifier: GPL-3.0-or-later
"""Canonical, offline storage guidance shared by renderers and evidence."""

from beamo_wipe.models import DiskKind

TITLE = "Supported storage limits"
BUTTON = "Storage limits (L)"
OVERWRITE_LIMITS = (
    "Overwriting reaches only storage the device exposes. It cannot guarantee "
    "coverage of inaccessible, remapped, over-provisioned (spare), or "
    "controller-managed flash areas. Additional overwrite passes do not fix these limitations."
)
VERIFICATION_SCOPE = (
    "Read-back verification checks exposed storage against the final overwrite. "
    "It does not prove that hidden copies were erased."
)


def notice(kind: DiskKind) -> str:
    if kind in (DiskKind.SSD, DiskKind.NVME):
        lead = "SSD limits: "
    elif kind == DiskKind.HDD:
        lead = (
            "Hard disk selected. Hidden or remapped sectors may remain. Flash limits: "
        )
    else:
        lead = "Device type is unknown; do not assume it is a hard disk or SSD. Flash limits: "
    return lead + OVERWRITE_LIMITS


SECTIONS = (
    (
        "What this tool supports",
        (
            "Beamo Wipe uses pinned nwipe v0.42 to overwrite a selected whole disk "
            "exposed to the operating system. It does not issue controller secure-erase "
            "or sanitize commands. It does not support Apple Silicon Macs, Chromebooks, "
            "or erasing the running Windows disk."
        ),
    ),
    ("SSD and flash storage", OVERWRITE_LIMITS),
    ("Read-back verification", VERIFICATION_SCOPE),
    (
        "Hard disks, hidden areas, and damaged media",
        (
            "Hidden HPA/DCO areas, remapped or unreadable sectors, and unexposed NVMe "
            "namespaces are outside the overwrite guarantee. A drive can report "
            "completion while hidden data remains. Read or write errors, missing "
            "completion evidence, and interruption must not be treated as success."
        ),
    ),
    (
        "Unknown devices and controllers",
        (
            "A missing device type stays unknown. A USB bridge or RAID controller "
            "may hide the media type, physical members, caches, or capacity. An exposed "
            "virtual disk does not establish coverage of every physical member. "
            "Do not use a displayed SSD or HDD label as proof that hidden areas are absent."
        ),
    ),
    (
        "Encryption and locked devices",
        (
            "Beamo Wipe does not unlock BitLocker, OPAL, ATA security, or other locked "
            "devices; extract keys; reset passwords; or bypass Secure Boot. Overwriting "
            "an exposed encrypted device is not proof of key destruction or coverage "
            "of hidden encrypted copies. Mapped volumes and partitions are not whole-disk targets."
        ),
    ),
    (
        "When to use a different process",
        (
            "If you need coverage beyond exposed storage, consult the drive maker's "
            "guidance for the exact model and firmware. Vendor secure erase support "
            "and validation vary; this USB does not perform or certify that process. "
            "For required assurance that cannot be established, use a qualified "
            "destruction service. Beamo reports are not a formal certificate."
        ),
    ),
    (
        "Ownership and safety",
        (
            "Erase only disks you own or have written permission to erase. Confirm "
            "the device identity and keep backups. Destructive-action warnings, boot "
            "exclusion, the confirmation token, and the five-second delay still apply. "
            "If identity is uncertain, stop; do not bypass the safety gates."
        ),
    ),
)


def full_text() -> str:
    return "\n\n".join(f"{title}\n{body}" for title, body in SECTIONS)
