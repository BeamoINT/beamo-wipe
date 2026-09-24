"""A running pinned engine remains running after its file is unlinked."""

from beamo_wipe import nwipe_runner as runner


def test_deleted_pinned_executable_is_still_running(monkeypatch):
    pinned = runner.NWIPE_PINNED_PATH
    monkeypatch.setattr(runner.os.path, "realpath", lambda path: str(path))
    monkeypatch.setattr(runner.os, "listdir", lambda path: ["4242"])
    monkeypatch.setattr(runner.os, "readlink", lambda path: f"{pinned} (deleted)")
    assert runner.pinned_nwipe_already_running()
