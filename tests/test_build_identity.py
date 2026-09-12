# SPDX-License-Identifier: GPL-3.0-or-later
"""Wrapper build identity and wall-clock confidence. Fake evidence, controlled clocks."""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path

import pytest

from beamo_wipe.build_identity import (
    STATUS_DEVELOPMENT,
    STATUS_DIRTY,
    STATUS_MISMATCH,
    STATUS_PRODUCTION,
    STATUS_UNAVAILABLE,
    assert_injectable,
    classify_status,
    evidence_identity,
    load_build,
    runtime_source_sha256,
    write_injected,
)
from beamo_wipe.evidence import SCHEMA_VERSION, valid_wall, wall_timestamps
from beamo_wipe.outcomes import present_evidence
from beamo_wipe.result_summary import build_result_summary
from beamo_wipe.support_export import prepare_terminal_evidence
from test_result_presentations import CASES, case_evidence

PRODUCTION_ID = "12345678-1234-1234-1234-123456789abc"


def _write(path: Path, **kwargs):
    digest = kwargs.get("source_sha256") or runtime_source_sha256() or ("b" * 64)
    return write_injected(
        path,
        source_commit=kwargs.get("source_commit", "a" * 40),
        source_sha256=digest,
        build_id=kwargs.get("build_id", PRODUCTION_ID),
        source_dirty=kwargs.get("source_dirty", False),
        allow_dirty=kwargs.get("allow_dirty", False),
        hosted=kwargs.get("hosted", False),
    )


def test_reproducible_production_identity(tmp_path):
    path = tmp_path / "build-identity.json"
    first = _write(path)
    second = _write(path)
    assert first == second
    loaded = load_build(path)
    assert loaded["status"] == STATUS_PRODUCTION
    assert loaded["source_commit"] == "a" * 40
    assert loaded["build_id"] == PRODUCTION_ID
    assert loaded["source_dirty"] is False
    ident = evidence_identity(loaded)
    assert ident["build_status"] == STATUS_PRODUCTION
    assert ident["source_commit"] == "a" * 40


def test_dirty_build_is_not_production(tmp_path):
    path = tmp_path / "build-identity.json"
    _write(path, source_dirty=True, allow_dirty=True)
    loaded = load_build(path)
    assert loaded["status"] == STATUS_DIRTY
    assert loaded["build_id"] == PRODUCTION_ID
    assert evidence_identity(loaded)["build_status"] == STATUS_DIRTY


def test_local_build_is_development(tmp_path):
    path = tmp_path / "build-identity.json"
    _write(path, build_id="local")
    assert load_build(path)["status"] == STATUS_DEVELOPMENT


def test_absent_and_invalid_metadata_are_unavailable(tmp_path):
    missing = tmp_path / "missing.json"
    assert load_build(missing)["status"] == STATUS_UNAVAILABLE
    bad = tmp_path / "build-identity.json"
    bad.write_text(json.dumps({"source_commit": "a" * 40, "hostname": "secret"}))
    assert load_build(bad)["status"] == STATUS_UNAVAILABLE
    ident = evidence_identity(load_build(bad))
    assert ident["source_commit"] == ""
    assert ident["build_id"] == ""
    assert ident["build_status"] == STATUS_UNAVAILABLE


def test_hash_mismatch_is_explicit(tmp_path):
    path = tmp_path / "build-identity.json"
    _write(path, source_sha256="c" * 64)
    assert load_build(path)["status"] == STATUS_MISMATCH


def test_hosted_production_refuses_local_and_dirty_identity():
    with pytest.raises(RuntimeError, match="BUILD_ID"):
        assert_injectable(
            build_id="local", source_dirty=False, allow_dirty=False, hosted=True
        )
    with pytest.raises(RuntimeError, match="dirty"):
        assert_injectable(
            build_id=PRODUCTION_ID, source_dirty=True, allow_dirty=False, hosted=False
        )
    assert_injectable(
        build_id=PRODUCTION_ID, source_dirty=True, allow_dirty=True, hosted=False
    )


def test_schema_v1_migrates_without_claiming_a_release(tmp_path):
    _, ev, _ = case_evidence(CASES[0])
    v1 = copy.deepcopy(ev)
    v1["schema_version"] = 1
    for key in ("source_commit", "build_id", "build_status", "source_dirty"):
        v1.pop(key, None)
    v1["timestamps"].pop("duration_source", None)
    v1["timestamps"].pop("wall_confidence", None)
    v1["timestamps"].pop("wall_provenance", None)
    assert present_evidence(v1).code == "verified"
    text = build_result_summary(v1, evidence_sha256="a" * 64)
    assert "Wrapper commit: unavailable" in text
    assert "Release build: unavailable" in text
    assert "Build status: unavailable" in text
    v3 = copy.deepcopy(ev)
    v3["schema_version"] = 3
    assert present_evidence(v3).code == "indeterminate"


def test_schema_v1_and_v2_finished_records_export(tmp_path):
    from beamo_wipe.evidence import write_evidence_atomic

    _, ev, _ = case_evidence(CASES[0])
    target = ev["device"]["path"]
    path = write_evidence_atomic(ev, log_dir=tmp_path, device_path=target, target_device=target)
    verified = prepare_terminal_evidence(path, target)
    assert json.loads(verified.data)["schema_version"] == SCHEMA_VERSION
    v1 = json.loads(path.read_text(encoding="utf-8"))
    v1["schema_version"] = 1
    path_v1 = write_evidence_atomic(v1, log_dir=tmp_path, device_path=target, target_device=target)
    old = prepare_terminal_evidence(path_v1, target)
    assert json.loads(old.data)["schema_version"] == 1


def test_clock_jump_does_not_change_monotonic_duration():
    _, ev, _ = case_evidence(CASES[0])
    ev = copy.deepcopy(ev)
    ev["timestamps"]["started_monotonic"] = 10.0
    ev["timestamps"]["ended_monotonic"] = 70.0
    ev["timestamps"]["duration_s"] = 60.0
    ev["timestamps"]["started_at_wall"] = "2026-09-09T12:00:00Z"
    ev["timestamps"]["ended_at_wall"] = "2026-09-09T11:00:00Z"
    ev["timestamps"]["wall_confidence"] = "unverified"
    ev["timestamps"]["wall_provenance"] = "os_utc"
    text = build_result_summary(ev, evidence_sha256="a" * 64)
    assert "Elapsed: 1 minute" in text
    assert "Clock: unverified (os_utc)" in text


def test_invalid_dates_are_unavailable():
    walls = wall_timestamps("yesterday", "2026-13-40T99:99:99Z", "os_utc")
    assert walls["started_at_wall"] == ""
    assert walls["ended_at_wall"] == ""
    assert walls["wall_confidence"] == "unavailable"
    assert valid_wall("2026-09-09 12:00:00") == ""
    assert valid_wall("2026-09-09T12:00:00+12:00") == ""
    assert valid_wall("2026-09-09T12:00:00Z") == "2026-09-09T12:00:00Z"


def test_timezone_change_cannot_leak_into_utc_stamps(monkeypatch):
    from beamo_wipe.evidence import _iso_now_wall

    monkeypatch.setenv("TZ", "Pacific/Auckland")
    if hasattr(time, "tzset"):
        time.tzset()
    stamp = _iso_now_wall()
    assert stamp.endswith("Z")
    assert "+" not in stamp
    assert valid_wall(stamp) == stamp
    monkeypatch.setenv("TZ", "UTC")
    if hasattr(time, "tzset"):
        time.tzset()


def test_format_alone_does_not_verify_a_clock():
    walls = wall_timestamps("2026-09-09T12:00:00Z", "2026-09-09T12:01:00Z", "os_utc")
    assert walls["wall_confidence"] == "unverified"
    ignored = wall_timestamps("2026-09-09T12:00:00Z", "2026-09-09T12:01:00Z", "unavailable")
    assert ignored["wall_confidence"] == "unavailable"
    assert ignored["started_at_wall"] == ""


def test_injected_identity_reaches_evidence(tmp_path, monkeypatch):
    path = tmp_path / "build-identity.json"
    _write(path, build_id=PRODUCTION_ID)
    monkeypatch.setattr("beamo_wipe.build_identity.BUILD_PATH", path)
    _, ev, _ = case_evidence(CASES[0])
    assert ev["schema_version"] == 2
    assert ev["build_status"] == STATUS_PRODUCTION
    assert ev["source_commit"] == "a" * 40
    assert ev["build_id"] == PRODUCTION_ID
    text = build_result_summary(ev, evidence_sha256="a" * 64)
    assert f"Wrapper commit: {'a' * 40}" in text
    assert f"Release build: {PRODUCTION_ID}" in text
    assert "Build status: production" in text


def test_classify_status_matrix():
    digest = "b" * 64
    assert classify_status(
        build_id=PRODUCTION_ID, source_dirty=True, source_sha256=digest, runtime_sha256=digest
    ) == STATUS_DIRTY
    assert classify_status(
        build_id="local", source_dirty=False, source_sha256=digest, runtime_sha256=digest
    ) == STATUS_DEVELOPMENT
    assert classify_status(
        build_id=PRODUCTION_ID, source_dirty=False, source_sha256=digest, runtime_sha256=digest
    ) == STATUS_PRODUCTION
    assert classify_status(
        build_id=PRODUCTION_ID, source_dirty=False, source_sha256=digest, runtime_sha256=None
    ) == STATUS_MISMATCH
