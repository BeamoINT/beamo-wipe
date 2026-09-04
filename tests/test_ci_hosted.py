# SPDX-License-Identifier: GPL-3.0-or-later
"""Google Cloud Build is the project's CI. GitHub Actions is not used."""

import os
from pathlib import Path
import subprocess
import sys

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
    assert '_PUBLISH_RELEASE: "false"' in cfg
    assert "artifacts:" not in cfg
    assert "artifacts.objects" not in cfg
    for line in cfg.splitlines():
        if line.strip().startswith("name:"):
            assert "@sha256:" in line
    # QEMU needs the built ISO, so it must wait for the ISO step.
    qemu_at = cfg.find("  - id: qemu-verify\n")
    assert qemu_at != -1
    assert "waitFor: ['iso-build']" in cfg[qemu_at:]
    publish_at = cfg.find("  - id: publish-release\n")
    assert publish_at > qemu_at
    assert "waitFor: ['qemu-verify']" in cfg[publish_at:]
    assert "cloud-builders/gsutil" not in cfg
    assert "cloud-builders/docker" not in cfg
    assert "library/python" not in cfg
    # Negative test temporarily patches safety.py, so every read-only source
    # consumer must finish before it runs and the ISO build must wait for the
    # restored tree.
    assert "waitFor: ['python-tests', 'lint', 'preview']" in cfg
    iso_at = cfg.find("  - id: iso-build\n")
    assert iso_at != -1
    assert "waitFor: ['negative-test']" in cfg[iso_at:qemu_at]
    iso_step = cfg[iso_at:qemu_at]
    assert "ca-certificates docker.io git python3" in iso_step
    submit = (ROOT / "scripts" / "ci-cloud.sh").read_text(encoding="utf-8")
    assert "--project=" in submit
    assert "beamo-wipe" in submit
    assert "--publish-release" in submit
    publisher = (ROOT / "scripts" / "publish_release_gcs.py").read_text(encoding="utf-8")
    assert 'os.environ.get("PUBLISH_RELEASE", "false")' in publisher
    assert "SKIP_ISO" in publisher and "SKIP_QEMU" in publisher
    assert '"ifGenerationMatch": "0"' in publisher
    assert "RELEASE_COMPLETE.txt" in publisher
    assert '_git("tag", "--points-at"' in publisher
    assert "verify_manifest" in publisher
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


def test_release_publisher_is_default_off_and_rejects_skipped_gates():
    script = ROOT / "scripts" / "publish_release_gcs.py"
    env = os.environ.copy()
    for name in ("PUBLISH_RELEASE", "SKIP_ISO", "SKIP_QEMU", "BUILD_ID"):
        env.pop(name, None)
    disabled = subprocess.run(  # noqa: S603
        [sys.executable, str(script)],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert disabled.returncode == 0
    assert "disabled" in disabled.stdout.lower()

    env.update(
        {
            "PUBLISH_RELEASE": "true",
            "SKIP_ISO": "true",
            "BUILD_ID": "00000000-0000-0000-0000-000000000000",
        }
    )
    skipped = subprocess.run(  # noqa: S603
        [sys.executable, str(script)],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert skipped.returncode == 2
    assert "skipped iso or qemu gate" in skipped.stderr.lower()


def test_cloud_submit_rejects_hidden_or_wrong_project_publication():
    script = ROOT / "scripts" / "ci-cloud.sh"
    env = os.environ.copy()
    env["SUBSTITUTIONS"] = "_PUBLISH_RELEASE=true"
    hidden = subprocess.run(  # noqa: S603
        ["bash", str(script)],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert hidden.returncode == 2
    assert "--publish-release" in hidden.stderr

    env.pop("SUBSTITUTIONS")
    wrong_project = subprocess.run(  # noqa: S603
        ["bash", str(script), "--publish-release", "--project", "not-production"],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert wrong_project.returncode == 2
    assert "restricted to gcp project beamo-wipe" in wrong_project.stderr.lower()


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


def test_hosted_python_tests_install_git_for_fail_closed_manifest():
    """The source metadata is useless unless the test image can read it."""
    hosted = (ROOT / "scripts" / "ci-hosted.sh").read_text(encoding="utf-8")
    test_deps = hosted.split("install_test_deps() {", 1)[1].split("\n}", 1)[0]
    assert "    git \\\n" in test_deps


def test_qemu_phase_installs_pytest_for_fake_disk_gate():
    """Cloud Build step containers cannot share the earlier pip install."""
    hosted = (ROOT / "scripts" / "ci-hosted.sh").read_text(encoding="utf-8")
    qemu_deps = hosted.split("install_qemu_deps() {", 1)[1].split("\n}", 1)[0]
    assert "    python3-pytest \\\n" in qemu_deps


def test_qemu_phase_installs_pinned_nwipe_runtime_dependency():
    """The extracted v0.42 binary exits 1 when hdparm is unavailable."""
    hosted = (ROOT / "scripts" / "ci-hosted.sh").read_text(encoding="utf-8")
    qemu_deps = hosted.split("install_qemu_deps() {", 1)[1].split("\n}", 1)[0]
    assert "    hdparm \\\n" in qemu_deps


def test_iso_build_requires_and_always_generates_provenance():
    build = (ROOT / "scripts" / "build-iso.sh").read_text(encoding="utf-8")
    assert "for tool in docker awk git python3 sha256sum" in build
    assert "SKIP_MANIFEST" not in build
    assert "./scripts/generate-release-manifest.sh" in build
