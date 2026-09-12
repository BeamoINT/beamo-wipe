# SPDX-License-Identifier: GPL-3.0-or-later
"""Adversarial privacy tests for the labeled sharing copy. Fake data only."""

from __future__ import annotations

import copy
import hashlib
import json

from beamo_wipe.privacy import (
    NOTICE,
    POLICY_ID,
    POLICY_VERSION,
    SHARE_JSON,
    SHARE_SUMMARY,
    UNSUITABLE,
    collect_secrets,
    encode_sharing_copy,
    is_sharing_copy,
    make_sharing_copy,
)
from beamo_wipe.result_summary import build_result_summary
from beamo_wipe.support_export import _bundle_files
from test_result_presentations import CASES, case_evidence

SERIAL = "PLANT-SERIAL-ZX9Q"
WWN = "PLANT-WWN-0xDEADBEEF"
PATH = "/dev/planteddisk0"
NAME = "planteddisk0"
LABEL = "PLANT-LABEL-OK"
BOOT = "/dev/plantedboot"
LOGFILE = "/tmp/beamo-wipe/planted-nwipe.log"
EVIDENCE_FILE = "/tmp/beamo-wipe/result-planteddisk0-1.json"
ID_VALUE = "PLANT-ID-VALUE"
ARGV_DEV = "/dev/plantedtarget"
ANNOUNCE_TOKEN = "PLANT-ANNOUNCE"
EXTRA_TOKEN = "PLANT-EXTRA-ROOT"
LOG_TOKEN = "PLANT-LOG-SECRET"
HOST_TOKEN = "planted.example.invalid"

TOKENS = (
    SERIAL,
    WWN,
    PATH,
    NAME,
    LABEL,
    BOOT,
    LOGFILE,
    EVIDENCE_FILE,
    ID_VALUE,
    ARGV_DEV,
    ANNOUNCE_TOKEN,
    EXTRA_TOKEN,
    LOG_TOKEN,
    HOST_TOKEN,
)


def _planted_evidence():
    _, ev, _ = case_evidence(CASES[0])
    ev = copy.deepcopy(ev)
    ev["device"]["serial"] = SERIAL
    ev["device"]["wwn"] = WWN
    ev["device"]["path"] = PATH
    ev["device"]["realpath"] = PATH
    ev["device"]["name"] = NAME
    ev["device"]["label"] = LABEL
    ev["device"]["vendor"] = HOST_TOKEN
    ev["boot_device"] = BOOT
    ev["logfile"] = LOGFILE
    ev["failure_reason"] = f"open failed {PATH} {SERIAL}"
    ev["completion"]["reason"] = f"completed {PATH}"
    ev["warnings"] = list(ev.get("warnings") or []) + [f"see {SERIAL} {PATH}"]
    ev["nwipe"]["argv_redacted"] = ["--autonuke", ARGV_DEV]
    ev["provenance"] = {
        "evidence_file": EVIDENCE_FILE,
        "written_at_wall": "2026-09-09T12:00:00Z",
        "host": HOST_TOKEN,
    }
    presentation = dict(ev.get("device_presentation") or {})
    presentation["id_value"] = ID_VALUE
    presentation["announcement"] = f"{ANNOUNCE_TOKEN} {SERIAL} {PATH}"
    presentation["system_path"] = PATH
    ev["device_presentation"] = presentation
    result_pres = dict(ev.get("presentation") or {})
    result_pres["announcement"] = f"{ANNOUNCE_TOKEN} done"
    ev["presentation"] = result_pres
    ev["extra_secret"] = EXTRA_TOKEN
    ev["hostname"] = HOST_TOKEN
    return ev


def _assert_clean(blob: bytes | str) -> None:
    text = blob.decode("utf-8") if isinstance(blob, bytes) else blob
    lowered = text.casefold()
    for token in TOKENS:
        assert token.casefold() not in lowered, token


def test_sharing_copy_is_new_document_and_keeps_original():
    original = _planted_evidence()
    snapshot = copy.deepcopy(original)
    sharing = make_sharing_copy(original)
    assert original == snapshot
    assert is_sharing_copy(sharing)
    assert sharing["privacy"]["policy_version"] == POLICY_VERSION
    assert sharing["privacy"]["policy"] == POLICY_ID
    assert sharing["privacy"]["unsuitable_for_identity_evidence"] is True
    assert sharing["privacy"]["notice"] == NOTICE
    assert sharing["outcome"] == original["outcome"]
    assert sharing["method"]["id"] == original["method"]["id"]
    assert sharing["verification"]["verified"] == original["verification"]["verified"]
    assert sharing["timestamps"]["duration_source"] == "monotonic"
    assert sharing["beamo_wipe_version"] == original["beamo_wipe_version"]
    assert "path" not in sharing.get("device", {})
    assert "serial" not in sharing.get("device", {})
    assert "wwn" not in sharing.get("device", {})
    assert "boot_device" not in sharing
    assert "logfile" not in sharing
    assert "argv_redacted" not in sharing.get("nwipe", {})
    assert "extra_secret" not in sharing
    assert "hostname" not in sharing
    assert "provenance" not in sharing
    _assert_clean(encode_sharing_copy(sharing))


def test_bundle_keeps_owner_original_and_adds_labeled_sharing_files():
    ev = _planted_evidence()
    raw = json.dumps(ev).encode()
    log = f"{LOG_TOKEN} {SERIAL} {PATH}\n".encode()
    bundle = _bundle_files(raw, log, "complete", privacy_reduced=True)
    assert bundle["result.json"] == raw
    assert SERIAL.encode() in bundle["result.json"]
    assert SERIAL.encode() in bundle["RESULT.txt"]
    assert LOG_TOKEN.encode() in bundle["nwipe.log"]
    assert SHARE_JSON in bundle
    assert SHARE_SUMMARY in bundle
    assert f"{SHARE_JSON}.sha256" in bundle
    assert f"{SHARE_SUMMARY}.sha256" in bundle
    for name, data in bundle.items():
        assert SERIAL not in name
        assert NAME not in name
        assert "planted" not in name.casefold()
        if name in {SHARE_JSON, SHARE_SUMMARY, f"{SHARE_JSON}.sha256", f"{SHARE_SUMMARY}.sha256", "COMPLETE", "README.txt"}:
            _assert_clean(data)
    sharing = json.loads(bundle[SHARE_JSON])
    assert is_sharing_copy(sharing)
    summary = bundle[SHARE_SUMMARY].decode("utf-8")
    assert NOTICE in summary
    assert UNSUITABLE in summary
    assert "Identity evidence:" in summary
    complete = json.loads(bundle["COMPLETE"])
    assert complete["share_copy"] == SHARE_JSON
    assert complete["share_summary"] == SHARE_SUMMARY
    assert complete["privacy_policy_version"] == POLICY_VERSION
    assert complete["files"][SHARE_JSON] == hashlib.sha256(bundle[SHARE_JSON]).hexdigest()
    assert complete["files"][SHARE_SUMMARY] == hashlib.sha256(bundle[SHARE_SUMMARY]).hexdigest()
    assert complete["files"]["result.json"] == hashlib.sha256(raw).hexdigest()
    readme = bundle["README.txt"].decode("utf-8")
    assert "not identity evidence" in readme.casefold()
    assert "copy only SHARE.json and SHARE.txt" in readme
    rebuilt = _bundle_files(raw, log, "complete", privacy_reduced=True)
    assert rebuilt[SHARE_JSON] == bundle[SHARE_JSON]
    assert rebuilt[SHARE_SUMMARY] == bundle[SHARE_SUMMARY]


def test_sharing_summary_checksum_is_the_sharing_json_not_the_original():
    ev = _planted_evidence()
    raw = json.dumps(ev).encode()
    bundle = _bundle_files(raw, b"", "unavailable", privacy_reduced=True)
    share_hash = hashlib.sha256(bundle[SHARE_JSON]).hexdigest()
    owner_hash = hashlib.sha256(raw).hexdigest()
    text = bundle[SHARE_SUMMARY].decode("utf-8")
    assert share_hash in text
    assert owner_hash not in text
    assert "SHARE.json" in text
    assert "result-planted" not in text


def test_without_privacy_reduced_no_sharing_files_are_emitted():
    _, ev, log = case_evidence(CASES[0])
    bundle = _bundle_files(json.dumps(ev).encode(), log.encode(), "complete")
    assert SHARE_JSON not in bundle
    assert SHARE_SUMMARY not in bundle
    complete = json.loads(bundle["COMPLETE"])
    assert complete["share_copy"] == ""
    assert complete["privacy_policy_version"] == 0


def test_collect_secrets_includes_paths_and_identifiers():
    secrets = collect_secrets(_planted_evidence())
    assert SERIAL in secrets
    assert PATH in secrets
    assert NAME in secrets
    assert BOOT in secrets
    assert ARGV_DEV in secrets


def test_result_summary_from_sharing_copy_preserves_outcome():
    _, ev, _ = case_evidence(CASES[0])
    sharing = make_sharing_copy(ev)
    text = build_result_summary(sharing, evidence_sha256="a" * 64)
    assert ev["presentation"]["message"] in text
    assert NOTICE in text.splitlines()[0]
    assert "Serial: withheld" in text
    assert "Hardware ID: withheld" in text
    assert UNSUITABLE in text
