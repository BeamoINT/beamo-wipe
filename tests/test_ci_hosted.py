# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_hosted_gate_runs_pytest_and_iso_on_cloud_build():
    cfg = (ROOT / "cloudbuild.yaml").read_text(encoding="utf-8")
    assert "ci-hosted.sh tests" in cfg
    assert "ci-hosted.sh iso" in cfg
    assert "E2_HIGHCPU_8" in cfg
    submit = (ROOT / "scripts" / "ci-cloud.sh").read_text(encoding="utf-8")
    assert "--project=" in submit
    assert "beamo-wipe" in submit
    hosted = (ROOT / "scripts" / "ci-hosted.sh").read_text(encoding="utf-8")
    assert "xvfb-run" in hosted
    assert "BEAMO_WIPE_DRY_RUN" in hosted
    assert "build-iso.sh" in hosted
    assert (ROOT / "scripts" / "install-cloud-triggers.sh").is_file()


def test_github_actions_is_manual_only():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch" in text
    assert "pull_request" not in text
