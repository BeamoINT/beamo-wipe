# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression coverage for the 2026-09-03 security audit (fake data only)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


def test_untrusted_metadata_removes_unicode_terminal_and_bidi_controls():
    from beamo_wipe.discover import _clean

    assert _clean("Safe\u202eEXE\u009b31m\u200b") == "SafeEXE31m"


def test_diagnostic_log_does_not_bypass_unsafe_default_dir(monkeypatch, capsys):
    import beamo_wipe.safety as safety
    from beamo_wipe.diagnostics import log_diag

    def unsafe():
        raise safety.SafetyError("unsafe")

    monkeypatch.setattr(safety, "default_log_dir", unsafe)
    assert not log_diag("audit", "unsafe-dir", "secret\u202etext")
    assert "secret text" in capsys.readouterr().err


def test_diagnostic_reader_refuses_symlink(tmp_path):
    from beamo_wipe.diagnostics import read_diagnostics

    outside = tmp_path / "outside"
    outside.write_text('{"area":"forged"}\n', encoding="utf-8")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "diagnostics.log").symlink_to(outside)
    assert read_diagnostics(logs) == []


def test_evidence_sidecar_binds_hash_and_exact_filename(tmp_path):
    from beamo_wipe.evidence import verify_evidence_checksum

    evidence = tmp_path / "result-safe.json"
    evidence.write_text("{}\n", encoding="utf-8")
    sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
    sidecar = Path(str(evidence) + ".sha256")
    sidecar.write_text(f"{sha}  another.json\n", encoding="ascii")
    assert not verify_evidence_checksum(evidence)
    sidecar.write_text(f"{sha}  {evidence.name}\nextra\n", encoding="ascii")
    assert not verify_evidence_checksum(evidence)


def test_evidence_reader_refuses_symlink(tmp_path):
    from beamo_wipe.evidence import load_evidence
    from beamo_wipe.safety import SafetyError

    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    link = tmp_path / "result-link.json"
    link.symlink_to(outside)
    with pytest.raises(SafetyError, match="safely read"):
        load_evidence(link)


def _manifest_for(root: Path, iso_bytes: bytes = b"known image") -> Path:
    import beamo_wipe.release_manifest as rm

    dist = root / "dist"
    dist.mkdir()
    iso = dist / "beamo-wipe-1.2.3-amd64.iso"
    iso.write_bytes(iso_bytes)
    iso_sha = hashlib.sha256(iso_bytes).hexdigest()
    Path(str(iso) + ".sha256").write_text(
        f"{iso_sha}  {iso.name}\n", encoding="ascii"
    )
    body = {
        "schema_version": 1,
        "beamo_wipe_version": "1.2.3",
        "source": {"dirty": False},
        "nwipe": {"version": "0.42", "commit": "a" * 40},
        "artifact": {
            "iso_name": iso.name,
            "iso_path": iso.name,
            "iso_size_bytes": len(iso_bytes),
            "iso_sha256": iso_sha,
        },
    }
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    body["_manifest_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    manifest = dist / "beamo-wipe-1.2.3-amd64.manifest.json"
    rm.write_manifest(body, manifest)
    return manifest


def test_manifest_verification_hashes_actual_iso_bytes(tmp_path, monkeypatch):
    import beamo_wipe.release_manifest as rm

    monkeypatch.setattr(rm, "ROOT", tmp_path)
    manifest = _manifest_for(tmp_path)
    rm.verify_manifest(manifest)
    (tmp_path / "dist" / "beamo-wipe-1.2.3-amd64.iso").write_bytes(b"altered")
    with pytest.raises(RuntimeError, match="ISO checksum mismatch"):
        rm.verify_manifest(manifest)


def test_manifest_verification_rejects_iso_path_escape(tmp_path, monkeypatch):
    import beamo_wipe.release_manifest as rm

    monkeypatch.setattr(rm, "ROOT", tmp_path)
    manifest = _manifest_for(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["artifact"]["iso_path"] = "../outside.iso"
    no_hash = {k: v for k, v in data.items() if k != "_manifest_sha256"}
    canonical = json.dumps(no_hash, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    data["_manifest_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    raw = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    manifest.write_text(raw, encoding="utf-8")
    Path(str(manifest) + ".sha256").write_text(
        f"{hashlib.sha256(raw.encode()).hexdigest()}  {manifest.name}\n",
        encoding="ascii",
    )
    with pytest.raises(RuntimeError, match="escapes"):
        rm.verify_manifest(manifest)


def test_manifest_verifies_after_release_directory_relocation(tmp_path, monkeypatch):
    import shutil

    import beamo_wipe.release_manifest as rm

    monkeypatch.setattr(rm, "ROOT", tmp_path)
    manifest = _manifest_for(tmp_path)
    release = tmp_path / "downloaded-release"
    release.mkdir()
    for source in manifest.parent.iterdir():
        shutil.copy2(source, release / source.name)

    rm.verify_manifest(release / manifest.name)


def test_gallery_payload_cannot_close_script_element(monkeypatch):
    import beamo_wipe.gallery as gallery

    monkeypatch.setattr(gallery.C, "APP_NAME", "</script><script>alert(1)</script>")
    html = gallery.gallery_html()
    assert "</script><script>alert(1)</script>" not in html
    assert "\\u003c/script\\u003e" in html


def test_owner_ui_does_not_show_discovery_diagnostic():
    from beamo_wipe.models import DiscoveryResult
    from beamo_wipe.nwipe_runner import DryRunRunner
    from beamo_wipe.wizard import Screen, Wizard

    result = DiscoveryResult(
        error="Cannot safely identify the Beamo boot device.",
        diagnostic="findmnt failed at /private/customer/path",
    )
    wizard = Wizard(result, DryRunRunner())
    wizard.screen = Screen.OWNER
    wizard.owner_ok = True
    wizard.continue_owner()
    assert wizard.screen == Screen.PICK_BLOCKED
    assert wizard.error == result.error
    assert "customer" not in (wizard.error or "")


def test_required_boot_alias_check_fails_closed_when_nodes_missing():
    from beamo_wipe.safety import SafetyError, assert_not_boot

    with pytest.raises(SafetyError, match="Cannot prove"):
        assert_not_boot("/dev/vda", "/dev/sr0", required=True)


def test_real_discovery_rejects_missing_ro_or_mountpoint_metadata(monkeypatch):
    import beamo_wipe.discover as discover

    payload = {
        "blockdevices": [
            {"name": "sdb", "path": "/dev/sdb", "type": "disk", "size": 10}
        ]
    }
    monkeypatch.setattr(discover, "run_lsblk", lambda: payload)
    result = discover.discover(boot_path="/dev/sdb", env={})
    assert not result.boot_identified
    assert result.error


def test_final_nvme_transport_check_rejects_fabrics(monkeypatch):
    from beamo_wipe.safety import SafetyError, assert_local_device_transport

    monkeypatch.delenv("BEAMO_WIPE_DRY_RUN", raising=False)
    monkeypatch.delenv("BEAMO_WIPE_DEMO", raising=False)
    original = Path.read_text

    def fake_read(self, *args, **kwargs):
        if str(self) == "/sys/class/nvme/nvme7/transport":
            return "tcp\n"
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read)
    with pytest.raises(SafetyError, match="remote or unknown"):
        assert_local_device_transport("/dev/nvme7n2")


def test_nwipe_build_hook_cannot_mask_source_or_build_failure():
    hook = Path("packaging/live/config/hooks/normal/0500-build-nwipe.hook.chroot").read_text()
    for command in ("git clone", "./autogen.sh", "./configure", "make install"):
        for line in hook.splitlines():
            if command in line:
                assert "| tee" not in line
                assert "|| true" not in line
    assert "mktemp -d /tmp/beamo-wipe-nwipe.XXXXXX" in hook
    assert "git rev-parse HEAD" in hook
    assert "NWIPE_COMMIT" in hook


def test_qemu_gate_has_no_unverified_or_host_binary_fallback():
    script = Path("scripts/qemu-verify.sh").read_text(encoding="utf-8")
    assert "mktemp -d /tmp/beamo-wipe-qemu.XXXXXX" in script
    assert "verify_manifest" in script
    assert "exact versioned ISO and manifest are required" in script
    assert "command -v nwipe" not in script
    assert "apt fallback" not in script.casefold()
    assert "still usable" not in script.casefold()
    assert "MODEL,SERIAL" not in script
    assert "debsecan --suite bookworm --only-fixed" in script
    assert "--quiet" in script
    assert "required libparted2 dependency missing from ISO: dmidecode" in script
    assert "unsafe dmidecode helper permissions" in script
    assert "qemu verification failed at line" in script
    assert "artifact checksums verified" in script
    assert "live filesystem package and permission policy verified" in script
    assert '[[ "$nwipe_code" == 0 ]]' in script
    assert '[[ "$bad_code" != 0 ]]' in script


def test_build_environment_and_output_names_are_pinned():
    build = Path("scripts/build-iso.sh").read_text(encoding="utf-8")
    inside = Path("packaging/live/inside-docker.sh").read_text(encoding="utf-8")
    manifest = Path("scripts/generate-release-manifest.sh").read_text(encoding="utf-8")
    assert "debian:bookworm@sha256:" in build
    assert "beamo-wipe-docker.XXXXXX" in build
    assert "/tmp/beamo-docker-info.log" not in build
    assert "must produce exactly one ISO" in inside
    assert "head -n 1" not in inside
    assert '"$DEST" != "$EXPECTED_DEST"' in manifest
    assert "git status --short" not in manifest


def test_live_image_omits_out_of_scope_destructive_and_admin_tools():
    packages = {
        line.strip()
        for line in Path(
            "packaging/live/config/package-lists/beamo.list.chroot"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert not packages.intersection(
        {"nano", "less", "iproute2", "dmidecode", "pciutils", "usbutils", "eject"}
    )
    assert "hdparm" in packages  # pinned nwipe uses read-only -N/DCO discovery


def test_no_open_mode_never_invokes_browser_for_helper(tmp_path, monkeypatch):
    import webbrowser
    from beamo_wipe.app import _open_html

    helper = tmp_path / "helper.html"
    helper.write_text("safe", encoding="utf-8")
    monkeypatch.setenv("BEAMO_WIPE_NO_OPEN", "1")
    monkeypatch.setattr(
        webbrowser,
        "open",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("browser opened")),
    )
    assert _open_html(helper) == 0
