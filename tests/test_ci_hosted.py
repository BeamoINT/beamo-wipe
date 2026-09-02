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


def test_github_actions_gates_prs_and_main():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    # Must gate PRs and pushes to main, not manual-only
    assert "pull_request" in text
    assert "push" in text
    assert "workflow_dispatch" in text
    assert "branches: [main]" in text
    # Must pin actions and use least privilege
    assert "permissions:" in text and "contents: read" in text
    assert "concurrency:" in text and "cancel-in-progress: true" in text
    assert "actions/checkout@11d5960" in text
    assert "actions/setup-python@a26af69" in text
    # Must run under Xvfb 72 DPI and skip live-image tests when files missing
    assert "xvfb-run" in text and "72" in text
    assert "BEAMO_WIPE_DRY_RUN" in text
    # Must include lint, preview, and negative-test
    assert "ruff" in text or "py_compile" in text
    assert "preview --web" in text
    assert "negative-test" in text
    # ISO must be built on x86_64 with artifact retention
    assert "build-iso.sh" in text
    assert "upload-artifact@ea165f8" in text
    assert "retention-days:" in text
    # 90 days for ISO+manifest, at least 14
    import re

    m = re.search(r"retention-days:\s*(\d+)", text)
    assert m and int(m.group(1)) >= 14
