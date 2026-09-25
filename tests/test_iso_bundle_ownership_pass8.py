"""Exercise the ISO bundle transaction with disposable files only."""

from pathlib import Path
import os
import subprocess
import shutil


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "scripts/build-iso.sh"


def test_iso_bundle_inode_receipt_uses_portable_shell_and_rejects_links(tmp_path):
    source = BUILD.read_text()
    assert "-ef" not in source
    assert shutil.which("dash"), "dash is required to verify the hosted shell path"
    helper = (
        "same_regular_inode() {"
        + source.split("same_regular_inode() {", 1)[1].split("\ncleanup()", 1)[0]
    )
    original = tmp_path / "original.iso"
    hardlink = tmp_path / "hardlink.iso"
    replacement = tmp_path / "replacement.iso"
    symlink = tmp_path / "linked.iso"
    original.write_bytes(b"same bytes")
    os.link(original, hardlink)
    replacement.write_bytes(b"same bytes")
    symlink.symlink_to(original)
    script = tmp_path / "inode-check.sh"
    script.write_text(
        "#!/bin/dash\nset -eu\n"
        + helper
        + '\nsame_regular_inode "$1" "$2"\n'
        + 'if same_regular_inode "$1" "$3"; then exit 10; fi\n'
        + 'if same_regular_inode "$1" "$4"; then exit 11; fi\n'
        + 'if same_regular_inode "$1" "$5"; then exit 12; fi\n'
    )
    result = subprocess.run(
        [
            "dash",
            str(script),
            str(original),
            str(hardlink),
            str(replacement),
            str(symlink),
            str(tmp_path / "missing.iso"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _transaction_script(
    out: Path, setup: str, race: str, ending: str = "false", between: str = ":"
) -> str:
    source = BUILD.read_text()
    cleanup = source.split('DOCKER_INFO="$(mktemp ', 1)[1].split(
        "\ntrap cleanup EXIT", 1
    )[0]
    cleanup = 'DOCKER_INFO="$(mktemp ' + cleanup
    publication = source.split(
        'BACKUP_DIR="$(mktemp -d "$OUT_DIR/.bundle-backup.XXXXXX")"', 1
    )[1]
    publication = (
        'BACKUP_DIR="$(mktemp -d "$OUT_DIR/.bundle-backup.XXXXXX")"'
        + publication.split('\necho "Wrote ', 1)[0]
    )
    # These older synthetic rollback cases start with deliberately incomplete
    # bundles. The current builder verifies ownership separately; bypass that
    # one verification in this extracted transaction to keep testing rollback.
    publication = publication.replace('verify_prior_bundle "$BACKUP_DIR" "$OUT_DIR"\n', "")
    return f"""#!/bin/sh
set -eu
OUT_DIR={out}
VERSION=0.2.9
ISO_NAME=beamo-wipe-0.2.9-amd64.iso
{cleanup}
trap cleanup EXIT
mkdir -p "$OUT_DIR"
BUILD_OUT="$(mktemp -d "$OUT_DIR/.build-output.XXXXXX")"
printf 'new iso' > "$BUILD_OUT/$ISO_NAME"
{setup}
require_prior_bundle_paths
{between}
{publication}
{race}
{ending}
"""


def _run_failure(tmp_path: Path, setup: str, race: str) -> Path:
    out = tmp_path / "dist"
    script = tmp_path / "repro.sh"
    script.write_text(_transaction_script(out, setup, race))
    result = subprocess.run(["sh", str(script)], capture_output=True, text=True)
    assert result.returncode != 0, result.stdout + result.stderr
    return out


def test_failed_iso_build_preserves_foreign_replacement_and_prior_backup(tmp_path):
    out = _run_failure(
        tmp_path,
        'printf "prior iso" > "$OUT_DIR/$ISO_NAME"',
        'rm "$OUT_DIR/$ISO_NAME"; printf "foreign iso" > "$OUT_DIR/$ISO_NAME"',
    )
    name = "beamo-wipe-0.2.9-amd64.iso"
    assert (out / name).read_text() == "foreign iso"
    backups = list(out.glob(".bundle-backup.*/" + name))
    assert len(backups) == 1
    assert backups[0].read_text() == "prior iso"


def test_failed_iso_build_restores_relative_symlink_from_backup(tmp_path):
    out = _run_failure(
        tmp_path,
        'printf "prior iso" > "$OUT_DIR/prior.iso"; ln -s prior.iso "$OUT_DIR/$ISO_NAME"',
        ":",
    )
    link = out / "beamo-wipe-0.2.9-amd64.iso"
    assert link.is_symlink()
    assert os.readlink(link) == "prior.iso"
    assert link.read_text() == "prior iso"


def test_failed_iso_build_leaves_unknown_sidecar_and_entire_backup(tmp_path):
    out = _run_failure(
        tmp_path,
        'printf "prior iso" > "$OUT_DIR/$ISO_NAME"; '
        'printf "prior manifest" > "$OUT_DIR/beamo-wipe-0.2.9-amd64.manifest.json"',
        'printf "foreign manifest" > "$OUT_DIR/beamo-wipe-0.2.9-amd64.manifest.json"',
    )
    iso = "beamo-wipe-0.2.9-amd64.iso"
    manifest = "beamo-wipe-0.2.9-amd64.manifest.json"
    assert (out / manifest).read_text() == "foreign manifest"
    assert (out / iso).read_text() == "new iso"
    backups = list(out.glob(".bundle-backup.*"))
    assert len(backups) == 1
    assert (backups[0] / iso).read_text() == "prior iso"
    assert (backups[0] / manifest).read_text() == "prior manifest"


def test_success_refuses_iso_replaced_after_manifest_generation(tmp_path):
    out = tmp_path / "dist"
    source = BUILD.read_text()
    finalize = 'for _f in "dist/' + source.rsplit('for _f in "dist/', 1)[1]
    finalize = finalize.split('\nls -lh "dist/', 1)[0]
    script = tmp_path / "repro.sh"
    script.write_text(
        _transaction_script(
            out,
            'printf "prior iso" > "$OUT_DIR/$ISO_NAME"',
            "for file in beamo-wipe-0.2.9-amd64.manifest.json "
            "beamo-wipe-0.2.9-amd64.manifest.json.sha256 "
            "beamo-wipe-0.2.9-amd64.iso.sha256 SHA256SUMS; do "
            'touch "$OUT_DIR/$file"; done; '
            'rm "$OUT_DIR/$ISO_NAME"; printf "foreign iso" > "$OUT_DIR/$ISO_NAME"; '
            'cd "$OUT_DIR/.."',
            finalize,
        )
    )
    result = subprocess.run(["sh", str(script)], capture_output=True, text=True)
    assert result.returncode != 0, result.stdout + result.stderr
    assert (out / "beamo-wipe-0.2.9-amd64.iso").read_text() == "foreign iso"
    assert list(out.glob(".bundle-backup.*/beamo-wipe-0.2.9-amd64.iso"))


def test_iso_build_refuses_directory_at_prior_bundle_path(tmp_path):
    out = tmp_path / "dist"
    source = BUILD.read_text()
    finalize = 'for _f in "dist/' + source.rsplit('for _f in "dist/', 1)[1]
    finalize = finalize.split('\nls -lh "dist/', 1)[0]
    script = tmp_path / "repro.sh"
    script.write_text(
        _transaction_script(
            out,
            'mkdir "$OUT_DIR/$ISO_NAME"; printf "prior" > "$OUT_DIR/$ISO_NAME/keep.txt"',
            "for file in beamo-wipe-0.2.9-amd64.manifest.json "
            "beamo-wipe-0.2.9-amd64.manifest.json.sha256 "
            "beamo-wipe-0.2.9-amd64.iso.sha256 SHA256SUMS; do "
            'touch "$OUT_DIR/$file"; done; cd "$OUT_DIR/.."',
            finalize,
        )
    )
    result = subprocess.run(["sh", str(script)], capture_output=True, text=True)
    assert result.returncode != 0
    assert (out / "beamo-wipe-0.2.9-amd64.iso/keep.txt").read_text() == "prior"
    assert not list(out.glob(".bundle-backup.*"))


def test_iso_success_survives_backup_cleanup_failure(tmp_path):
    out = tmp_path / "dist"
    source = BUILD.read_text()
    finalize = 'for _f in "dist/' + source.rsplit('for _f in "dist/', 1)[1]
    finalize = finalize.split('\nls -lh "dist/', 1)[0]
    script = tmp_path / "repro.sh"
    script.write_text(
        _transaction_script(
            out,
            'printf "prior" > "$OUT_DIR/$ISO_NAME"',
            'rm "$BACKUP_DIR/$ISO_NAME"; mkdir "$BACKUP_DIR/$ISO_NAME"; '
            "for file in beamo-wipe-0.2.9-amd64.manifest.json "
            "beamo-wipe-0.2.9-amd64.manifest.json.sha256 "
            "beamo-wipe-0.2.9-amd64.iso.sha256 SHA256SUMS; do "
            'touch "$OUT_DIR/$file"; done; cd "$OUT_DIR/.."',
            finalize,
        )
    )
    result = subprocess.run(["sh", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (out / "beamo-wipe-0.2.9-amd64.iso").read_text() == "new iso"
    assert "Could not remove prior ISO bundle backup" in result.stderr


def test_iso_build_refuses_directory_swapped_after_preflight(tmp_path):
    out = tmp_path / "dist"
    source = BUILD.read_text()
    finalize = 'for _f in "dist/' + source.rsplit('for _f in "dist/', 1)[1]
    finalize = finalize.split('\nls -lh "dist/', 1)[0]
    script = tmp_path / "repro.sh"
    script.write_text(
        _transaction_script(
            out,
            'printf "prior" > "$OUT_DIR/$ISO_NAME"',
            "for file in beamo-wipe-0.2.9-amd64.manifest.json "
            "beamo-wipe-0.2.9-amd64.manifest.json.sha256 "
            "beamo-wipe-0.2.9-amd64.iso.sha256 SHA256SUMS; do "
            'touch "$OUT_DIR/$file"; done; cd "$OUT_DIR/.."',
            finalize,
            'rm "$OUT_DIR/$ISO_NAME"; mkdir "$OUT_DIR/$ISO_NAME"; '
            'printf "foreign" > "$OUT_DIR/$ISO_NAME/keep.txt"',
        )
    )
    result = subprocess.run(["sh", str(script)], capture_output=True, text=True)
    assert result.returncode != 0
    assert (out / "beamo-wipe-0.2.9-amd64.iso/keep.txt").read_text() == "foreign"
    assert "Unsafe prior ISO bundle path changed during backup" in result.stderr
