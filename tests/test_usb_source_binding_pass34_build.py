"""Exercise USB-image source binding with disposable files and fake FAT tools."""

import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "damage",
    [
        "iso_changed_after_extract",
        "linked_extract_file",
        "linked_isolinux_dir",
        "linked_syslinux_destination",
        "transient_iso_edit",
    ],
)
def test_usb_builder_rejects_changed_iso_or_linked_extraction(tmp_path, damage):
    source = (ROOT / "scripts/build-usb-image.sh").read_text()
    platform_check = (
        '[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 && ! -d /Users/HP ]] || {\n'
        "  echo 'USB image builds require an isolated amd64 Linux worker.' >&2; exit 2;\n"
        "}\n"
    )
    assert platform_check in source
    source = source.replace(platform_check, "")
    source = source.replace(
        "stream.truncate(2*1024**3-1024**2)", "stream.truncate(1024**2)"
    )
    source = source.replace(
        "code=pathlib.Path('/usr/lib/syslinux/mbr/mbr.bin').read_bytes()", "code=b''"
    )
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    builder = scripts / "build-usb-image.sh"
    builder.write_text(source)
    package = tmp_path / "src/beamo_wipe"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("__version__ = '0.2.9'\n")
    (package / "release_manifest.py").write_text(
        "import hashlib, pathlib\n"
        "def verify_build_manifest(path, allow_dirty=False):\n"
        "    iso = path.with_name('beamo-wipe-0.2.9-amd64.iso')\n"
        "    expected = path.with_name('expected-sha').read_text()\n"
        "    if hashlib.sha256(iso.read_bytes()).hexdigest() != expected:\n"
        "        raise RuntimeError('ISO checksum mismatch')\n"
    )
    dist = tmp_path / "dist"
    dist.mkdir()
    iso = dist / "beamo-wipe-0.2.9-amd64.iso"
    iso.write_bytes(b"verified fixture ISO")
    (dist / "expected-sha").write_text(hashlib.sha256(iso.read_bytes()).hexdigest())
    (dist / "beamo-wipe-0.2.9-amd64.manifest.json").write_text("fixture")
    payloads = {
        "Start Beamo Wipe.exe": b"MZ Windows fixture",
        "Start Beamo Wipe Linux": b"ELF Linux fixture",
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
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    def tool(name, body):
        path = fake_bin / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)

    tool(
        "xorriso",
        'previous=""\n'
        "for arg do\n"
        '  if [ "$previous" = -indev ]; then indev="$arg"; fi\n'
        '  previous="$arg"\n'
        '  tree="$arg"\n'
        "done\n"
        'mkdir -p "$tree/EFI/boot" "$tree/isolinux"\n'
        'printf "%s" "$tree" > "$BEAMO_FIXTURE_DIR/tree-path"\n'
        'printf MZ > "$tree/EFI/boot/bootx64.efi"\n'
        + (
            'printf temporarily-mutated > "$BEAMO_FIXTURE_DIR/dist/beamo-wipe-0.2.9-amd64.iso"\n'
            'cat "$indev" >> "$tree/EFI/boot/bootx64.efi"\n'
            'cp "$tree/EFI/boot/bootx64.efi" "$BEAMO_FIXTURE_DIR/observed-loader"\n'
            'printf "verified fixture ISO" > "$BEAMO_FIXTURE_DIR/dist/beamo-wipe-0.2.9-amd64.iso"\n'
            if damage == "transient_iso_edit"
            else ""
        )
        + 'printf MZ > "$tree/EFI/boot/grubx64.efi"\n'
        'printf config > "$tree/isolinux/isolinux.cfg"\n'
        'printf iso-module > "$tree/isolinux/ldlinux.c32"\n'
        'cp "$BEAMO_FIXTURE_DIR/desktop-build.json" "$tree/"\n'
        'cp "$BEAMO_FIXTURE_DIR/Start Beamo Wipe.exe" "$tree/"\n'
        'cp "$BEAMO_FIXTURE_DIR/Start Beamo Wipe Linux" "$tree/"\n'
        + (
            'printf mutated > "$BEAMO_FIXTURE_DIR/dist/beamo-wipe-0.2.9-amd64.iso"\n'
            if damage == "iso_changed_after_extract"
            else (
                'ln -s "$BEAMO_FIXTURE_DIR/outside-secret" "$tree/extra-file"\n'
                if damage == "linked_extract_file"
                else (
                    'rm -rf "$tree/isolinux"\n'
                    'ln -s "$BEAMO_FIXTURE_DIR/outside-isolinux" "$tree/isolinux"\n'
                    if damage == "linked_isolinux_dir"
                    else (
                        'ln -s "$BEAMO_FIXTURE_DIR/outside-syslinux" "$tree/isolinux/syslinux.cfg"\n'
                        if damage == "linked_syslinux_destination"
                        else ""
                    )
                )
            )
        ),
    )
    (tmp_path / "outside-secret").write_bytes(b"outside fixture bytes")
    outside_dir = tmp_path / "outside-isolinux"
    outside_dir.mkdir()
    (outside_dir / "isolinux.cfg").write_bytes(b"outside config source")
    outside_destination = tmp_path / "outside-syslinux"
    outside_destination.write_bytes(b"preserve outside destination")
    (tmp_path / "installed-ldlinux.c32").write_bytes(b"installed module" * 128)
    for name in ("mkfs.vfat", "mcopy", "mmd"):
        tool(name, "exit 0\n")
    tool(
        "syslinux",
        'dd if=/dev/zero of="$BEAMO_FIXTURE_DIR/ldlinux.sys" bs=1024 count=1 2>/dev/null\n',
    )
    tool(
        "mtype",
        "for file do :; done\n"
        'case "$file" in\n'
        '  ::/isolinux/ldlinux.sys) exec cat "$BEAMO_FIXTURE_DIR/ldlinux.sys" ;;\n'
        '  ::/isolinux/ldlinux.c32) exec cat "$BEAMO_FIXTURE_DIR/installed-ldlinux.c32" ;;\n'
        "  ::/*) name=${file#::/} ;;\n"
        "  *) exit 9 ;;\n"
        "esac\n"
        'tree=$(cat "$BEAMO_FIXTURE_DIR/tree-path")\n'
        'exec cat "$tree/$name"\n',
    )
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
    if damage == "transient_iso_edit":
        assert result.returncode == 0, result.stdout + result.stderr
        assert (tmp_path / "observed-loader").read_bytes() == b"MZverified fixture ISO"
        assert image.exists()
    else:
        assert result.returncode != 0, result.stdout + result.stderr
        assert not image.exists()
        assert not (dist / (image.name + ".json")).exists()
        assert not (dist / (image.name + ".sha256")).exists()
        if damage == "linked_isolinux_dir":
            assert not (outside_dir / "syslinux.cfg").exists()
        if damage == "linked_syslinux_destination":
            assert outside_destination.read_bytes() == b"preserve outside destination"
