"""Live-medium probes must request the exact mountpoint from findmnt."""

from types import SimpleNamespace

from beamo_wipe import discover


def test_findmnt_cannot_interpret_live_mount_path_as_a_bind_source(monkeypatch):
    calls = []

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr(discover.subprocess, "run", fake_run)
    discover._run_findmnt("/run/live/medium")

    assert calls == [[
        "/usr/bin/findmnt", "-n", "-o", "SOURCE",
        "--mountpoint", "/run/live/medium",
    ]]
