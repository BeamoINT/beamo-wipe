#!/usr/bin/env bash
# Destructive-path verification for an isolated x86_64 Linux worker only.
# QEMU receives only newly-created image files; no host block device is passed.
set -euo pipefail
umask 077

ROOT="$(CDPATH='' cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
  echo "ABORT: QEMU verification requires isolated x86_64 Linux" >&2
  exit 2
fi
if [[ -d /Users/HP ]]; then
  echo "ABORT: refusing to run on the development Mac" >&2
  exit 2
fi

VERSION="${BEAMO_WIPE_VERSION:-0.2.1}"
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "ABORT: invalid BEAMO_WIPE_VERSION" >&2
  exit 2
fi
ISO="$ROOT/dist/beamo-wipe-${VERSION}-amd64.iso"
MANIFEST="$ROOT/dist/beamo-wipe-${VERSION}-amd64.manifest.json"
[[ -f "$ISO" && -f "$MANIFEST" ]] || {
  echo "ABORT: exact versioned ISO and manifest are required" >&2
  exit 2
}

RUN_ROOT="$(mktemp -d /tmp/beamo-wipe-qemu.XXXXXX)"
EVIDENCE_DIR="$RUN_ROOT/evidence"
TARGET="$RUN_ROOT/target.qcow2"
TARGET_RAW="$RUN_ROOT/target.raw"
ISO_MOUNT="$RUN_ROOT/iso"
SQUASH_MOUNT="$RUN_ROOT/squash"
NWIPE_BIN="$RUN_ROOT/nwipe"
mkdir -m 0700 "$EVIDENCE_DIR" "$ISO_MOUNT" "$SQUASH_MOUNT"
mkdir -p "$ROOT/qemu-evidence"
printf '%s\n' "$EVIDENCE_DIR" >"$ROOT/qemu-evidence/PATH"

LOOP=""
BOOT_LOOP=""
ISO_MOUNTED=0
SQUASH_MOUNTED=0
BIOS_PID=""
UEFI_PID=""
cleanup() {
  set +e
  for pid in "$BIOS_PID" "$UEFI_PID"; do
    if [[ "$pid" =~ ^[0-9]+$ ]]; then
      kill "$pid" 2>/dev/null
      wait "$pid" 2>/dev/null
    fi
  done
  if [[ "$SQUASH_MOUNTED" == 1 ]]; then sudo umount "$SQUASH_MOUNT"; fi
  if [[ "$ISO_MOUNTED" == 1 ]]; then sudo umount "$ISO_MOUNT"; fi
  if [[ "$LOOP" =~ ^/dev/loop[0-9]+$ ]]; then sudo losetup -d "$LOOP"; fi
  if [[ "$BOOT_LOOP" =~ ^/dev/loop[0-9]+$ ]]; then sudo losetup -d "$BOOT_LOOP"; fi
  rm -f -- "$TARGET" "$TARGET_RAW" "$NWIPE_BIN" "$RUN_ROOT/ovmf-vars.fd"
}
trap cleanup EXIT HUP INT TERM

log() {
  printf '[qemu-verify] %s\n' "$*" | tee -a "$EVIDENCE_DIR/run.txt"
}

log "worker_os=Linux worker_arch=x86_64"
qemu-system-x86_64 --version >"$EVIDENCE_DIR/qemu-version.txt"
git rev-parse HEAD >"$EVIDENCE_DIR/source-commit.txt"

# Verify every consumer checksum and bind the manifest to the actual ISO bytes.
(
  cd "$ROOT/dist"
  sha256sum -c "$(basename "$ISO").sha256"
  sha256sum -c "$(basename "$MANIFEST").sha256"
) >"$EVIDENCE_DIR/checksums.txt" 2>&1
PYTHONPATH="$ROOT/src" python3 -c \
  'import pathlib,sys; from beamo_wipe.release_manifest import verify_manifest; verify_manifest(pathlib.Path(sys.argv[1]))' \
  "$MANIFEST"
magic="$(dd if="$ISO" bs=1 skip=32769 count=5 status=none)"
[[ "$magic" == CD001 ]] || { echo "ISO 9660 PVD check failed" >&2; exit 2; }
isoinfo -d -i "$ISO" >"$EVIDENCE_DIR/isoinfo.txt" 2>&1
grep -q 'El Torito' "$EVIDENCE_DIR/isoinfo.txt" || {
  echo "ISO has no El Torito boot catalog" >&2
  exit 2
}

# Inspect the exact filesystem that QEMU will boot. Mounts are read-only and
# private to this disposable worker; failure to inspect is a hard failure.
sudo mount -o ro,loop "$ISO" "$ISO_MOUNT"
ISO_MOUNTED=1
[[ -f "$ISO_MOUNT/live/filesystem.squashfs" ]] || {
  echo "live filesystem.squashfs missing" >&2
  exit 2
}
sudo mount -t squashfs -o ro,loop "$ISO_MOUNT/live/filesystem.squashfs" "$SQUASH_MOUNT"
SQUASH_MOUNTED=1
SHIPPED_NWIPE="$SQUASH_MOUNT/usr/lib/beamo-wipe/nwipe"
[[ -x "$SHIPPED_NWIPE" ]] || { echo "pinned nwipe missing from ISO" >&2; exit 2; }
"$SHIPPED_NWIPE" -V >"$EVIDENCE_DIR/nwipe-version.txt" 2>&1
grep -qiE '^nwipe version 0\.42([[:space:]]|$)' "$EVIDENCE_DIR/nwipe-version.txt" || {
  echo "ISO nwipe version is not the exact pin" >&2
  exit 2
}
if find "$SQUASH_MOUNT/usr/lib/beamo-wipe" \
    "$SQUASH_MOUNT/usr/local/bin/beamo-wipe" \
    "$SQUASH_MOUNT/usr/share/beamo-wipe" \
    \( ! -user root -o ! -group root -o -perm /022 \) -print -quit | grep -q .; then
  echo "ISO contains writable or non-root-owned boot assets" >&2
  exit 2
fi
for forbidden in nano less iproute2 dmidecode pciutils usbutils eject gcc git; do
  if dpkg-query --admindir="$SQUASH_MOUNT/var/lib/dpkg" -W -f='${db:Status-Abbrev}' "$forbidden" 2>/dev/null | grep -q '^ii'; then
    echo "forbidden package present in ISO: $forbidden" >&2
    exit 2
  fi
done
if command -v debsecan >/dev/null 2>&1; then
  debsecan --suite bookworm --only-fixed --format packages \
    --status "$SQUASH_MOUNT/var/lib/dpkg/status" >"$EVIDENCE_DIR/fixed-vulnerabilities.txt"
  if [[ -s "$EVIDENCE_DIR/fixed-vulnerabilities.txt" ]]; then
    echo "ISO contains packages with fixed Debian vulnerabilities" >&2
    exit 2
  fi
else
  echo "debsecan is required for the image vulnerability gate" >&2
  exit 2
fi
install -m 0700 "$SHIPPED_NWIPE" "$NWIPE_BIN"
shipped_sha="$(sha256sum "$SHIPPED_NWIPE" | awk '{print $1}')"
copied_sha="$(sha256sum "$NWIPE_BIN" | awk '{print $1}')"
[[ "$shipped_sha" == "$copied_sha" ]] || { echo "nwipe copy changed" >&2; exit 2; }
sudo umount "$SQUASH_MOUNT"
SQUASH_MOUNTED=0
sudo umount "$ISO_MOUNT"
ISO_MOUNTED=0

# Exercise the complete owner, boot-exclusion, token and countdown state
# machine with fake disks only. No device node is opened by these tests.
BEAMO_WIPE_DRY_RUN=1 python3 -m pytest -q \
  tests/test_confirmation_gates.py \
  tests/test_boot_exclusion_fails_closed.py \
  >"$EVIDENCE_DIR/fake-disk-e2e.txt" 2>&1

# The only destructive process-boundary check uses a newly-created sparse raw
# file attached to a loop node whose backing file is re-proved before each run.
qemu-img create -f raw "$TARGET_RAW" 256M >"$EVIDENCE_DIR/qemu-img.txt" 2>&1
LOOP="$(sudo losetup --find --show "$TARGET_RAW")"
BOOT_LOOP="$(sudo losetup --find --show --read-only "$ISO")"
[[ "$LOOP" =~ ^/dev/loop[0-9]+$ && "$BOOT_LOOP" =~ ^/dev/loop[0-9]+$ ]] || {
  echo "unexpected loop device path" >&2
  exit 2
}
prove_loop() {
  local loop="$1" backing="$2" got
  got="$(sudo losetup -j "$backing" | awk -F: 'NR==1 {print $1}')"
  [[ "$got" == "$loop" && "$(lsblk -dn -o TYPE "$loop")" == loop ]] || {
    echo "loop identity changed" >&2
    exit 2
  }
  if findmnt -rn -S "$loop" | grep -q .; then
    echo "loop target is mounted" >&2
    exit 2
  fi
}
prove_loop "$LOOP" "$TARGET_RAW"
prove_loop "$BOOT_LOOP" "$ISO"
NWIPE_LOG="$RUN_ROOT/nwipe.log"
nwipe_code=0
timeout 45 "$NWIPE_BIN" --autonuke --nogui --nowait --method=zero \
  --rounds=1 --verify=off --noblank --exclude="$BOOT_LOOP" \
  --logfile="$NWIPE_LOG" --PDFreportpath=noPDF "$LOOP" \
  >"$EVIDENCE_DIR/nwipe-boundary.txt" 2>&1 || nwipe_code=$?
[[ "$nwipe_code" == 0 ]] || { echo "nwipe boundary run failed: $nwipe_code" >&2; exit 2; }
grep -Eq '\|[[:space:]]*Erased[[:space:]]*\||100\.00%' "$NWIPE_LOG" || {
  echo "nwipe exited without a target success marker" >&2
  exit 2
}

# A non-block target and an interrupted run must never return success.
bad_code=0
timeout 5 "$NWIPE_BIN" --autonuke --nogui --nowait --method=zero \
  --rounds=1 --verify=off --noblank --exclude="$BOOT_LOOP" \
  --logfile="$RUN_ROOT/bad.log" --PDFreportpath=noPDF "$RUN_ROOT/not-a-device" \
  >"$EVIDENCE_DIR/nwipe-invalid-target.txt" 2>&1 || bad_code=$?
[[ "$bad_code" != 0 ]] || { echo "nwipe accepted a non-block target" >&2; exit 2; }

# BIOS and UEFI get only the ISO and the disposable qcow2 file. A process that
# exits during the boot window is a failed check, not a tolerated timeout.
qemu-img create -f qcow2 "$TARGET" 1G >>"$EVIDENCE_DIR/qemu-img.txt" 2>&1
boot_probe() {
  local label="$1"
  shift
  qemu-system-x86_64 -machine accel=kvm:tcg -m 1024 -nic none \
    "$@" -cdrom "$ISO" -drive "file=$TARGET,if=virtio,format=qcow2" \
    -boot order=d -display none -serial "file:$EVIDENCE_DIR/${label}-serial.txt" \
    -no-reboot >"$EVIDENCE_DIR/${label}-qemu.txt" 2>&1 &
  local pid=$!
  if [[ "$label" == bios ]]; then BIOS_PID="$pid"; else UEFI_PID="$pid"; fi
  sleep 12
  kill -0 "$pid" 2>/dev/null || {
    echo "QEMU $label exited during boot" >&2
    wait "$pid" || true
    exit 2
  }
  kill "$pid"
  wait "$pid" || true
  if [[ "$label" == bios ]]; then BIOS_PID=""; else UEFI_PID=""; fi
  log "$label boot process remained healthy for 12 seconds"
}
boot_probe bios

OVMF_CODE=""
for candidate in /usr/share/OVMF/OVMF_CODE_4M.fd /usr/share/OVMF/OVMF_CODE.fd; do
  if [[ -f "$candidate" ]]; then OVMF_CODE="$candidate"; break; fi
done
[[ -n "$OVMF_CODE" ]] || { echo "OVMF firmware missing" >&2; exit 2; }
OVMF_VARS="${OVMF_CODE/CODE/VARS}"
if [[ -f "$OVMF_VARS" ]]; then
  cp "$OVMF_VARS" "$RUN_ROOT/ovmf-vars.fd"
  boot_probe uefi \
    -drive "if=pflash,format=raw,readonly=on,file=$OVMF_CODE" \
    -drive "if=pflash,format=raw,file=$RUN_ROOT/ovmf-vars.fd"
else
  boot_probe uefi -bios "$OVMF_CODE"
fi

printf 'iso_sha256=%s\nnwipe_sha256=%s\nbios=pass\nuefi=pass\n' \
  "$(sha256sum "$ISO" | awk '{print $1}')" "$shipped_sha" \
  >"$EVIDENCE_DIR/summary.txt"
log "PASS; evidence=$EVIDENCE_DIR"
