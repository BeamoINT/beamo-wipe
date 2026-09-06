#!/usr/bin/env bash
# Build a Windows-readable USB image from the verified ISO using regular files.
# No physical device arguments, mounts, or loop devices are accepted.
set -euo pipefail
ROOT="$(CDPATH='' cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 && ! -d /Users/HP ]] || {
  echo 'USB image builds require an isolated amd64 Linux worker.' >&2; exit 2;
}
[[ $# == 0 ]] || { echo 'This builder accepts no device or path arguments.' >&2; exit 2; }
VERSION="$(PYTHONPATH="$ROOT/src" python3 -c 'import beamo_wipe; print(beamo_wipe.__version__)')"
ISO="$ROOT/dist/beamo-wipe-${VERSION}-amd64.iso"
OUT="$ROOT/dist/beamo-wipe-${VERSION}-amd64.img"
[[ -f "$ISO" && ! -L "$ISO" && ! -e "$OUT" && ! -L "$OUT" ]] || {
  echo 'A regular ISO and an unused image output path are required.' >&2; exit 2;
}
PYTHONPATH="$ROOT/src" python3 -c 'import pathlib,sys; from beamo_wipe.release_manifest import verify_manifest; verify_manifest(pathlib.Path(sys.argv[1]))' "$ROOT/dist/beamo-wipe-${VERSION}-amd64.manifest.json"
TMP_IMAGE="$(mktemp -d /tmp/beamo-wipe-usb.XXXXXX)"
trap 'rm -rf -- "$TMP_IMAGE"' EXIT
TREE="$TMP_IMAGE/tree"
FAT="$TMP_IMAGE/volume.fat"
xorriso -osirrox on -indev "$ISO" -extract / "$TREE" >"$TMP_IMAGE/extract.log" 2>&1
[[ -f "$TREE/EFI/boot/bootx64.efi" && -f "$TREE/EFI/boot/grubx64.efi" && -f "$TREE/isolinux/isolinux.cfg" ]] || {
  echo 'Required signed EFI and BIOS boot assets are missing.' >&2; exit 2;
}
cp "$TREE/isolinux/isolinux.cfg" "$TREE/isolinux/syslinux.cfg"
# The live image is below FAT32's individual-file limit. Refuse future growth.
python3 - "$TREE" "$FAT" <<'PY'
import pathlib,sys
root=pathlib.Path(sys.argv[1])
files=[p for p in root.rglob('*') if p.is_file()]
if any(p.stat().st_size >= 2**32 for p in files) or sum(p.stat().st_size for p in files)>1800*1024**2:
    raise SystemExit('Live payload exceeds the bounded 2 GiB USB image capacity')
with open(sys.argv[2],'xb') as stream: stream.truncate(2*1024**3-1024**2)
PY
mkfs.vfat -F 32 -n BEAMO_WIPE -h 2048 "$FAT"
# Include hidden ISO metadata too; no shell glob may omit .disk.
for entry in "$TREE"/* "$TREE"/.[!.]*; do
  [[ -e "$entry" ]] || continue
  mcopy -s -i "$FAT" "$entry" ::/
done
# Syslinux stores this path in its boot files. A relative "isolinux" installs
# successfully but boots to "No configuration file found" on BIOS; the
# filesystem-root path is required (verified with the same FAT image in QEMU).
syslinux --install --directory /isolinux "$FAT"
python3 - "$FAT" "$OUT" "$ISO" <<'PY'
import hashlib,json,pathlib,secrets,shutil,struct,sys
fat,out,iso=map(pathlib.Path,sys.argv[1:])
mbr=bytearray(512)
code=pathlib.Path('/usr/lib/syslinux/mbr/mbr.bin').read_bytes()
if len(code)>440: raise SystemExit('Unexpected BIOS MBR code size')
mbr[:len(code)]=code
mbr[440:444]=struct.pack('<I',secrets.randbelow(2**32-1)+1)
mbr[446:462]=struct.pack('<B3sB3sII',0x80,b'\xfe\xff\xff',0x0c,b'\xfe\xff\xff',2048,fat.stat().st_size//512)
mbr[510:512]=b'\x55\xaa'
with out.open('xb') as dest,fat.open('rb') as source:
    dest.write(mbr);dest.seek(1024**2);shutil.copyfileobj(source,dest,1024**2)
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(1024**2): h.update(chunk)
    return h.hexdigest()
sha=digest(out)
out.with_suffix('.img.sha256').write_text(f'{sha}  {out.name}\n')
out.with_suffix('.img.json').write_text(json.dumps({'schema_version':1,'image':out.name,'sha256':sha,'iso':iso.name,'iso_sha256':digest(iso),'layout':'MBR, one active FAT32 partition at sector 2048','size':out.stat().st_size},sort_keys=True,indent=2)+'\n')
PY
# Read the packaged launcher files back through FAT32, not the extraction tree.
python3 - "$TREE" "$FAT" <<'PY'
import hashlib,json,pathlib,subprocess,sys
root=pathlib.Path(sys.argv[1]);manifest=json.loads((root/'desktop-build.json').read_text())
for name,expected in manifest['files'].items():
    actual=subprocess.check_output(['mtype','-i',sys.argv[2],'::/'+name])
    if hashlib.sha256(actual).hexdigest()!=expected: raise SystemExit('USB launcher readback mismatch')
PY
printf 'Built Windows-readable USB image: %s\n' "$OUT"
