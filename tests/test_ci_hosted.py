# SPDX-License-Identifier: GPL-3.0-or-later
"""Google Cloud Build is the project's CI. GitHub Actions is not used."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_hosted_gate_runs_full_pipeline_on_cloud_build():
    cfg = (ROOT / "cloudbuild.yaml").read_text(encoding="utf-8")
    assert "ci-hosted.sh lint" in cfg
    assert "ci-hosted.sh tests" in cfg
    assert "ci-hosted.sh preview" in cfg
    assert "ci-hosted.sh negative" in cfg
    assert "ci-hosted.sh iso" in cfg
    assert "ci-hosted.sh qemu" in cfg
    assert "E2_HIGHCPU_8" in cfg
    assert "_SKIP_ISO" in cfg
    assert "_SKIP_QEMU" in cfg
    # QEMU needs the built ISO, so it must wait for the ISO step.
    qemu_at = cfg.find("qemu-verify")
    assert qemu_at != -1
    assert "waitFor: ['iso-build']" in cfg[qemu_at:]
    # Negative test must run after the test step so its temporary
    # safety.py patch cannot corrupt the parallel pytest run.
    assert "waitFor: ['python-tests']" in cfg
    submit = (ROOT / "scripts" / "ci-cloud.sh").read_text(encoding="utf-8")
    assert "--project=" in submit
    assert "beamo-wipe" in submit
    hosted = (ROOT / "scripts" / "ci-hosted.sh").read_text(encoding="utf-8")
    assert "xvfb-run" in hosted
    assert "BEAMO_WIPE_DRY_RUN" in hosted
    assert "build-iso.sh" in hosted
    assert "qemu-verify.sh" in hosted
    assert "SKIP_QEMU" in hosted
    # lb-config live-image tests skip when bootstrap/binary are absent.
    assert "test_iso_build_uses_https_debian_mirrors" in hosted
    assert "test_live_config_xinit_cannot_hijack_kiosk" in hosted
    assert (ROOT / "scripts" / "install-cloud-triggers.sh").is_file()


def test_github_actions_not_used():
    # No GitHub workflow may remain: billing is disabled there and Cloud
    # Build is the gate. Templates and agent instructions are not CI.
    workflows = ROOT / ".github" / "workflows"
    assert not workflows.exists(), f"{workflows} must not exist"


def test_cloud_triggers_cover_prs_and_main():
    text = (ROOT / "scripts" / "install-cloud-triggers.sh").read_text(encoding="utf-8")
    assert "beamo-wipe-pr-gate" in text
    assert "beamo-wipe-main-gate" in text
    assert "--pull-request-pattern" in text
    assert "--branch-pattern" in text
    # QEMU (TCG, slowest) runs on pushes to main; PRs run the rest.
    assert "_SKIP_QEMU=true" in text


def test_shell_embedded_python_parses():
    """Every `<<'PY'` heredoc in scripts must compile.

    Shell functions indent their bodies, but Python rejects indented
    top-level statements — an indented heredoc fails the gate with
    IndentationError before doing anything (caught once in
    ci-hosted.sh run_negative).
    """
    import re

    for script in sorted((ROOT / "scripts").glob("*.sh")):
        text = script.read_text(encoding="utf-8")
        for m in re.finditer(r"<<'PY'\n(.*?)^PY$", text, re.S | re.M):
            compile(m.group(1), str(script), "exec")


def test_cloud_submit_uploads_git_metadata():
    """`.gcloudignore` must not exclude `.git/`.

    The hosted gate runs `tests/test_release_manifest.py`, which requires
    `git rev-parse HEAD` (fail-closed "untraceable source state" without
    it), and manifest/ISO generation records the source commit. Excluding
    `.git/` reds python-tests (13 failures) on every `ci-cloud.sh` submit.
    """
    rules = [
        line.strip()
        for line in (ROOT / ".gcloudignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert ".git/" not in rules
    assert "**/.git/" not in rules
