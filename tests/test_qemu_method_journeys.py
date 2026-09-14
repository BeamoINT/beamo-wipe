# SPDX-License-Identifier: GPL-3.0-or-later
"""QEMU verify enumerates production methods on isolated disposable disks."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess

from beamo_wipe.methods import METHODS
from beamo_wipe.models import MethodId


ROOT = Path(__file__).resolve().parents[1]
QEMU = ROOT / "scripts/qemu-verify.sh"


def _cases() -> list[dict[str, str]]:
    text = QEMU.read_text(encoding="utf-8")
    block = text.split("METHOD_CASES=$(cat <<'EOF'\n", 1)[1].split("\nEOF\n", 1)[0]
    rows = []
    for line in block.splitlines():
        case, key, nwipe_method, verify, outcome, host_timeout, guest_timeout, serial = line.split("|")
        rows.append(
            {
                "case": case,
                "key": key,
                "nwipe_method": nwipe_method,
                "verify": verify,
                "outcome": outcome,
                "host_timeout": host_timeout,
                "guest_timeout": guest_timeout,
                "serial": serial,
            }
        )
    return rows


def test_qemu_method_table_matches_production_methods():
    rows = {row["case"]: row for row in _cases()}
    assert set(rows) == {"everyday", "extra", "quick_zero"}
    mapping = {
        "everyday": MethodId.EVERYDAY,
        "extra": MethodId.EXTRA,
        "quick_zero": MethodId.QUICK_ZERO,
    }
    for name, method_id in mapping.items():
        spec = METHODS[method_id]
        row = rows[name]
        assert row["nwipe_method"] == spec.nwipe_method
        assert row["verify"] == spec.verify
        assert spec.rounds == 1
        assert spec.noblank is True
        assert int(row["host_timeout"]) >= 60
        assert int(row["guest_timeout"]) >= 180
    assert rows["everyday"]["key"] == "1"
    assert rows["extra"]["key"] == "2"
    assert rows["quick_zero"]["key"] == "3"
    assert len({row["serial"] for row in rows.values()}) == 3


def test_qemu_does_not_weaken_production_methods_for_speed():
    text = QEMU.read_text(encoding="utf-8")
    methods_src = (ROOT / "src/beamo_wipe/methods.py").read_text(encoding="utf-8")
    assert 'nwipe_method="prng"' in methods_src
    assert 'nwipe_method="dodshort"' in methods_src
    assert 'nwipe_method="zero"' in methods_src
    assert 'verify="last"' in methods_src
    assert 'verify="off"' in methods_src
    assert "rounds=1" in methods_src
    assert "|prng|last|verified|" in text
    assert "|dodshort|last|verified|" in text
    assert "|zero|off|completed|" in text
    assert '--method="$nwipe_method"' in text
    assert "HOST_METHOD_BYTES=67108864" in text
    assert re.search(r"timeout \"\$timeout_s\" \"\$NWIPE_BIN\"", text)


def test_qemu_isolates_method_disks_and_reports():
    text = QEMU.read_text(encoding="utf-8")
    assert 'target-${case}.qcow2' in text
    assert 'report-${case}.raw' in text
    assert "host-${case}.raw" in text
    assert "record_qemu_cmdline" in text
    assert "ABORT: QEMU command mentions a host block device" in text
    assert "-nic none" in text
    assert "if=virtio,/dev" not in text
    assert "file=/dev/sd" not in text
    assert "file=/dev/nvme" not in text
    assert "bios-${case}" in text
    assert 'cases=%s' in text
    assert "source_commit=%s" in text
    assert "iso_sha256=%s" in text
    assert "nwipe_sha256=%s" in text


def test_qemu_report_checks_method_wording_and_checksums():
    text = QEMU.read_text(encoding="utf-8")
    assert "guest report outcome" in text
    assert "RESULT.txt missing method title" in text
    assert "RESULT.txt missing verified wording" in text
    assert "RESULT.txt missing unverified wording" in text
    assert "report digest mismatch" in text
    assert "completion manifest does not match report files" in text
    assert 'method.get("nwipe_method")' in text
    assert "guest method rounds is not the production value 1" in text


def test_qemu_drive_export_uses_method_key_not_a_hardcoded_quick_zero():
    source = QEMU.read_text(encoding="utf-8")
    function = source.split("drive_report_export() {", 1)[1].split("\n}\n", 1)[0]
    assert '"$method_key"' in function
    assert "send_key_for_marker" in function
    assert '3 BEAMO_WIPE_SCREEN_METHOD' not in function


def test_qemu_repeats_each_guest_on_a_distinct_scenario():
    source = QEMU.read_text(encoding="utf-8")
    table = source.split("METHOD_CASES=$(cat <<'EOF'\n", 1)[1].split("\nEOF\n", 1)[0]
    loop = source.split('EXECUTED_CASES=""', 1)[1].split('log "all production methods', 1)[0]
    result = subprocess.run(
        ["bash", "-ceu", 'METHOD_CASES=$(cat <<\'EOF\'\n' + table
         + '\nEOF\n)\nEXECUTED_CASES=""\n'
         + 'run_guest_method() { printf "%s|%s\\n" "$1" "$2"; }\n' + loop],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.splitlines() == [
        f"{scenario}|{method}" for method in ("everyday", "extra", "quick_zero")
        for scenario in (method, f"{method}-repeat")
    ]
