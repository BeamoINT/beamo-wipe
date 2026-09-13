"""Host-portable developer tooling tests; no application or disk imports."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


@pytest.fixture
def dev():
    return module("dev", ROOT / "dev.py")


def test_help_outside_checkout(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "dev.py"), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "desktop-build" in result.stdout


def test_fake_environment_discards_live_overrides(dev, monkeypatch):
    monkeypatch.setenv("BEAMO_WIPE_LIVE", "1")
    monkeypatch.setenv("BEAMO_WIPE_BOOT_DEVICE", "/dev/personal")
    monkeypatch.setenv("BEAMO_DESKTOP_NATIVE_INVENTORY_TEST", "1")
    env = dev.fake_environment(preview=True)
    assert env["BEAMO_WIPE_DRY_RUN"] == "1"
    assert env["BEAMO_WIPE_DEMO"] == "1"
    assert not any(
        k in env
        for k in (
            "BEAMO_WIPE_LIVE",
            "BEAMO_WIPE_BOOT_DEVICE",
            "BEAMO_DESKTOP_NATIVE_INVENTORY_TEST",
        )
    )


def test_venv_separates_hosts(dev):
    assert dev.venv_python("win32") != dev.venv_python("linux")
    assert dev.venv_python("darwin") != dev.venv_python("linux")
    assert dev.venv_python("win32").name == "python.exe"


def test_wsl_exact_path_and_arguments(dev, monkeypatch):
    calls = []
    monkeypatch.setattr(dev.shutil, "which", lambda _: "wsl.exe")
    monkeypatch.setattr(dev, "ROOT", Path("C:/A project"))

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "/mnt/c/A project\n")

    monkeypatch.setattr(dev.subprocess, "run", run)
    assert dev.wsl(["preview", "--web"]) == 0
    assert calls[-1] == [
        "wsl.exe",
        "--exec",
        "python3",
        "/mnt/c/A project/dev.py",
        "preview",
        "--web",
    ]


def test_missing_wsl_is_actionable(dev, monkeypatch, capsys):
    monkeypatch.setattr(dev.shutil, "which", lambda _: None)
    assert dev.wsl(["test"]) == 2
    assert "WSL2" in capsys.readouterr().err


def test_failed_wsl_conversion_never_launches(dev, monkeypatch):
    monkeypatch.setattr(dev.shutil, "which", lambda _: "wsl.exe")
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 7, "", "distribution missing")

    monkeypatch.setattr(dev.subprocess, "run", run)
    assert dev.wsl(["test"]) == 7
    assert len(calls) == 1


def test_live_environment_refused_before_command(dev, monkeypatch):
    monkeypatch.setattr(dev, "live_environment", lambda: True)
    monkeypatch.setattr(dev, "run", lambda *a, **k: pytest.fail("must not spawn"))
    assert dev.main(["preview", "--web"]) == 2
    assert dev.main(["test"]) == 2


def test_child_failure_preserved(dev, monkeypatch):
    monkeypatch.setattr(
        dev.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 17)
    )
    assert dev.run(["nonexistent fake command"]) == 17


def test_native_tests_do_not_enable_inventory(dev, monkeypatch):
    monkeypatch.setenv("BEAMO_DESKTOP_NATIVE_INVENTORY_TEST", "1")
    observed = []
    monkeypatch.setattr(dev, "live_environment", lambda: False)
    monkeypatch.setattr(dev, "run", lambda argv, **kw: observed.append((argv, kw)) or 0)
    assert dev.main(["desktop-test"]) == 0
    assert "BEAMO_DESKTOP_NATIVE_INVENTORY_TEST" not in observed[0][1]["env"]


def test_build_rejects_wrong_go_before_output(tmp_path, monkeypatch):
    builder = module("builder", ROOT / "scripts" / "build_desktop.py")
    monkeypatch.setattr(
        builder.subprocess,
        "check_output",
        lambda *a, **k: "go version go1.1 linux/amd64\n",
    )
    with pytest.raises(RuntimeError, match="1.26.8"):
        builder.build(tmp_path)
    assert not list(tmp_path.iterdir())


def test_build_contract_with_space_paths(tmp_path, monkeypatch):
    builder = module("builder", ROOT / "scripts" / "build_desktop.py")
    calls = []

    def output(argv, **kwargs):
        if argv[1:] == ["version"]:
            return "go version go1.26.8 linux/amd64\n"
        if argv[1:] == ["rev-parse", "HEAD"]:
            return "a" * 40 + "\n"
        return ""

    def check(argv, **kwargs):
        calls.append((argv, kwargs))
        Path(argv[argv.index("-o") + 1]).write_bytes(kwargs["env"]["GOOS"].encode())

    monkeypatch.setattr(builder.subprocess, "check_output", output)
    monkeypatch.setattr(builder.subprocess, "check_call", check)
    dest = tmp_path / "output with spaces"
    builder.build(dest)
    data = json.loads((dest / "desktop-build.json").read_text())
    assert set(data["files"]) == {"Start Beamo Wipe Linux", "Start Beamo Wipe.exe"}
    assert data["source_commit"] == "a" * 40
    assert [kw["env"]["GOOS"] for _, kw in calls] == ["linux", "windows"]
    assert all(kw["env"]["CGO_ENABLED"] == "0" for _, kw in calls)
    assert all("-trimpath" in cmd and "-buildvcs=false" in cmd for cmd, _ in calls)
    assert "-H=windowsgui" in calls[1][0][calls[1][0].index("-ldflags") + 1]


def test_failed_build_does_not_write_success_manifest(tmp_path, monkeypatch):
    builder = module("builder", ROOT / "scripts" / "build_desktop.py")
    monkeypatch.setattr(
        builder.subprocess,
        "check_output",
        lambda cmd, **k: "go version go1.26.8 darwin/arm64"
        if cmd[1:] == ["version"]
        else "a" * 40,
    )

    def fail(*a, **k):
        raise subprocess.CalledProcessError(3, "go")

    monkeypatch.setattr(builder.subprocess, "check_call", fail)
    with pytest.raises(subprocess.CalledProcessError):
        builder.build(tmp_path)
    assert not (tmp_path / "desktop-build.json").exists()


def test_test_environment_does_not_disguise_fake_as_demo(dev, monkeypatch):
    monkeypatch.setenv("BEAMO_WIPE_DEMO", "1")
    assert "BEAMO_WIPE_DEMO" not in dev.fake_environment()


def test_preview_keeps_argument_order(dev, monkeypatch):
    calls = []
    monkeypatch.setattr(dev, "live_environment", lambda: False)
    monkeypatch.setattr(dev.sys, "platform", "linux")
    monkeypatch.setattr(dev, "run", lambda argv, **kw: calls.append(argv) or 0)
    assert dev.main(["preview", "--scenario", "empty", "--console"]) == 0
    assert calls[0][-3:] == ["--scenario", "empty", "--console"]


@pytest.mark.parametrize(
    "host,native", [("linux", False), ("darwin", False), ("win32", True)]
)
def test_setup_bootstraps_pep517_tools_before_editable_install(
    dev, monkeypatch, tmp_path, host, native
):
    executable = tmp_path / "bin/python"
    executable.parent.mkdir()
    executable.touch()
    calls = []
    monkeypatch.setattr(dev, "live_environment", lambda: False)
    monkeypatch.setattr(dev, "venv_python", lambda: executable)
    monkeypatch.setattr(dev, "run", lambda cmd, **kw: calls.append(cmd) or 0)
    monkeypatch.setattr(dev.sys, "platform", host)
    assert dev.main(["setup"] + (["--native"] if native else [])) == 0
    assert calls[0][2:5] == ["pip", "install", "--upgrade"]
    assert "pip>=23" in calls[0]
    assert ("-e" in calls[1]) is (not native)
    assert "pytest==9.0.3" in calls[1]


def test_concurrent_build_cannot_mix_executables_and_hashes(tmp_path, monkeypatch):
    import hashlib
    import threading

    builder = module("builder", ROOT / "scripts" / "build_desktop.py")
    first_waiting = threading.Event()
    second_finished = threading.Event()
    errors = []

    def output(cmd, **kwargs):
        return "go version go1.26.8 linux/amd64" if cmd[1:] == ["version"] else "a" * 40

    def compile_fake(cmd, **kwargs):
        if (
            threading.current_thread().name == "first"
            and kwargs["env"]["GOOS"] == "windows"
        ):
            first_waiting.set()
            assert second_finished.wait(5)
        Path(cmd[cmd.index("-o") + 1]).write_bytes(
            threading.current_thread().name.encode()
        )

    def first():
        try:
            builder.build(tmp_path)
        except Exception as exc:
            errors.append(exc)

    monkeypatch.setattr(builder.subprocess, "check_output", output)
    monkeypatch.setattr(builder.subprocess, "check_call", compile_fake)
    thread = threading.Thread(target=first, name="first")
    thread.start()
    try:
        assert first_waiting.wait(5)
        try:
            builder.build(tmp_path)
        except RuntimeError as exc:
            assert "build" in str(exc).lower()
    finally:
        second_finished.set()
        thread.join(5)
    assert not thread.is_alive() and not errors
    manifest = json.loads((tmp_path / "desktop-build.json").read_text())
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() == digest


def test_git_windows_checkout_keeps_shell_line_endings(tmp_path):
    import shutil

    if not shutil.which("git"):
        pytest.skip("Git prerequisite is unavailable")
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    subprocess.check_call(["git", "init", "-q", str(fixture)])
    (fixture / ".gitattributes").write_bytes((ROOT / ".gitattributes").read_bytes())
    (fixture / "preview.sh").write_bytes(b"#!/bin/sh\nprintf hello\n")
    subprocess.check_call(
        ["git", "-c", "core.autocrlf=true", "add", ".gitattributes", "preview.sh"],
        cwd=fixture,
    )
    checkout = tmp_path / "windows checkout"
    subprocess.check_call(
        [
            "git",
            "-c",
            "core.autocrlf=true",
            "checkout-index",
            "-a",
            "--prefix=" + checkout.as_posix() + "/",
        ],
        cwd=fixture,
    )
    assert (checkout / "preview.sh").read_bytes() == b"#!/bin/sh\nprintf hello\n"


def test_windows_full_setup_delegates_to_wsl(dev, monkeypatch):
    calls = []
    monkeypatch.setattr(dev.sys, "platform", "win32")
    monkeypatch.setattr(dev, "live_environment", lambda: False)
    monkeypatch.setattr(dev, "wsl", lambda args: calls.append(args) or 0)
    monkeypatch.setattr(
        dev, "run", lambda *a, **k: pytest.fail("native setup must not run")
    )
    assert dev.main(["setup"]) == 0
    assert calls == [["setup"]]
