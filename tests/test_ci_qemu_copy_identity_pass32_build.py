"""The hosted QEMU handoff must copy the final named evidence bytes."""

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def _copy_program() -> str:
    script = (ROOT / "scripts/ci-hosted.sh").read_text(encoding="utf-8")
    marker = '  python3 - "$evidence_source" "$ROOT/qemu-evidence" <<\'PY\'\n'
    return script.split(marker, 1)[1].split("\nPY\n", 1)[0]


def _run_copy(
    tmp_path: Path, injection: str = "", *, extra_source: bool = False
) -> subprocess.CompletedProcess[str]:
    source = tmp_path / "source"
    output = tmp_path / "output"
    source.mkdir()
    output.mkdir()
    (source / "run.txt").write_bytes(b"A" * 1024)
    if extra_source:
        (source / "a.txt").write_bytes(b"A" * 1024)
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"B" * 1024)
    program = _copy_program()
    if injection:
        line = "                    shutil.copyfileobj(source_file, output_file)"
        assert line in program
        program = program.replace(line, line + "\n" + injection)
    result = subprocess.run(
        [sys.executable, "-c", program, str(source), str(output), str(replacement)],
        capture_output=True,
        text=True,
        check=False,
    )
    if not injection:
        assert result.returncode == 0, result.stderr
        assert (output / "run.txt").read_bytes() == b"A" * 1024
    return result


def test_qemu_copy_rejects_replaced_source_name(tmp_path: Path) -> None:
    result = _run_copy(
        tmp_path,
        "                    os.replace(sys.argv[3], os.path.join(sys.argv[1], name))",
    )
    assert result.returncode != 0
    assert "changed during copy" in result.stderr


def test_qemu_copy_rejects_replaced_destination_name(tmp_path: Path) -> None:
    result = _run_copy(
        tmp_path,
        "                    os.replace(sys.argv[3], os.path.join(sys.argv[2], name))",
    )
    assert result.returncode != 0
    assert "changed during copy" in result.stderr


def test_qemu_copy_rejects_same_size_rewrite_with_restored_mtime(
    tmp_path: Path,
) -> None:
    result = _run_copy(
        tmp_path,
        "                    import time\n"
        "                    time.sleep(0.01)\n"
        "                    source_path = os.path.join(sys.argv[1], name)\n"
        "                    with open(source_path, 'wb') as changed:\n"
        "                        changed.write(b'B' * 1024)\n"
        "                    os.utime(source_path, ns=(before.st_atime_ns, before.st_mtime_ns))",
    )
    assert result.returncode != 0
    assert "changed during copy" in result.stderr


def test_qemu_copy_rechecks_earlier_file_after_later_copy(tmp_path: Path) -> None:
    result = _run_copy(
        tmp_path,
        "                    if name == 'run.txt':\n"
        "                        with open(os.path.join(sys.argv[1], 'a.txt'), 'wb') as changed:\n"
        "                            changed.write(b'B' * 1024)",
        extra_source=True,
    )
    assert result.returncode != 0
    assert "changed during copy" in result.stderr
