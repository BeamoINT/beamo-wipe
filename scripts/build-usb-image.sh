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
[[ -d "$ROOT/dist" && ! -L "$ROOT/dist" ]] || {
  echo 'A regular output directory is required.' >&2; exit 2;
}
ISO="$ROOT/dist/beamo-wipe-${VERSION}-amd64.iso"
OUT="$ROOT/dist/beamo-wipe-${VERSION}-amd64.img"
[[ -f "$ISO" && ! -L "$ISO" ]] || {
  echo 'A regular ISO is required.' >&2; exit 2;
}
# An earlier receipt must never survive as apparent success for a failed retry.
# Refuse existing outputs, including dangling links, without replacing them.
for output in "$OUT" "$OUT.sha256" "$OUT.json"; do
  [[ ! -e "$output" && ! -L "$output" ]] || {
    echo 'Unused image and sidecar output paths are required.' >&2; exit 2;
  }
done
PYTHONPATH="$ROOT/src" python3 -c 'import os,pathlib,sys; from beamo_wipe.release_manifest import verify_build_manifest; verify_build_manifest(pathlib.Path(sys.argv[1]), allow_dirty=os.environ.get("ALLOW_DIRTY") == "1")' "$ROOT/dist/beamo-wipe-${VERSION}-amd64.manifest.json"
TMP_IMAGE="$(mktemp -d /tmp/beamo-wipe-usb.XXXXXX)"
# Keep the final image on the output filesystem so publication can use
# no-overwrite hard links. A failed assembly or readback must leave no final
# image that would block a safe retry.
OUTPUT_STAGE=""
published_image=0
published_sha=0
published_json=0
remove_owned_link() {
  local staged="$1" published="$2"
  # A concurrent writer may replace a published path before a later link
  # fails. The staged inode is our ownership receipt; never unlink a changed
  # path or a symlink solely because this process published the old name.
  if [[ -f "$staged" && ! -L "$staged" && ! -L "$published" && "$staged" -ef "$published" ]]; then
    rm -f -- "$published"
  fi
}
cleanup() {
  rc=$?
  if [[ "$rc" -ne 0 ]]; then
    [[ "$published_json" -eq 0 ]] || remove_owned_link "$STAGED_OUT.json" "$OUT.json"
    [[ "$published_sha" -eq 0 ]] || remove_owned_link "$STAGED_OUT.sha256" "$OUT.sha256"
    [[ "$published_image" -eq 0 ]] || remove_owned_link "$STAGED_OUT" "$OUT"
  fi
  rm -rf -- "$TMP_IMAGE"
  [[ -z "$OUTPUT_STAGE" ]] || rm -rf -- "$OUTPUT_STAGE"
}
trap cleanup EXIT
OUTPUT_STAGE="$(mktemp -d "$ROOT/dist/.usb-build.XXXXXX")"
STAGED_OUT="$OUTPUT_STAGE/$(basename "$OUT")"
TREE="$TMP_IMAGE/tree"
FAT="$TMP_IMAGE/volume.fat"
REFERENCE_FAT="$TMP_IMAGE/syslinux-reference.fat"
# Extract a private byte-for-byte ISO snapshot. A source that changes only
# during xorriso and is restored before the final manifest check must not be
# allowed to contribute different boot files to an otherwise verified image.
SOURCE_ISO="$TMP_IMAGE/source.iso"
SNAPSHOT_SHA="$(python3 - "$ISO" "$SOURCE_ISO" <<'PYSNAPSHOT'
import hashlib,os,stat,sys
source,destination=sys.argv[1:]
fd=os.open(source,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
with os.fdopen(fd,'rb') as original:
    info=os.fstat(original.fileno())
    if not stat.S_ISREG(info.st_mode) or info.st_size<=0:
        raise SystemExit('ISO source is not a regular file')
    digest=hashlib.sha256()
    with open(destination,'xb') as snapshot:
        for chunk in iter(lambda: original.read(1024**2),b''):
            snapshot.write(chunk)
            digest.update(chunk)
    if os.stat(destination).st_size!=info.st_size:
        raise SystemExit('ISO changed while making the extraction snapshot')
    print(digest.hexdigest())
PYSNAPSHOT
)"
xorriso -osirrox on -indev "$SOURCE_ISO" -extract / "$TREE" >"$TMP_IMAGE/extract.log" 2>&1
[[ -f "$TREE/EFI/boot/bootx64.efi" && -f "$TREE/EFI/boot/grubx64.efi" && -f "$TREE/isolinux/isolinux.cfg" ]] || {
  echo 'Required signed EFI and BIOS boot assets are missing.' >&2; exit 2;
}
# Validate before creating syslinux.cfg: a linked isolinux ancestor or output
# can otherwise make a normal cp write outside the extracted tree. Keep the
# source and destination on the checked directory descriptor during the copy.
python3 - "$TREE" "$FAT" <<'PY'
import os,pathlib,shutil,stat,sys
root=pathlib.Path(sys.argv[1])
if not stat.S_ISDIR(root.lstat().st_mode):
    raise SystemExit('ISO extraction root is not a directory')
files=[]
for p in root.rglob('*'):
    mode=p.lstat().st_mode
    if stat.S_ISREG(mode):
        files.append(p)
    elif not stat.S_ISDIR(mode):
        raise SystemExit(f'Unsupported linked or special ISO entry: {p.relative_to(root)}')
# The generated Syslinux configuration duplicates the source bytes, so count
# both names before allocating the FAT image.
config=root/'isolinux/isolinux.cfg'
config_size=config.lstat().st_size
if any(p.lstat().st_size >= 2**32 for p in files) or sum(p.lstat().st_size for p in files)+config_size>1800*1024**2:
    raise SystemExit('Live payload exceeds the bounded 2 GiB USB image capacity')
directory=os.open(root/'isolinux',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
try:
    source_fd=os.open('isolinux.cfg',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
    with os.fdopen(source_fd,'rb') as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise SystemExit('Invalid Syslinux configuration source')
        output_fd=os.open('syslinux.cfg',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644,dir_fd=directory)
        with os.fdopen(output_fd,'wb') as output:
            shutil.copyfileobj(source,output,1024**2)
finally:
    os.close(directory)
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
# The installer overwrites the ISO's ldlinux.c32 with its embedded loader.
# Build a separate, small regular-file FAT volume to establish the bytes this
# same installer writes, independently of the source ISO and final image.
python3 - "$REFERENCE_FAT" <<'PYREFERENCE'
import pathlib,sys
with pathlib.Path(sys.argv[1]).open('xb') as stream:
    stream.truncate(64*1024**2)
PYREFERENCE
mkfs.vfat -F 32 -n BEAMO_REF -h 2048 "$REFERENCE_FAT"
mmd -i "$REFERENCE_FAT" ::/isolinux
syslinux --install --directory /isolinux "$REFERENCE_FAT"
python3 - "$FAT" "$STAGED_OUT" "$ISO" <<'PY'
import pathlib,secrets,shutil,struct,sys
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
PY
# Read the packaged files through the final MBR image, including its partition
# offset. Verify before writing success sidecars; a failed image is not a bundle.
python3 - "$TREE" "$STAGED_OUT" "$ISO" "$REFERENCE_FAT" <<'PYVERIFY'
import hashlib,json,pathlib,struct,subprocess,sys
root,out,iso,reference=map(pathlib.Path,sys.argv[1:])
source_manifest=(root/'desktop-build.json').read_bytes()
manifest=json.loads(source_manifest)
names={'Start Beamo Wipe Linux','Start Beamo Wipe.exe'}
if not isinstance(manifest.get('files'),dict) or set(manifest['files'])!=names:
    raise SystemExit('USB manifest must contain exactly both desktop launchers')
# File readback alone cannot prove the partition table points to those bytes.
with out.open('rb') as image:
    mbr=image.read(512)
if (len(mbr)!=512 or mbr[510:512]!=b'\x55\xaa'
        or struct.unpack_from('<I',mbr,440)[0]==0
        or mbr[446]!=0x80 or mbr[450]!=0x0c or any(mbr[462:510])):
    raise SystemExit('USB MBR layout readback mismatch')
start,sectors=struct.unpack_from('<II',mbr,454)
offset=start*512
if start!=2048 or sectors==0 or offset+sectors*512!=out.stat().st_size:
    raise SystemExit('USB partition extent readback mismatch')
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(1024**2): h.update(chunk)
    return h.hexdigest()
def readback_digest(name, image=out, partition_offset=offset):
    # Stream through the final partition instead of trusting mcopy's exit code.
    # The live filesystem and boot files matter as much as the launchers, and
    # the squashfs can be too large to buffer in a Python process.
    volume=str(image)+(f'@@{partition_offset}' if partition_offset else '')
    process=subprocess.Popen(['mtype','-i',volume,'::/'+name],
                             stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    h=hashlib.sha256()
    length=0
    with process.stdout as stream:
        while chunk:=stream.read(1024**2):
            h.update(chunk)
            length+=len(chunk)
    if process.wait()!=0:
        raise SystemExit(f'USB file readback failed: {name}')
    return h.hexdigest(),length
readback_hashes={}
for source in sorted(root.rglob('*')):
    if not source.is_file():
        continue
    name=source.relative_to(root).as_posix()
    actual,size=readback_digest(name)
    readback_hashes[name]=actual
    if name=='isolinux/ldlinux.c32':
        # The installer owns this file. Compare the installed bytes in the
        # final image with a second install, not with the displaced ISO file.
        reference_hash,reference_size=readback_digest(name,reference,0)
        if size<512 or (actual,size)!=(reference_hash,reference_size):
            raise SystemExit('USB Syslinux module readback mismatch')
    elif actual!=digest(source):
        raise SystemExit(f'USB file readback mismatch: {name}')
for name in sorted(names):
    actual=readback_hashes.get(name) or readback_digest(name)[0]
    if actual!=manifest['files'][name]:
        raise SystemExit(f'USB launcher readback mismatch: {name}')
# The Syslinux installer writes ldlinux.sys after the ISO tree is copied, so
# source-file readback alone cannot prove that BIOS loader reached the image.
_,loader_size=readback_digest('isolinux/ldlinux.sys')
if loader_size<512:
    raise SystemExit('USB Syslinux loader readback is empty or too short')
sha=digest(out)
out.with_suffix('.img.sha256').write_text(f'{sha}  {out.name}\n')
out.with_suffix('.img.json').write_text(json.dumps({'schema_version':1,'image':out.name,'sha256':sha,'iso':iso.name,'iso_sha256':digest(iso),'layout':'MBR, one active FAT32 partition at sector 2048','size':out.stat().st_size},sort_keys=True,indent=2)+'\n')
PYVERIFY
# Verify the live ISO still matches the manifest and both source paths match
# the snapshot digest. This also catches a source changed only while copied,
# and a snapshot changed while xorriso read it.
PYTHONPATH="$ROOT/src" python3 - "$ROOT/dist/beamo-wipe-${VERSION}-amd64.manifest.json" "$ISO" "$SOURCE_ISO" "$SNAPSHOT_SHA" "$STAGED_OUT.json" <<'PYFINAL'
import hashlib,json,os,pathlib,sys
from beamo_wipe.release_manifest import verify_build_manifest
manifest,iso,snapshot,expected,receipt_path=sys.argv[1:]
verify_build_manifest(pathlib.Path(manifest),allow_dirty=os.environ.get('ALLOW_DIRTY')=='1')
def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as stream:
        for chunk in iter(lambda: stream.read(1024**2),b''): h.update(chunk)
    return h.hexdigest()
receipt=json.loads(pathlib.Path(receipt_path).read_bytes())
if digest(iso)!=expected or digest(snapshot)!=expected or receipt.get('iso_sha256')!=expected:
    raise SystemExit('ISO source changed during USB image assembly')
PYFINAL
# os.link refuses an existing destination of any type. Plain `ln source dest`
# treats a directory created at dest during publication as a target directory.
publish_link() {
  python3 -c 'import os,sys; os.link(sys.argv[1],sys.argv[2],follow_symlinks=False)' "$1" "$2"
}
publish_link "$STAGED_OUT" "$OUT"
published_image=1
publish_link "$STAGED_OUT.sha256" "$OUT.sha256"
published_sha=1
publish_link "$STAGED_OUT.json" "$OUT.json"
published_json=1
# A writer can replace an earlier output while later sidecars are published.
# Refuse success unless every final pathname still names our staged inode.
for suffix in '' .sha256 .json; do
  if [[ ! -f "$STAGED_OUT$suffix" || -L "$OUT$suffix" ||
        ! "$STAGED_OUT$suffix" -ef "$OUT$suffix" ]]; then
    echo 'Published USB image bundle changed before finalization.' >&2
    exit 2
  fi
done
printf 'Built Windows-readable USB image: %s\n' "$OUT"
