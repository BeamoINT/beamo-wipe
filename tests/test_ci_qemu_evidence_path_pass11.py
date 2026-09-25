"""The hosted QEMU collector must not follow a stale evidence PATH link."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_qemu_evidence_path_link_is_rejected_before_child_runs(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    builder = scripts / "build-usb-image.sh"
    builder.write_text("#!/bin/sh\nexit 0\n")
    builder.chmod(0o755)
    verifier = scripts / "qemu-verify.sh"
    verifier.write_text(
        "#!/bin/sh\n"
        'mkdir -p "$ROOT/source-evidence"\n'
        'printf "fixture evidence\\n" > "$ROOT/source-evidence/summary.txt"\n'
        'printf "%s\\n" "$ROOT/source-evidence" > "$ROOT/qemu-evidence/PATH"\n'
    )
    verifier.chmod(0o755)
    private = tmp_path / "outside.txt"
    private.write_text("original private file\n")
    evidence = tmp_path / "qemu-evidence"
    evidence.mkdir()
    (evidence / "PATH").symlink_to(private)

    source = (ROOT / "scripts/ci-hosted.sh").read_text()
    function = "run_qemu() {" + source.split("run_qemu() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"
    harness = (
        "set -euo pipefail\n"
        'ROOT="$1"; export ROOT\n'
        'cd "$ROOT"\n'
        "log() { :; }\n"
        + function
        + "run_qemu\n"
    )
    result = subprocess.run(
        ["bash", "-c", harness, "test", str(tmp_path)], capture_output=True, text=True
    )
    assert result.returncode != 0
    assert private.read_text() == "original private file\n"
