"""Final release inventory must come from the retained CI evidence file."""

import json

import pytest

from beamo_wipe import ci_evidence, release_manifest as rm
from test_ci_evidence_pipeline import build_provenance  # noqa: F401 - fixture


def test_finalize_refuses_package_inventory_link(build_provenance, monkeypatch, tmp_path):  # noqa: F811
    root, manifest_path, _iso = build_provenance
    evidence = root / "dist/evidence"
    evidence.mkdir()
    outside = tmp_path / "outside-inventory.json"
    outside.write_text("{}")
    (evidence / "packages.json").symlink_to(outside)
    original = json.loads(manifest_path.read_text())
    generated = []

    def generate(**kwargs):
        generated.append(kwargs)
        return original

    monkeypatch.setattr(ci_evidence, "load_receipts", lambda _directory: [])
    monkeypatch.setattr(rm, "generate_manifest", generate)
    monkeypatch.setattr(rm, "verify_manifest", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeError) as error:
        ci_evidence.finalize(root)
    assert "cannot safely read packages.json" in str(error.value)
    assert generated == [], "linked inventory reached release manifest generation"
