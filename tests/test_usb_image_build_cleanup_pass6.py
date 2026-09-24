"""Exercise failed USB-image readback with only disposable regular files."""

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "failure",
    [
        "readback",
        "publication",
        "replacement",
        "directory",
        "late_image_replacement",
        "late_sha_replacement",
        "none",
    ],
)
def test_image_output_published_only_after_readback(tmp_path, failure):
    source = (ROOT / "scripts/build-usb-image.sh").read_text()
    # This local fixture runs the production script on macOS too, using a tiny
    # regular-file image and fake FAT tools. It never opens a device or mount.
    platform_check = (
        '[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 && ! -d /Users/HP ]] || {\n'
        "  echo 'USB image builds require an isolated amd64 Linux worker.' >&2; exit 2;\n"
        "}\n"
    )
    assert platform_check in source
    source = source.replace(platform_check, "")
    size_line = "stream.truncate(2*1024**3-1024**2)"
    assert size_line in source
    source = source.replace(size_line, "stream.truncate(1024**2)")
    mbr_line = "code=pathlib.Path('/usr/lib/syslinux/mbr/mbr.bin').read_bytes()"
    assert mbr_line in source
    source = source.replace(mbr_line, "code=b''")

    scripts = tmp_path / "scripts"
    scripts.mkdir()
    builder = scripts / "build-usb-image.sh"
    builder.write_text(source)
    package = tmp_path / "src/beamo_wipe"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("__version__ = '0.2.9'\n")
    (package / "release_manifest.py").write_text(
        "def verify_build_manifest(*args, **kwargs):\n    return None\n"
    )
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "beamo-wipe-0.2.9-amd64.iso").write_bytes(b"fake ISO fixture")
    payloads = {
        "Start Beamo Wipe.exe": b"MZ-windows-fixture",
        "Start Beamo Wipe Linux": b"ELF-linux-fixture",
    }
    (tmp_path / "desktop-build.json").write_text(
        json.dumps(
            {
                "files": {
                    name: hashlib.sha256(data).hexdigest()
                    for name, data in payloads.items()
                }
            }
        )
    )
    for name, data in payloads.items():
        (tmp_path / name).write_bytes(data)
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    xorriso = fake_bin / "xorriso"
    xorriso.write_text(
        "#!/bin/sh\n"
        "for tree do :; done\n"
        'mkdir -p "$tree/EFI/boot" "$tree/isolinux"\n'
        'printf MZ > "$tree/EFI/boot/bootx64.efi"\n'
        'printf MZ > "$tree/EFI/boot/grubx64.efi"\n'
        'printf config > "$tree/isolinux/isolinux.cfg"\n'
        'cp "$BEAMO_FIXTURE_DIR/desktop-build.json" "$tree/"\n'
        'cp "$BEAMO_FIXTURE_DIR/Start Beamo Wipe.exe" "$tree/"\n'
        'cp "$BEAMO_FIXTURE_DIR/Start Beamo Wipe Linux" "$tree/"\n'
    )
    xorriso.chmod(0o755)
    for name in ("mkfs.vfat", "mcopy", "syslinux"):
        tool = fake_bin / name
        tool.write_text("#!/bin/sh\nexit 0\n")
        tool.chmod(0o755)
    mtype = fake_bin / "mtype"
    if failure == "readback":
        mtype.write_text("#!/bin/sh\nexit 9\n")
    else:
        mtype.write_text(
            "#!/bin/sh\n"
            "for file do :; done\n"
            'case "$file" in\n'
            '  "::/desktop-build.json") cat "$BEAMO_FIXTURE_DIR/desktop-build.json" ;;\n'
            '  "::/Start Beamo Wipe.exe") cat "$BEAMO_FIXTURE_DIR/Start Beamo Wipe.exe" ;;\n'
            '  "::/Start Beamo Wipe Linux") cat "$BEAMO_FIXTURE_DIR/Start Beamo Wipe Linux" ;;\n'
            "  *) exit 9 ;;\n"
            "esac\n"
        )
    mtype.chmod(0o755)
    if failure in {
        "publication",
        "replacement",
        "directory",
        "late_image_replacement",
        "late_sha_replacement",
    }:
        link = fake_bin / "python3"
        script = (
            "#!/bin/sh\n"
            'if [ "$1" != -c ] || '
            "[ \"$2\" != 'import os,sys; os.link(sys.argv[1],sys.argv[2],follow_symlinks=False)' ]; then\n"
            f'  exec {shlex.quote(sys.executable)} "$@"\n'
            "fi\n"
            'count_file="$BEAMO_FIXTURE_DIR/ln-count"\n'
            'count=$(cat "$count_file" 2>/dev/null || printf 0)\n'
            "count=$((count + 1))\n"
            'printf "%s" "$count" > "$count_file"\n'
        )
        if failure == "directory":
            script += (
                'if [ "$count" -eq 1 ]; then\n'
                "  for output do :; done\n"
                '  mkdir "$output"\n'
                "fi\n"
            )
        elif failure in {
            "replacement",
            "late_image_replacement",
            "late_sha_replacement",
        }:
            script += (
                'if [ "$count" -eq 1 ]; then\n'
                "  for output do :; done\n"
                '  printf "%s" "$output" > "$BEAMO_FIXTURE_DIR/published-path"\n'
                "fi\n"
            )
            if failure == "late_sha_replacement":
                script += (
                    'if [ "$count" -eq 2 ]; then\n'
                    "  for output do :; done\n"
                    '  printf "%s" "$output" > "$BEAMO_FIXTURE_DIR/published-path"\n'
                    "fi\n"
                )
            replace_on = 2 if failure == "replacement" else 3
            script += (
                f'if [ "$count" -eq {replace_on} ]; then\n'
                '  output=$(cat "$BEAMO_FIXTURE_DIR/published-path")\n'
                '  rm -f -- "$output"\n'
                '  printf "foreign output" > "$output"\n'
            )
            if failure == "replacement":
                script += "  exit 9\n"
            script += "fi\n"
        else:
            script += 'if [ "$count" -eq 2 ]; then exit 9; fi\n'
        link.write_text(script + f'exec {shlex.quote(sys.executable)} "$@"\n')
        link.chmod(0o755)
    result = subprocess.run(
        ["bash", str(builder)],
        env={
            **os.environ,
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "BEAMO_FIXTURE_DIR": str(tmp_path),
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    image = dist / "beamo-wipe-0.2.9-amd64.img"
    if failure in {"readback", "publication"}:
        assert result.returncode != 0
        assert not image.exists()
        assert not (dist / f"{image.name}.sha256").exists()
        assert not (dist / f"{image.name}.json").exists()
    elif failure == "replacement":
        assert result.returncode != 0
        assert image.read_bytes() == b"foreign output"
        assert not (dist / f"{image.name}.sha256").exists()
        assert not (dist / f"{image.name}.json").exists()
    elif failure in {"late_image_replacement", "late_sha_replacement"}:
        assert result.returncode != 0
        foreign = (
            image
            if failure == "late_image_replacement"
            else dist / f"{image.name}.sha256"
        )
        assert foreign.read_bytes() == b"foreign output"
        assert not (dist / f"{image.name}.json").exists()
        if failure == "late_sha_replacement":
            assert not image.exists()
        else:
            assert not (dist / f"{image.name}.sha256").exists()
    elif failure == "directory":
        assert result.returncode != 0
        assert image.is_dir()
        assert list(image.iterdir()) == []
        assert not (dist / f"{image.name}.sha256").exists()
        assert not (dist / f"{image.name}.json").exists()
    else:
        assert result.returncode == 0, result.stderr
        assert image.is_file()
        assert (dist / f"{image.name}.sha256").is_file()
        assert (dist / f"{image.name}.json").is_file()
    assert not list(dist.glob(".usb-build.*"))
