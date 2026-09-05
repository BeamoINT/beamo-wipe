# SPDX-License-Identifier: GPL-3.0-or-later
"""Claim & storage-limit consistency — terminology, SSD/encryption/RAID/destruction.

Pinned language must never imply certified sanitization beyond evidence.
Fake disks only; never exec nwipe."""

from pathlib import Path

from beamo_wipe import copy as C
from beamo_wipe import gallery as G
from beamo_wipe.evidence import build_evidence
from beamo_wipe.models import Disk, DiskKind, DiscoveryResult, MethodId

ROOT = Path(__file__).resolve().parents[1]

# Forbidden badge/cert language — may only appear inside the "forbidden" lists
# in claims.md / copy tests, not as an affirmative claim elsewhere.
FORBIDDEN_CLAIMS = (
    "military certified",
    "dod certified",
    "nsa certified",
    "nist compliant",  # as badge
    "certified sanitization",
    "guaranteed unrecoverable",
    "impossible to recover",
    "plug and play",
    "works on any computer",
    "works on any mac",
    "apple silicon supported",
    "blancco replacement",
    "sanitized",  # as standalone claim for overwrite
    "nwipe sanitize",
)
# The one Apple Silicon phrase that is allowed is the honesty line.
ALLOWED_NEIGHBOR = "not apple silicon"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _lower(rel: str) -> str:
    return _read(rel).lower()


def _surfaces_without_forbidden_lists():
    # Only check *customer-facing* rendered surfaces, not docs that document the forbidden list.
    # The forbidden phrases are allowed to appear in docs/claims.md as examples of what NOT to say.
    # Also "sanitized" is allowed inside code comments that say "never claim sanitized".
    # So we exclude that doc from the scan; the other docs should not claim them.
    blobs = [
        _lower("src/beamo_wipe/copy.py"),
        _lower("src/beamo_wipe/evidence.py"),
        _lower("README.md"),
        _lower("docs/storage-and-controller-limits.md"),
        _lower("docs/ADVANCED.md"),
        _lower("helper/index.html"),
        G.gallery_html().lower(),
    ]
    return blobs


def _contains_claim(blob: str, phrase: str) -> bool:
    # For short generic words and negated disclosure lines, only flag when used as a claim,
    # not when documenting that we do NOT claim it: e.g. "never claim sanitized"
    # or "not a Blancco replacement". Table rows that list forbidden examples are also allowed.
    low = blob.lower()
    ph = phrase.lower()
    for line in low.splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            # Markdown table row documenting allowed vs forbidden — not a claim
            continue
        if ph in line:
            # allow lines that explicitly negate it or are listing forbidden examples
            if any(neg in line for neg in ("never", "not a", "not ", "do not", "forbidden", "do not say", "is not a", "are not", "never a")):
                continue
            # allow variable name cases like sanitized-device
            if ph == "sanitized" and ("sanitized-device" in line or "result-" in line):
                continue
            return True
    return False


def test_no_forbidden_cert_claim_outside_the_forbidden_list():
    blobs = _surfaces_without_forbidden_lists()
    for blob in blobs:
        for phrase in FORBIDDEN_CLAIMS:
            # "nwipe sanitize" forbidden as overwrite synonym; vendor sanitize is okay
            if phrase == "nwipe sanitize" and "vendor" in blob:
                # the string may appear as "vendor sanitize" nearby — allow that line
                # but forbid "nwipe sanitize" as a claim that nwipe sanitizes
                for line in blob.splitlines():
                    if "nwipe sanitize" in line and "vendor" not in line:
                        assert False, f"forbidden claim in surface: {phrase!r} line: {line[:120]}"
                continue
            if not _contains_claim(blob, phrase):
                continue
            assert False, f"forbidden claim found: {phrase!r}"


def test_ssd_footer_is_plain_language_and_not_a_certificate():
    assert "controller" in C.SSD_FOOTER.lower()
    assert "certificate" in C.SSD_FOOTER.lower()
    assert "formal certificate" in C.SSD_FOOTER.lower()
    # must not say certified sanitized
    assert "certified" not in C.SSD_FOOTER.lower() or "not a" in C.SSD_FOOTER.lower()


def test_every_method_shares_specific_ssd_limits():
    from beamo_wipe.storage_limits import notice, OVERWRITE_LIMITS
    assert OVERWRITE_LIMITS in notice(DiskKind.SSD)
    for term in ("inaccessible", "remapped", "over-provisioned", "controller-managed"):
        assert term in notice(DiskKind.SSD)
    assert "Additional overwrite passes do not fix" in notice(DiskKind.SSD)


def test_evidence_warning_matches_ssd_footer_language():
    # Both warn SSD results depend on controller and are not a formal certificate.
    assert "controller" in C.SSD_FOOTER.lower()
    assert "not a formal certificate" in C.SSD_FOOTER.lower()
    # evidence warning
    disk = Disk(
        path="/dev/sda",
        name="sda",
        model="Samsung SSD 970 EVO",
        serial="S123",
        size_bytes=256_000_000_000,
        size_gb_label="256",
        kind=DiskKind.SSD,
        bus="NVMe",
        label="",
    )
    from beamo_wipe.discover import DiscoveryResult

    disc = DiscoveryResult(disks=(disk,), selectable=(disk,), boot=None, boot_identified=True)
    ev = build_evidence(
        disk=disk,
        discovery=disc,
        method=MethodId.EVERYDAY,
        request=None,
        result=None,
        started_at_wall="2026-09-02T00:00:00Z",
        ended_at_wall="",
        started_mono=0.0,
        ended_mono=None,
        argv=[],
        log_text="",
    )
    warns = " ".join(ev.get("warnings") or []).lower()
    assert "controller" in warns
    from beamo_wipe.storage_limits import notice
    assert notice(DiskKind.SSD).lower() in warns


def test_claims_doc_mentions_vendor_and_destruction():
    claims = _lower("docs/claims.md")
    assert "vendor" in claims
    assert "destruction" in claims or "destroy" in claims


def test_readme_mentions_vendor_and_destruction_and_not_certificate():
    readme = _lower("README.md")
    assert "vendor" in readme
    assert "destroy" in readme or "destruction" in readme
    assert "not a lab" in readme or "not a formal certificate" in readme


def test_storage_doc_has_source_table_and_review_dates():
    text = _lower("docs/storage-and-controller-limits.md")
    assert "source and evidence table" in text
    assert "last checked" in text
    assert "owner" in text
    assert "next review" in text
    assert "2026-09-02" in text
    # pinned commit present
    assert "6082bde060091e66365d852a1877f2ee80c67105" in text
    assert "nwipe v0.42" in text


def test_storage_doc_covers_all_required_sections():
    text = _lower("docs/storage-and-controller-limits.md")
    for heading in (
        "verified behavior",
        "overwrite limits",
        "wear leveling",
        "remapped",
        "over-provisioning",
        "hpa",
        "dco",
        "nvme namespaces",
        "raid",
        "damaged",
        "encryption states",
        "opal",
        "bitlocker",
        "when vendor secure erase",
        "physical destruction",
        "ownership",
        "result messaging",
        "fail-closed",
        "consistent language",
        "say",
        "do not say",
    ):
        assert heading in text, f"storage doc missing section: {heading}"


def test_adv_docs_reference_storage_limits():
    for rel in ("docs/ADVANCED.md", "docs/compatibility-matrix.md", "README.md"):
        assert "storage-and-controller-limits" in _lower(rel)


def test_helper_does_not_claim_wipe():
    html = _lower("helper/index.html")
    assert "does not erase" in html
    assert "not apple silicon" in html


def test_package_readme_inside_iso_says_no_warranty_and_nwipe():
    # The staged README.txt is generated by scripts/build-iso.sh; verify the template in the script
    build_iso = _lower("scripts/build-iso.sh")
    assert "nwipe" in build_iso
    assert "no warranty" in build_iso

    packaging_readme = ROOT / "packaging/live/config/includes.binary/README.txt"
    if packaging_readme.exists():
        txt = packaging_readme.read_text(encoding="utf-8").lower()
        assert "nwipe" in txt
        assert "no warranty" in txt


def test_evidence_never_has_certificate_field():
    disk = Disk(
        path="/dev/sda",
        name="sda",
        model="WDC WD1000",
        serial="WD-1",
        size_bytes=1_000_000_000_000,
        size_gb_label="1000",
        kind=DiskKind.HDD,
        bus="SATA",
        label="",
    )
    disc = DiscoveryResult(disks=(disk,), selectable=(disk,), boot=None, boot_identified=True)
    ev = build_evidence(
        disk=disk,
        discovery=disc,
        method=MethodId.EVERYDAY,
        request=None,
        result=None,
        started_at_wall="2026-09-02T00:00:00Z",
        ended_at_wall="",
        started_mono=0.0,
        ended_mono=None,
        argv=[],
        log_text="",
    )
    blob = str(ev).lower()
    assert "certificate" not in blob
    assert "sanitized" not in blob
    assert "compliant" not in blob
