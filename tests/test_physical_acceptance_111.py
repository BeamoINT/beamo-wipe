# SPDX-License-Identifier: GPL-3.0-or-later
"""Physical acceptance #111 scaffolding stays honest and discoverable.

Docs and path checks only. Fake disks are not required. This does not run
nwipe, enumerate host disks, or invent hardware results.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
HUB = DOCS / "evidence" / "physical-acceptance-111"
RESULTS = HUB / "results"

PHY_LINE = re.compile(r"^\| PHY-[A-Z]+-\d+")
RESULT_SHEETS = (
    "firmware.md",
    "monitors.md",
    "ports.md",
    "usb-controllers.md",
    "keyboards.md",
    "touchpads.md",
    "audio.md",
    "power.md",
    "desktop-usb-launch.md",
    "optional-destructive.md",
)
REQUIRED_IDS = (
    "PHY-FW-01",
    "PHY-FW-03",
    "PHY-FW-06",
    "PHY-MON-01",
    "PHY-MON-02",
    "PHY-PORT-01",
    "PHY-PORT-03",
    "PHY-USB-01",
    "PHY-USB-02",
    "PHY-KB-01",
    "PHY-TP-01",
    "PHY-AUD-01",
    "PHY-AUD-03",
    "PHY-PWR-01",
    "PHY-PWR-05",
    "PHY-PWR-08",
    "PHY-DESK-01",
    "PHY-DEST-01",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_hub_and_templates_exist():
    for rel in (
        "README.md",
        "BUILD-IDENTITY.md",
        "photos/README.md",
        "logs/README.md",
    ):
        assert (HUB / rel).is_file(), rel
    for name in RESULT_SHEETS:
        assert (RESULTS / name).is_file(), name


def test_acceptance_criteria_are_stated_before_blank_tables():
    text = _read(HUB / "README.md")
    criteria = text.lower().index("what “done” means") if "what “done” means" in text.lower() else text.lower().index("measurable")
    index = text.lower().index("matrix index")
    assert criteria < index
    for needle in (
        "build identity",
        "dedicated safe hardware",
        "named-machine",
        "not a substitute",
        "disposable",
    ):
        assert needle in text.lower(), needle


def test_status_is_prep_only():
    text = _read(HUB / "README.md")
    low = text.lower()
    assert "prep only" in low
    assert "blocked" in low
    assert "not tested" in low
    assert "in progress" in low
    assert "lab completed" not in low
    assert "physical acceptance complete" not in low
    assert "all rows passed" not in low


def test_virtual_coverage_is_not_treated_as_physical():
    text = _read(HUB / "README.md")
    low = text.lower()
    assert "usb-lab" in low or "usb-lab-20260907" in low
    assert "laptop-power-20260914" in low
    assert "untested-physical.txt" in text
    assert "not a substitute" in low
    assert "qemu" in low
    assert "tier 3" in low


def test_gap_inventory_cites_real_paths():
    text = _read(HUB / "README.md")
    for path in (
        "docs/desktop-hardware-acceptance.md",
        "docs/compatibility-matrix.md",
        "docs/evidence-tiers.md",
        "docs/usb-simulation-lab-2026-09-07.md",
        "docs/evidence/usb-lab-20260907/",
        "docs/evidence/laptop-power-20260914.md",
        "docs/evidence/live-session-power-20260910.md",
        "docs/gcp-desktop-validation-2026-09-07.md",
        "packaging/live/",
    ):
        assert path in text, path
    assert (DOCS / "evidence/usb-lab-20260907/linux/boot-gate/untested-physical.txt").is_file()
    assert (DOCS / "evidence/laptop-power-20260914.md").is_file()


def test_build_identity_has_recording_fields():
    text = _read(HUB / "BUILD-IDENTITY.md").lower()
    for field in (
        "wrapper version",
        "source commit",
        "iso sha-256",
        "usb image sha-256",
        "manifest sha-256",
        "usb stick serial",
        "firmware vendor / version",
        "secure boot",
        "must be no",
    ):
        assert field in text, field


def test_procedure_preserves_disk_safety():
    text = _read(HUB / "README.md").lower()
    assert "never run `nwipe`" in text or "never run nwipe" in text
    assert "valuable disks" in text
    assert "spare usb" in text
    assert "manufactured image" in text
    assert "this development" in text
    assert "not a vm" in text or "not a vm," in text


def test_result_rows_default_to_not_tested_never_pass():
    found: set[str] = set()
    for name in RESULT_SHEETS:
        for line in _read(RESULTS / name).splitlines():
            if not PHY_LINE.match(line):
                continue
            assert "NOT TESTED" in line, line
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            assert cells, line
            # Result is the second-to-last cell on every results sheet.
            assert cells[-2] == "NOT TESTED", line
            assert cells[-2] != "Pass"
            found.add(cells[0])
    for required in REQUIRED_IDS:
        assert required in found, required
    assert len(found) >= 70


def test_photos_and_logs_are_empty_scaffolding():
    photos = _read(HUB / "photos" / "README.md").lower()
    logs = _read(HUB / "logs" / "README.md").lower()
    assert "empty of lab photos" in photos
    assert "empty of lab logs" in logs
    photo_files = [p for p in (HUB / "photos").iterdir() if p.name != "README.md"]
    log_files = [p for p in (HUB / "logs").iterdir() if p.name != "README.md"]
    assert photo_files == []
    assert log_files == []


def test_cross_links_from_existing_docs():
    pointer = "evidence/physical-acceptance-111/README.md"
    for rel in (
        "desktop-hardware-acceptance.md",
        "compatibility-matrix.md",
        "evidence-tiers.md",
    ):
        text = _read(DOCS / rel)
        assert pointer in text, rel
        assert "NOT TESTED" in text
    power = _read(DOCS / "live-session-power.md")
    assert "physical-acceptance-111/results/power.md" in power


def test_desktop_checklist_still_untested():
    text = _read(DOCS / "desktop-hardware-acceptance.md")
    assert "no physical configuration has been accepted" in text.lower()
    for line in text.splitlines():
        if not line.startswith("| ") or line.startswith("| Case"):
            continue
        if "Expected result" in line or line.startswith("| ---"):
            continue
        # Original non-destructive table rows stay NOT TESTED.
        if "NOT TESTED" in line or "Result / evidence" in line:
            continue
        # Header / section pipes are allowed; data rows in the case table
        # always include the result column.
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[0] and "Expected result" not in cells[1]:
            assert cells[2] == "NOT TESTED", line
