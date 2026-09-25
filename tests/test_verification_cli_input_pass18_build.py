"""Evidence CLI inputs must be bounded regular files, never device-like paths."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from beamo_wipe import verification_evidence as evidence


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO only")
def test_evidence_cli_rejects_fifo_without_waiting(tmp_path: Path) -> None:
    fifo = tmp_path / "input.fifo"
    os.mkfifo(fifo)
    command = [
        sys.executable,
        "-c",
        "from beamo_wipe.verification_evidence import _read_text_file; import sys; _read_text_file(sys.argv[1], what='junit xml')",
        str(fifo),
    ]
    env = dict(os.environ, PYTHONPATH=str(Path(evidence.__file__).parents[1]))
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=2)
    assert result.returncode != 0
    assert "regular" in result.stderr.lower() or "safely" in result.stderr.lower()


def test_evidence_cli_rejects_linked_and_oversized_inputs(tmp_path: Path) -> None:
    regular = tmp_path / "report.xml"
    regular.write_text("<testsuite/>")
    linked = tmp_path / "linked.xml"
    linked.symlink_to(regular)
    with pytest.raises(RuntimeError, match="safely|regular"):
        evidence._read_text_file(linked, what="junit xml")
    with regular.open("wb") as stream:
        stream.truncate(16 * 1024 * 1024 + 1)
    with pytest.raises(RuntimeError, match="limit|bounded"):
        evidence._read_text_file(regular, what="junit xml")


def test_evidence_cli_reads_small_regular_input(tmp_path: Path) -> None:
    path = tmp_path / "report.xml"
    path.write_text("<testsuite/>")
    assert evidence._read_text_file(path, what="junit xml") == "<testsuite/>"
