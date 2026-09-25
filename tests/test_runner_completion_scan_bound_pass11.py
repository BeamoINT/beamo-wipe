"""A growing fake completion log cannot extend one whole-log scan."""

import os

from beamo_wipe.nwipe_runner import NwipeRunner, _log_signature


def test_completion_scan_reads_no_more_than_initial_snapshot(tmp_path, monkeypatch):
    logfile = tmp_path / "fake-nwipe.log"
    logfile.write_bytes(b"sda | Erased |\n")
    initial_size = logfile.stat().st_size
    identity = _log_signature(logfile.stat())
    original_fdopen = os.fdopen
    observed = {"bytes": 0, "grew": False}

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

        def readline(self, limit=-1):
            if not observed["grew"]:
                observed["grew"] = True
                with logfile.open("ab") as writer:
                    writer.write(b"x" * 4096)
            line = self.stream.readline(limit)
            observed["bytes"] += len(line)
            return line

    monkeypatch.setattr(os, "fdopen", lambda *a, **k: GrowingFile(original_fdopen(*a, **k)))
    runner = NwipeRunner()

    projection = runner._scan_completion_log(str(logfile), "/dev/sda", identity)

    assert projection is None  # changed file is not completion proof
    assert observed["bytes"] <= initial_size
