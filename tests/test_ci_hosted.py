# SPDX-License-Identifier: GPL-3.0-or-later
"""Google Cloud Build is the project's CI. GitHub Actions is not used."""

import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_hosted_gate_runs_full_pipeline_on_cloud_build():
    cfg = (ROOT / "cloudbuild.yaml").read_text(encoding="utf-8")
    assert "ci-hosted.sh lint" in cfg
    assert "ci-hosted.sh tests" in cfg
    assert "ci-hosted.sh preview" in cfg
    assert "ci-hosted.sh negative" in cfg
    assert "ci-hosted.sh iso" in cfg
    assert "ci-hosted.sh qemu" in cfg
    assert "ci-hosted.sh desktop-launchers" in cfg
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
    publish_step = cfg[publish_at:]
    assert "waitFor: ['qemu-verify']" in publish_step
    assert "BUILD_ID=$BUILD_ID" in publish_step
    assert "ci_evidence summary" in publish_step
    assert "cloud-builders/gsutil" not in cfg
    assert "cloud-builders/docker" not in cfg
    assert "library/python" not in cfg
    # Negative test temporarily patches safety.py, so every read-only source
    # consumer must finish before it runs and the ISO build must wait for the
    # restored tree.
    assert "waitFor: ['python-tests', 'lint', 'preview', 'desktop-launchers']" in cfg
    iso_at = cfg.find("  - id: iso-build\n")
    assert iso_at != -1
    assert "waitFor: ['negative-test', 'desktop-launchers']" in cfg[iso_at:qemu_at]
    assert "ci-hosted.sh desktop-launchers" in cfg
    iso_step = cfg[iso_at:qemu_at]
    assert "ca-certificates docker.io git python3" in iso_step
    from beamo_wipe import __version__ as wrapper_version

    for line in cfg.splitlines():
        if "BEAMO_WIPE_VERSION=" in line:
            assert f"BEAMO_WIPE_VERSION={wrapper_version}" in line
    assert "--device" not in cfg
    assert "/dev/sda" not in cfg
    assert "/dev/nvme" not in cfg
    assert "-v /dev" not in cfg
    submit = (ROOT / "scripts" / "ci-cloud.sh").read_text(encoding="utf-8")
    assert "--project=" in submit
    assert "beamo-wipe" in submit
    assert "--publish-release" in submit
    assert (
        'SUBSTITUTIONS="${SUBSTITUTIONS:+$SUBSTITUTIONS,}_PUBLISH_RELEASE=false"'
        in submit
    )
    publisher = (ROOT / "scripts" / "publish_release_gcs.py").read_text(
        encoding="utf-8"
    )
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
    assert "PIP_CACHE_DIR" in hosted
    assert "desktop-launchers" in hosted
    assert "ci-desktop.sh" in hosted
    # Source live-image assertions always run; lb-config file checks skip
    # themselves when bootstrap/binary are absent.
    assert "not test_iso_build_uses_https_debian_mirrors" not in hosted
    assert "not test_live_config_xinit_cannot_hijack_kiosk" not in hosted
    assert "python3 -m pytest" in hosted
    assert (ROOT / "scripts" / "install-cloud-triggers.sh").is_file()


def test_github_actions_not_used():
    # No GitHub workflow may remain: billing is disabled there and Cloud
    # Build is the gate. Templates and agent instructions are not CI.
    workflows = ROOT / ".github" / "workflows"
    assert not workflows.exists(), f"{workflows} must not exist"


def test_desktop_bundle_rejects_stale_dirty_source(tmp_path):
    """A desktop manifest bound only to HEAD and binary hashes can hide stale Go code."""
    from scripts.build_desktop import desktop_source_digest, verify_desktop_bundle

    desktop = tmp_path / "desktop"
    web = desktop / "web"
    web.mkdir(parents=True)
    (desktop / "go.mod").write_text("module fake/desktop\n", encoding="utf-8")
    go_source = desktop / "main.go"
    go_source.write_text("package main\nfunc main() {}\n", encoding="utf-8")
    (web / "index.html").write_text("<main>old</main>\n", encoding="utf-8")
    output = tmp_path / "dist" / "desktop"
    output.mkdir(parents=True)
    names = ("Start Beamo Wipe.exe", "Start Beamo Wipe Linux")
    binary_hashes = {}
    for name in names:
        data = ("fake binary: " + name).encode()
        (output / name).write_bytes(data)
        binary_hashes[name] = hashlib.sha256(data).hexdigest()
    source_commit = "a" * 40
    manifest = {
        "source_commit": source_commit,
        "source_sha256": desktop_source_digest(tmp_path),
        "source_dirty": True,
        "version": "0.2.9",
        "go": "go1.26.8",
        "files": binary_hashes,
    }
    (output / "desktop-build.json").write_text(json.dumps(manifest), encoding="utf-8")
    verify_desktop_bundle(tmp_path, output, source_commit, "0.2.9", True)

    go_source.write_text(
        'package main\nfunc main() { println("changed") }\n', encoding="utf-8"
    )
    # The previous guard still sees the same HEAD and intact cached binaries.
    assert manifest["source_commit"] == source_commit
    assert all(
        hashlib.sha256((output / name).read_bytes()).hexdigest() == binary_hashes[name]
        for name in names
    )
    with pytest.raises(RuntimeError, match="source"):
        verify_desktop_bundle(tmp_path, output, source_commit, "0.2.9", True)


def test_shipped_usb_readme_uses_windows_manual_boot_route():
    build = (ROOT / "scripts" / "build-iso.sh").read_text(encoding="utf-8")
    assert "stage_live_assets.py" in build
    script = ast.parse(
        (ROOT / "scripts" / "stage_live_assets.py").read_text(encoding="utf-8")
    )
    readme = next(
        node.value.value
        for node in script.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "README"
            for target in node.targets
        )
    )
    assert "On Windows:" in readme
    assert "boot menu" in readme
    assert "permission prompt" not in readme


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


def test_cloud_submit_verifies_dirty_checkout_without_enabling_publication(tmp_path):
    """A precommit gate must upload the edited source and mark its provenance dirty."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    real_git = shutil.which("git")
    assert real_git is not None
    fake_git = fake_bin / "git"
    fake_git.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = status ] && [ "$2" = --porcelain ]; then\n'
        "  printf ' M src/beamo_wipe/wizard.py\\n'\n"
        "  exit 0\n"
        "fi\n"
        f'exec "{real_git}" "$@"\n',
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    fake_gcloud = fake_bin / "gcloud"
    fake_gcloud.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        'Path(os.environ["FAKE_GCLOUD_CALLS"]).write_text(json.dumps(sys.argv[1:]))\n',
        encoding="utf-8",
    )
    fake_gcloud.chmod(0o755)
    calls = tmp_path / "calls.json"
    env = os.environ.copy()
    env.pop("SUBSTITUTIONS", None)
    env.update(
        PATH=f"{fake_bin}{os.pathsep}{env['PATH']}", FAKE_GCLOUD_CALLS=str(calls)
    )
    script = ROOT / "scripts/ci-cloud.sh"
    verification = subprocess.run(
        ["bash", str(script)],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert verification.returncode == 0, verification.stderr
    args = json.loads(calls.read_text())
    assert "--substitutions=_PUBLISH_RELEASE=false,_ALLOW_DIRTY=1" in args

    calls.unlink()
    publication = subprocess.run(
        ["bash", str(script), "--publish-release"],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert publication.returncode == 2
    assert "uncommitted source" in publication.stderr.lower()
    assert not calls.exists()


def test_cloud_dirty_verification_is_explicit_and_not_a_release_override():
    config = (ROOT / "cloudbuild.yaml").read_text(encoding="utf-8")
    assert '_ALLOW_DIRTY: "0"' in config
    iso = config.split("  - id: iso-build\n", 1)[1].split("  - id: qemu-verify\n", 1)[0]
    qemu = config.split("  - id: qemu-verify\n", 1)[1].split(
        "  - id: publish-release\n", 1
    )[0]
    assert "ALLOW_DIRTY=${_ALLOW_DIRTY}" in iso
    assert "ALLOW_DIRTY=${_ALLOW_DIRTY}" in qemu
    assert (
        "ALLOW_DIRTY=${_ALLOW_DIRTY}"
        not in config.split("  - id: publish-release\n", 1)[1]
    )
    for name in ("build-usb-image.sh", "qemu-verify.sh"):
        assert (
            'allow_dirty=os.environ.get("ALLOW_DIRTY") == "1"'
            in (ROOT / "scripts" / name).read_text()
        )


def test_cloud_skip_iso_also_skips_dependent_qemu(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gcloud = fake_bin / "gcloud"
    fake_gcloud.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        'Path(os.environ["FAKE_GCLOUD_CALLS"]).write_text(json.dumps(sys.argv[1:]))\n',
        encoding="utf-8",
    )
    fake_gcloud.chmod(0o755)
    calls = tmp_path / "calls.json"
    env = os.environ.copy()
    env.pop("SUBSTITUTIONS", None)
    env.update(
        PATH=f"{fake_bin}{os.pathsep}{env['PATH']}", FAKE_GCLOUD_CALLS=str(calls)
    )
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/ci-cloud.sh"), "--skip-iso"],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    args = json.loads(calls.read_text())
    values = next(
        arg.split("=", 1)[1] for arg in args if arg.startswith("--substitutions=")
    )
    substitutions = dict(item.split("=", 1) for item in values.split(","))
    assert substitutions["_SKIP_ISO"] == "true"
    assert substitutions["_SKIP_QEMU"] == "true"
    assert substitutions["_PUBLISH_RELEASE"] == "false"


def test_cloud_triggers_cover_prs_and_main():
    text = (ROOT / "scripts" / "install-cloud-triggers.sh").read_text(encoding="utf-8")
    assert "beamo-wipe-pr-gate" in text
    assert "beamo-wipe-main-gate" in text
    assert "--pull-request-pattern" in text
    assert "--branch-pattern" in text
    # QEMU (TCG, slowest) runs on pushes to main; PRs run the rest.
    # Verification triggers never publish and never skip the ISO.
    assert "_SKIP_QEMU=true,_SKIP_ISO=false,_PUBLISH_RELEASE=false" in text
    assert "_SKIP_QEMU=false,_SKIP_ISO=false,_PUBLISH_RELEASE=false" in text


def test_cloud_trigger_installer_pins_identity_and_reconciles(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "calls.jsonl"
    fake_gcloud = fake_bin / "gcloud"
    fake_gcloud.write_text(
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
with Path(os.environ["FAKE_GCLOUD_CALLS"]).open("a", encoding="utf-8") as out:
    out.write(json.dumps(args) + "\\n")
if args[:3] == ["builds", "triggers", "describe"]:
    if os.environ["FAKE_TRIGGER_EXISTS"] == "true":
        raise SystemExit(0)
    print("NOT_FOUND: trigger does not exist", file=sys.stderr)
    raise SystemExit(1)
""",
        encoding="utf-8",
    )
    fake_gcloud.chmod(0o755)
    service_account = (
        "projects/beamo-wipe/serviceAccounts/"
        "368895881889-compute@developer.gserviceaccount.com"
    )

    for exists, verb in (("false", "create"), ("true", "update")):
        calls.write_text("", encoding="utf-8")
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
                "FAKE_GCLOUD_CALLS": str(calls),
                "FAKE_TRIGGER_EXISTS": exists,
                "BEAMO_WIPE_CLOUD_BUILD_SERVICE_ACCOUNT": service_account,
            }
        )
        completed = subprocess.run(  # noqa: S603
            ["bash", str(ROOT / "scripts" / "install-cloud-triggers.sh")],
            cwd=ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
        recorded = [json.loads(line) for line in calls.read_text().splitlines()]
        mutations = [
            args for args in recorded if args[:3] == ["builds", "triggers", verb]
        ]
        assert len(mutations) == (2 if verb == "create" else 4)
        structural = [
            args for args in mutations if "--build-config=cloudbuild.yaml" in args
        ]
        assert len(structural) == 2
        assert all(
            f"--service-account={service_account}" in args for args in structural
        )
        mutation_text = [" ".join(args) for args in mutations]
        assert any("beamo-wipe-pr-gate" in args for args in mutation_text)
        assert any("beamo-wipe-main-gate" in args for args in mutation_text)
        pr_calls = [
            args for args in mutations if "beamo-wipe-pr-gate" in " ".join(args)
        ]
        main_calls = [
            args for args in mutations if "beamo-wipe-main-gate" in " ".join(args)
        ]
        pr_subs = "_SKIP_QEMU=true,_SKIP_ISO=false,_PUBLISH_RELEASE=false"
        main_subs = "_SKIP_QEMU=false,_SKIP_ISO=false,_PUBLISH_RELEASE=false"
        substitution_flag = (
            f"--substitutions={pr_subs}"
            if verb == "create"
            else f"--update-substitutions={pr_subs}"
        )
        main_substitution_flag = (
            f"--substitutions={main_subs}"
            if verb == "create"
            else f"--update-substitutions={main_subs}"
        )
        assert any(substitution_flag in args for args in pr_calls)
        assert any(main_substitution_flag in args for args in main_calls)
        assert any(
            "--comment-control=COMMENTS_ENABLED_FOR_EXTERNAL_CONTRIBUTORS_ONLY" in args
            for args in pr_calls
        ), "External contributor CI still requires maintainer approval"
        if verb == "update":
            assert all("--clear-substitutions" in args for args in structural)


def test_cloud_trigger_installer_rejects_cross_project_identity():
    env = os.environ.copy()
    env.update(
        {
            "BEAMO_WIPE_GCP_PROJECT": "beamo-wipe",
            "BEAMO_WIPE_CLOUD_BUILD_SERVICE_ACCOUNT": (
                "projects/other/serviceAccounts/build@other.iam.gserviceaccount.com"
            ),
        }
    )
    completed = subprocess.run(  # noqa: S603
        ["bash", str(ROOT / "scripts" / "install-cloud-triggers.sh")],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert "must belong to project beamo-wipe" in completed.stderr


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
    assert ".ci-cache/" in rules
    staged = "packaging/live/config/includes.chroot/usr/lib/python3/dist-packages/beamo_wipe/"
    assert staged in rules


def test_cloud_upload_excludes_local_captures_and_env_files(tmp_path):
    gcloud = shutil.which("gcloud")
    if gcloud is None:
        pytest.skip("gcloud CLI is unavailable")
    upload = tmp_path / "upload"
    upload.mkdir()
    for name in (".gcloudignore", ".gitignore"):
        (upload / name).write_bytes((ROOT / name).read_bytes())
    paths = (
        ".git/HEAD",
        ".env",
        ".env.local",
        ".playwright-mcp/private-page.png",
        ".mypy_cache/cache.db",
        ".ruff_cache/cache.db",
        "packaging/live/config/includes.binary/START-HERE.html",
        "packaging/live/config/hooks/normal/0500-build-nwipe.hook.chroot",
    )
    for name in paths:
        path = upload / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fake fixture\n", encoding="utf-8")
    env = dict(os.environ)
    env["CLOUDSDK_CONFIG"] = str(tmp_path / "gcloud-config")
    env["CLOUDSDK_GCLOUDIGNORE_ENABLED"] = "true"
    proc = subprocess.run(
        [gcloud, "meta", "list-files-for-upload", str(upload)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    uploaded = set(proc.stdout.splitlines())
    assert ".git/HEAD" in uploaded
    assert "packaging/live/config/hooks/normal/0500-build-nwipe.hook.chroot" in uploaded
    assert (
        not (
            set(paths)
            - {
                ".git/HEAD",
                "packaging/live/config/hooks/normal/0500-build-nwipe.hook.chroot",
            }
        )
        & uploaded
    )


def test_hosted_python_tests_install_git_for_fail_closed_manifest():
    """The source metadata is useless unless the test image can read it."""
    hosted = (ROOT / "scripts" / "ci-hosted.sh").read_text(encoding="utf-8")
    test_deps = hosted.split("install_test_deps() {", 1)[1].split("\n}", 1)[0]
    assert "    git \\\n" in test_deps


def test_hosted_python_tests_install_cryptography_for_release_signing():
    """Signature tests run in the same worker; a missing lib must fail loudly."""
    hosted = (ROOT / "scripts" / "ci-hosted.sh").read_text(encoding="utf-8")
    test_deps = hosted.split("install_test_deps() {", 1)[1].split("\n}", 1)[0]
    assert "'cryptography==" in test_deps


def test_release_signing_cryptography_pins_are_patched_and_identical():
    """Keep developer, test, and publication installs above the advisory floor."""
    sources = {
        "pyproject.toml": 2,
        "scripts/ci-hosted.sh": 1,
        "cloudbuild.yaml": 1,
    }
    versions = []
    for path, expected_count in sources.items():
        content = (ROOT / path).read_text(encoding="utf-8")
        matches = re.findall(r"cryptography==(\d+\.\d+\.\d+)", content)
        assert len(matches) == expected_count, path
        versions.extend(matches)
    assert len(set(versions)) == 1
    assert tuple(map(int, versions[0].split("."))) >= (50, 0, 0)


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
