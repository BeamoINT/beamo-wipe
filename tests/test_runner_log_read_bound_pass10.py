"""A growing fake log cannot make one runner poll read without a bound."""

import os

from beamo_wipe.nwipe_runner import NwipeRunner


def test_read_log_tail_stays_bounded_when_log_grows_during_read(tmp_path, monkeypatch):
    logfile = tmp_path / "fake-nwipe.log"
    logfile.write_bytes(b"ready\n")
    original_fdopen = os.fdopen

    class GrowingFile:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def fileno(self):
            return self.stream.fileno()

        def seek(self, *args):
            return self.stream.seek(*args)

        def tell(self):
            return self.stream.tell()

        def read(self, size=-1):
            with logfile.open("ab") as writer:
                writer.write(b"x" * 4096)
            return self.stream.read(size)

    monkeypatch.setattr(os, "fdopen", lambda *a, **k: GrowingFile(original_fdopen(*a, **k)))
    runner = NwipeRunner()

    tail = runner._read_log_tail(str(logfile), 32)

    assert len(tail.encode("utf-8")) <= 32
