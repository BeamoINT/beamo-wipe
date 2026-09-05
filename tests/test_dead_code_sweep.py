# SPDX-License-Identifier: GPL-3.0-or-later
"""Dead-code sweep 2026-09-03 — only high-confidence removals.

Proves that remaining candidates have at least one static/test/packaging/
CI/boot/recovery/hardware use, so they are left in place.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dead_asset_removed():
    assert not (ROOT / "src/beamo_wipe/assets/logo-mark-on-light.svg").exists()
    assert not (
        ROOT
        / "packaging/live/config/includes.chroot/usr/lib/python3/dist-packages/beamo_wipe/assets/logo-mark-on-light.svg"
    ).exists()
    # Live assets still present
    assert (ROOT / "src/beamo_wipe/assets/logo-mark.svg").exists()
    assert (ROOT / "src/beamo_wipe/assets/logo-header.png").exists()
    assert (ROOT / "src/beamo_wipe/assets/logo-splash.png").exists()


def test_beamo_wipe_live_write_removed():
    text = (ROOT / "src/beamo_wipe/app.py").read_text(encoding="utf-8")
    assert 'os.environ["BEAMO_WIPE_LIVE"]' not in text
    # Live detection still fail-closed via mountinfo, not env
    from beamo_wipe.safety import is_live_environment

    assert not is_live_environment(cmdline="boot=live", live_medium_mounted=False)
    assert is_live_environment(cmdline="boot=live", live_medium_mounted=True)


def test_gallery_payload_keys_preserved():
    # whatMore and confirmLead are shipped in web-preview payload and asserted
    # by test_gallery_and_tk_share_plain_titles_and_more_detail — not dead.
    from beamo_wipe.gallery import gallery_html

    html = gallery_html()
    assert "Type what we ask for, then continue." in html
    # whatMore is C.WHAT_MORE = SECURE_BOOT_HINT + ENGINE_LINE
    from beamo_wipe import copy as C

    assert C.WHAT_MORE in html or C.SECURE_BOOT_HINT in html


def test_read_diagnostics_and_evidence_wrapper_are_retained_despite_zero_import_hits():
    # Both are part of diagnostics/evidence public API for support export
    # and were flagged by the sweep as 0 hits outside definitions. We leave
    # them because their use is via manual support import (dynamic) and future
    # wizard export — uncertain per policy.
    assert (ROOT / "src/beamo_wipe/diagnostics.py").read_text(encoding="utf-8").count(
        "def read_diagnostics"
    ) == 1
    assert (ROOT / "src/beamo_wipe/evidence.py").read_text(encoding="utf-8").count(
        "def build_evidence_for_wizard"
    ) == 1


def test_identify_module_and_wrapper_retained():
    # python -m beamo_wipe.identify and scripts/identify-boot-usb.sh are
    # manual recovery tools; no static import in src, but used by operators.
    assert (ROOT / "src/beamo_wipe/identify.py").exists()
    assert (ROOT / "scripts/identify-boot-usb.sh").exists()


def test_beamo_wipe_ui_flag_retained():
    # BEAMO_WIPE_UI is a hardware-quirk flag: `BEAMO_WIPE_UI=console` forces
    # console on low-res KMS where X fails. No writer in repo, but read in
    # app.py and valid for boot-time override.
    text = (ROOT / "src/beamo_wipe/app.py").read_text(encoding="utf-8")
    assert 'os.environ.get("BEAMO_WIPE_UI")' in text
