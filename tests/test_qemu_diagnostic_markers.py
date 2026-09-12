# SPDX-License-Identifier: GPL-3.0-or-later
"""Boot diagnostics expose fixed classifications, never device metadata."""

from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from beamo_wipe.diagnostic_report import CODES
from beamo_wipe.models import Screen
from beamo_wipe.ui import tk_wizard


ROOT = Path(__file__).resolve().parents[1]
QEMU = ROOT / "scripts/qemu-verify.sh"
BOOT_MARKERS = {
    "BEAMO_WIPE_BOOT_FINDMNT_MULTIROW",
    "BEAMO_WIPE_BOOT_SOURCE_UNRESOLVED",
    "BEAMO_WIPE_BOOT_SOURCE_LOOP",
    "BEAMO_WIPE_BOOT_SOURCE_TYPED",
    "BEAMO_WIPE_BOOT_SOURCE_DEVICE",
    "BEAMO_WIPE_BOOT_SOURCE_OVERLAY",
    "BEAMO_WIPE_BOOT_SOURCE_OTHER",
    "BEAMO_WIPE_BOOT_SOURCE_CONFLICT",
}


def _draw_markers(monkeypatch, discovery_code, startup_code="", screen=Screen.PICK_BLOCKED):
    markers = []
    monkeypatch.setattr(tk_wizard, "emit_serial_marker", markers.append)
    app = SimpleNamespace(
        w=SimpleNamespace(
            screen=screen,
            discovery=SimpleNamespace(error_code=discovery_code, diagnostic="SERIAL_PRIVATE"),
            startup_error_code=startup_code,
        ),
        _body=SimpleNamespace(configure=lambda **kwargs: None),
        _footer=object(),
        _pick_canvas=None,
        _clear=lambda widget: None,
        _sync_chrome=lambda value: None,
        _draw_header=lambda: None,
        _draw_strip=lambda: None,
    )
    for name in (
        "_splash", "_what", "_owner", "_pick", "_blocked", "_empty", "_confirm",
        "_method", "_last", "_working", "_advanced", "_limits", "_report_help",
        "_shutdown_confirm",
    ):
        setattr(app, name, lambda: None)
    tk_wizard.TkWizard._draw(app)
    return markers


@pytest.mark.parametrize("code", sorted(CODES))
def test_blocked_screen_emits_allowlisted_discovery_code(monkeypatch, code):
    assert _draw_markers(monkeypatch, code) == [
        "BEAMO_WIPE_SCREEN_PICK_BLOCKED", f"BEAMO_WIPE_DISCOVERY_{code.upper()}",
    ]


@pytest.mark.parametrize("unknown", ["", None, [], {}, "SERIAL_PRIVATE", "io_failed\nSERIAL_PRIVATE"])
def test_blocked_screen_never_emits_unknown_or_raw_details(monkeypatch, unknown):
    assert _draw_markers(monkeypatch, unknown, unknown) == [
        "BEAMO_WIPE_SCREEN_PICK_BLOCKED", "BEAMO_WIPE_DISCOVERY_BOOT_UNIDENTIFIED",
    ]


def test_blocked_screen_uses_current_startup_failure_when_available(monkeypatch):
    assert _draw_markers(monkeypatch, "discovery_failed", "permission_denied")[-1] == (
        "BEAMO_WIPE_DISCOVERY_PERMISSION_DENIED"
    )
    assert _draw_markers(monkeypatch, "io_failed", "SERIAL_PRIVATE")[-1] == (
        "BEAMO_WIPE_DISCOVERY_IO_FAILED"
    )
    assert _draw_markers(monkeypatch, "io_failed", screen=Screen.WHAT) == [
        "BEAMO_WIPE_SCREEN_WHAT"
    ]


def _shell_function(source, name):
    return name + "() {" + source.split(name + "() {", 1)[1].split("\n}", 1)[0] + "\n}\n"


def test_qemu_summary_prints_only_exact_allowed_marker_counts(tmp_path):
    source = QEMU.read_text(encoding="utf-8")
    markers = BOOT_MARKERS | {f"BEAMO_WIPE_DISCOVERY_{code.upper()}" for code in CODES}
    private = "BEAMO_WIPE_DISCOVERY_SERIAL_PRIVATE"
    lines = [private, "SERIAL_PRIVATE"]
    for marker in sorted(markers):
        lines.extend([marker, marker + "\r", marker + " SERIAL_PRIVATE", "prefix " + marker])
    (tmp_path / "bios-serial.txt").write_text("\n".join(lines) + "\n", encoding="ascii")
    script = (
        _shell_function(source, "marker_count")
        + _shell_function(source, "report_marker_summary")
        + '\nEVIDENCE_DIR="$1"\nreport_marker_summary bios\n'
    )
    result = subprocess.run(  # noqa: S603
        ["/bin/bash", "-c", script, "proof", str(tmp_path)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stdout
    assert set(result.stderr.splitlines()) == {
        f"QEMU bios observed exact marker {marker} count=2" for marker in markers
    }


@pytest.mark.parametrize("exercise_export", ["yes", "no"])
def test_successful_boot_probe_preserves_safe_marker_summary(tmp_path, exercise_export):
    source = QEMU.read_text(encoding="utf-8")
    script = """
set -eu
RUN_ROOT="$1"
EVIDENCE_DIR="$1"
ISO=unused
TARGET=unused
QEMU_TARGET_SERIAL=unused
BOOT_WAIT_SECONDS=1
BIOS_PID=""
UEFI_PID=""
qemu-system-x86_64() {
  printf '%s\\n' BEAMO_WIPE_BOOT_FINDMNT_MULTIROW SERIAL_PRIVATE > "$EVIDENCE_DIR/bios-serial.txt"
}
wait_for_qmp() { wait "$BIOS_PID"; }
wait_for_marker() { :; }
send_key_for_marker() { :; }
drive_report_export() { :; }
kill() { :; }
stop_pid() { :; }
log() { :; }
"""
    for name in ("marker_count", "report_marker_summary", "record_qemu_cmdline", "boot_probe"):
        script += _shell_function(source, name)
    script += '\nboot_probe bios "$2"\n'
    result = subprocess.run(  # noqa: S603
        ["/bin/bash", "-c", script, "proof", str(tmp_path), exercise_export],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == (
        "QEMU bios observed exact marker BEAMO_WIPE_BOOT_FINDMNT_MULTIROW count=1\n"
    )
    assert not result.stdout
