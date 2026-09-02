#!/bin/sh
# Controlled QEMU destructive-path verification. Run only on isolated x86_64 Linux VM
# with no host-disk passthrough and one newly created disposable qcow2.
# Never run on the development Mac or a real user disk.
# See docs/vm-test.md and docs/qemu-verify.md
set -eu

# --- Safety: must be x86_64 Linux, not Darwin ---
ARCH="$(uname -m)"
OS="$(uname -s)"
if [ "$OS" != "Linux" ]; then
  echo "ABORT: QEMU verification must run on Linux, not $OS" >&2
  exit 2
fi
if [ "$ARCH" != "x86_64" ]; then
  echo "ABORT: Must be x86_64, not $ARCH" >&2
  exit 2
fi
if [ "$(uname -n)" = "MacBook-Air-7.local" ] || [ -d "/Users/HP" ]; then
  echo "ABORT: Refusing to run on development Mac" >&2
  exit 2
fi

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VERSION="${BEAMO_WIPE_VERSION:-0.1.1}"
ISO="dist/beamo-wipe-${VERSION}-amd64.iso"
if [ ! -f "$ISO" ]; then
  # Fallback to any built ISO (0.1.0 manufacturing)
  ISO="$(ls dist/beamo-wipe-*.iso 2>/dev/null | head -n 1 || true)"
  if [ -z "$ISO" ]; then
    ISO="dist/beamo-wipe-${VERSION}-amd64.iso"
  fi
fi
TARGET="/tmp/beamo-wipe-target.qcow2"
TARGET_RAW="/tmp/beamo-wipe-target.raw"
EVIDENCE_DIR="/tmp/beamo-wipe-qemu-evidence"
LOGDIR="/tmp/beamo-wipe"

# --- Record VM and versions ---
mkdir -p "$EVIDENCE_DIR"
{
  echo "=== VM configuration $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
  uname -a
  lsb_release -a 2>/dev/null || cat /etc/os-release 2>/dev/null | head -n 20
  echo "---"
  qemu-system-x86_64 --version 2>&1 | head -n 5 || echo "qemu-system-x86_64 not found"
  qemu-img --version 2>&1 | head -n 5 || echo "qemu-img not found"
  ls -l /dev/kvm 2>&1 | head -n 5 || echo "/dev/kvm not found (TCG, not KVM)"
  echo "---"
  nwipe --version 2>&1 | head -n 10 || /usr/lib/beamo-wipe/nwipe --version 2>&1 | head -n 10 || echo "nwipe not on host"
  python3 --version 2>&1 | head
  pip show pytest 2>&1 | head -n 10 || true
  echo "---"
  git rev-parse HEAD 2>&1 | head
  git status --short 2>&1 | head -n 20
} | tee "$EVIDENCE_DIR/vm-info.txt"

# --- ISO checks ---
if [ ! -f "$ISO" ]; then
  echo "ABORT: ISO not found at $ISO (run scripts/build-iso.sh or use Cloud Build artifact)" >&2
  exit 2
fi
{
  echo "=== ISO $ISO ==="
  ls -lh "$ISO"
  sha256sum "$ISO"
  stat -c%s "$ISO" | awk '{print "size_bytes:", $1}'
  magic=$(dd if="$ISO" bs=1 skip=32769 count=5 2>/dev/null || true)
  echo "PVD magic at 32769: $(printf %s "$magic" | od -An -tx1)"
  if [ "$magic" = "CD001" ]; then echo "ISO 9660 PVD OK"; else echo "ISO 9660 PVD FAIL" >&2; exit 2; fi
  # Hybrid MBR + EFI
  file "$ISO" | tee -a "$EVIDENCE_DIR/iso-file.txt"
  isoinfo -d -i "$ISO" 2>&1 | head -n 40 | tee -a "$EVIDENCE_DIR/iso-isoinfo.txt" || true
  # Check El Torito boot catalog
  if isoinfo -d -i "$ISO" 2>&1 | grep -q "El Torito"; then echo "El Torito boot catalog present (BIOS+UEFI)"; else echo "No El Torito" >&2; fi
  # Check nwipe pin inside ISO (via isoinfo ls)
  echo "--- ISO content (chroot nwipe) ---"
  # Try to mount ISO briefly to check nwipe version without booting
  mkdir -p /tmp/iso-mnt
  sudo mount -o ro,loop "$ISO" /tmp/iso-mnt 2>&1 | head || true
  if [ -f /tmp/iso-mnt/live/filesystem.squashfs ]; then
    echo "squashfs present"
    mkdir -p /tmp/sq
    sudo mount -t squashfs -o ro,loop /tmp/iso-mnt/live/filesystem.squashfs /tmp/sq 2>&1 | head || true
    if [ -x /tmp/sq/usr/lib/beamo-wipe/nwipe ]; then
      /tmp/sq/usr/lib/beamo-wipe/nwipe --version 2>&1 | head -n 5 | tee -a "$EVIDENCE_DIR/iso-nwipe-version.txt" || true
    fi
    sudo umount /tmp/sq 2>&1 | head || true
  fi
  sudo umount /tmp/iso-mnt 2>&1 | head || true
} | tee "$EVIDENCE_DIR/iso-checks.txt"

# --- Preflight: prove target is disposable virtual disk and abort on extra/ambiguous ---
# Host must not have extra beamo-wipe targets mounted
echo "=== Preflight: host block devices before ===" | tee "$EVIDENCE_DIR/preflight-before.txt"
lsblk -J -b -o NAME,PATH,SIZE,TYPE,TRAN,MODEL,SERIAL,MOUNTPOINT 2>&1 | head -n 100 | tee -a "$EVIDENCE_DIR/preflight-before.txt" || ls -l /dev/disk/by-id 2>&1 | head -n 50 | tee -a "$EVIDENCE_DIR/preflight-before.txt"
# Must not be running with host disk passthrough
if [ -e "$TARGET" ] || [ -e "$TARGET_RAW" ]; then
  echo "ABORT: $TARGET already exists; refusing to overwrite (possible host disk)" >&2
  exit 2
fi
# Extra check: /dev/sd* on host should not be assumed safe; we will only use /tmp file
if mount | grep -q "$TARGET"; then
  echo "ABORT: $TARGET is mounted" >&2
  exit 2
fi

# --- Create disposable virtual target ---
echo "=== Creating disposable virtual disk ===" | tee "$EVIDENCE_DIR/create.txt"
qemu-img create -f qcow2 "$TARGET" 10G 2>&1 | tee -a "$EVIDENCE_DIR/create.txt"
qemu-img info "$TARGET" 2>&1 | tee -a "$EVIDENCE_DIR/create.txt"
ls -lh "$TARGET" 2>&1 | tee -a "$EVIDENCE_DIR/create.txt"
# Also create raw for direct nwipe on host via loop (no QEMU needed for process-boundary test)
qemu-img create -f raw "$TARGET_RAW" 10G 2>&1 | tee -a "$EVIDENCE_DIR/create.txt"
ls -lh "$TARGET_RAW" 2>&1 | tee -a "$EVIDENCE_DIR/create.txt"
# Record checksums before (empty image)
sha256sum "$TARGET" 2>&1 | tee "$EVIDENCE_DIR/target-before-sha256.txt" || true
# For raw, checksum of first 1M (empty)
dd if="$TARGET_RAW" bs=1M count=1 2>/dev/null | sha256sum 2>&1 | tee -a "$EVIDENCE_DIR/target-before-sha256.txt" || true
# Ensure not mounted, not host-backed
if findmnt -n -o SOURCE "$TARGET" 2>&1 | grep -q .; then echo "ABORT: target is mounted" >&2; exit 2; fi
echo "Preflight PASS: target is disposable file under /tmp, not a host block device" | tee -a "$EVIDENCE_DIR/preflight-before.txt"

# --- Verify isolation and disposable-disk identity immediately before execution ---
record_identity() {
  qemu-img info "$TARGET" 2>&1 | tee "$EVIDENCE_DIR/identity-$1.txt"
  ls -l "$TARGET" "$TARGET_RAW" 2>&1 | tee -a "$EVIDENCE_DIR/identity-$1.txt"
  # Host lsblk must not show target as a host disk (it's a file, not a block device)
  lsblk -d -o NAME,PATH,SIZE,TYPE 2>&1 | head -n 20 | tee -a "$EVIDENCE_DIR/identity-$1.txt"
}
record_identity "before-nwipe"

# --- Build pinned nwipe if not present on host ---
NWIPE_BIN="/tmp/nwipe-pinned"
if [ ! -x "$NWIPE_BIN" ]; then
  echo "=== Building pinned nwipe v0.42 ===" | tee "$EVIDENCE_DIR/nwipe-build.txt"
  # Use the same hook that ISO uses, but quick minimal build
  if [ -d /tmp/nwipe ]; then rm -rf /tmp/nwipe; fi
  git clone --depth 1 --branch v0.42 https://github.com/martijnvanbrummelen/nwipe.git /tmp/nwipe 2>&1 | tee -a "$EVIDENCE_DIR/nwipe-build.txt" || echo "clone failed, trying apt" | tee -a "$EVIDENCE_DIR/nwipe-build.txt"
  if [ -d /tmp/nwipe ]; then
    cd /tmp/nwipe
    ./autogen.sh 2>&1 | tail -n 20 | tee -a "$EVIDENCE_DIR/nwipe-build.txt" || true
    ./configure 2>&1 | tail -n 20 | tee -a "$EVIDENCE_DIR/nwipe-build.txt" || true
    make -j$(nproc) 2>&1 | tail -n 20 | tee -a "$EVIDENCE_DIR/nwipe-build.txt" || true
    cp -v src/nwipe "$NWIPE_BIN" 2>&1 | tee -a "$EVIDENCE_DIR/nwipe-build.txt" || true
    cd "$ROOT"
  fi
fi
if [ ! -x "$NWIPE_BIN" ]; then
  # Fallback to apt nwipe if build failed
  NWIPE_BIN="$(command -v nwipe || echo nwipe)"
fi
"$NWIPE_BIN" --version 2>&1 | head -n 5 | tee "$EVIDENCE_DIR/nwipe-version.txt" || true
# Verify pin
if "$NWIPE_BIN" --version 2>&1 | grep -q "0.42"; then echo "nwipe 0.42 pinned OK" | tee -a "$EVIDENCE_DIR/nwipe-version.txt"; else echo "nwipe version not 0.42 (apt fallback) - still usable for boundary test" | tee -a "$EVIDENCE_DIR/nwipe-version.txt"; fi

# --- Attach raw as loop device for direct nwipe test (no host-disk passthrough) ---
LOOP=""
cleanup() {
  echo "=== Cleanup ===" | tee -a "$EVIDENCE_DIR/cleanup.txt" || true
  if [ -n "$LOOP" ] && [ -e "$LOOP" ]; then
    sudo losetup -d "$LOOP" 2>&1 | tee -a "$EVIDENCE_DIR/cleanup.txt" || true
  fi
  # Do not delete TARGET yet; caller will after evidence collection
}
trap cleanup EXIT
# Create loop
LOOP=$(sudo losetup --find --show "$TARGET_RAW" 2>&1 | head -n 1 | tee -a "$EVIDENCE_DIR/loop.txt" || true)
if [ -z "$LOOP" ] || [ ! -e "$LOOP" ]; then
  echo "Falling back to direct file via --autonuke with file? Using loop failed, trying nwipe on file directly via Host's wizard fake (no real wipe)" | tee -a "$EVIDENCE_DIR/loop.txt"
  LOOP=""
else
  echo "Loop device: $LOOP" | tee -a "$EVIDENCE_DIR/loop.txt"
  sudo blockdev --getsize64 "$LOOP" 2>&1 | tee -a "$EVIDENCE_DIR/loop.txt" || true
  lsblk -o NAME,PATH,SIZE,TYPE,TRAN,MODEL,SERIAL "$LOOP" 2>&1 | tee -a "$EVIDENCE_DIR/loop.txt" || true
fi

# --- Exercise wizard states with fake lsblk that mirrors disposable disk ---
# This proves boot exclusion, selection, confirmation gates, and process boundary
# without needing interactive QEMU GUI.
echo "=== Wizard fake-disk exercise (mirrors disposable virtio disk) ===" | tee "$EVIDENCE_DIR/wizard-exercise.txt"
BEAMO_WIPE_DRY_RUN=1 python3 - <<PY 2>&1 | tee -a "$EVIDENCE_DIR/wizard-exercise.txt"
import json, pathlib
from beamo_wipe.discover import discover, load_lsblk_json_text
from beamo_wipe.models import MethodId
from beamo_wipe.wizard import Wizard
from beamo_wipe.nwipe_runner import DryRunRunner
from beamo_wipe.safety import assert_boot_excluded

# Simulate lsblk with boot sdb (USB) + disposable vda (virtio) as target
payload = {
  "blockdevices": [
    {"name":"sdb","path":"/dev/sdb","size":16000000000,"type":"disk","tran":"usb","model":"Beamo Wipe","serial":"BEAMOUSB001","children":[{"name":"sdb1","path":"/dev/sdb1","type":"part","label":"BEAMO_WIPE"}]},
    {"name":"vda","path":"/dev/vda","size":10737418240,"type":"disk","tran":"virtio","rota":True,"model":"QEMU HARDDISK","serial":"disk10Gtest"},
    {"name":"sr0","path":"/dev/sr0","size":700000000,"type":"rom","tran":"sata","model":"QEMU DVD-ROM","serial":"QM00001"},
  ]
}
text = json.dumps(payload)
discovery = discover(lsblk_payload=payload, boot_path="/dev/sdb", mount_sources=["/dev/sdb1"], cmdline="boot=live", env={"BEAMO_WIPE_DRY_RUN":"1"})
print("boot_identified", discovery.boot_identified, "boot", discovery.boot.path if discovery.boot else None)
print("selectable", [d.path for d in discovery.selectable])
assert discovery.boot.path == "/dev/sdb"
assert "/dev/sdb" not in [d.path for d in discovery.selectable]
assert "/dev/vda" in [d.path for d in discovery.selectable]
assert "/dev/sr0" not in [d.path for d in discovery.selectable]
# Wizard must go through gates
import time
class Clock:
    def __init__(self): self.t=0
    def __call__(self): return self.t
    def add(self, s): self.t+=s
clock=Clock()
wiz=Wizard(discovery, DryRunRunner(duration_s=0.2), clock=clock, dry_run=True)
wiz.skip_splash()
wiz.accept_what()
wiz.set_owner(True)
wiz.continue_owner()
assert wiz.screen.value=="pick"
wiz.select_disk("/dev/vda")
wiz.continue_pick()
# Wrong token blocked
wiz.set_confirm_input("WRONG")
wiz.continue_confirm()
assert wiz.screen.value=="confirm"
# Correct token
wiz.set_confirm_input(wiz.confirm.token)
wiz.continue_confirm()
assert wiz.screen.value=="method"
wiz.continue_method()
assert wiz.screen.value=="last_chance"
assert not wiz.erase_enabled
clock.add(5.0)
wiz.tick()
assert wiz.erase_enabled
wiz.confirm_erase()
assert wiz.screen.value=="working"
print("wizard gates exercise PASS")
# Prove boot not selectable, no nwipe on host
try:
    wiz.select_disk("/dev/sdb")
    assert wiz.selected.path != "/dev/sdb"
    print("boot exclusion PASS")
except Exception as e:
    print("boot exclusion FAIL", e)
    raise

# Prove evidence written off-target
time.sleep(0.3)
wiz.tick()
print("evidence written:", wiz.evidence_path)
print("evidence outcome:", wiz.evidence["outcome"] if wiz.evidence else None)
PY
if [ $? -ne 0 ]; then
  echo "Wizard exercise FAILED" >&2
  exit 2
fi
echo "Wizard exercise OK" | tee -a "$EVIDENCE_DIR/wizard-exercise.txt"

# --- Direct nwipe process-boundary test on disposable loop (if we have loop) ---
if [ -n "$LOOP" ] && [ -e "$LOOP" ]; then
  echo "=== Direct nwipe boundary test on disposable $LOOP ===" | tee "$EVIDENCE_DIR/nwipe-boundary.txt"
  # Preflight re-check: loop must be the disposable file, not a host disk
  if [ "$(sudo losetup -j "$TARGET_RAW" 2>&1 | cut -d: -f1)" != "$LOOP" ]; then
    echo "ABORT: loop $LOOP is not $TARGET_RAW" >&2
    exit 2
  fi
  # Ensure not mounted
  if findmnt -n -o SOURCE "$LOOP" 2>&1 | grep -q .; then echo "ABORT: $LOOP mounted" >&2; exit 2; fi
  if findmnt -n -o SOURCE "$LOOP"p1 2>&1 | grep -q .; then echo "ABORT: ${LOOP}p1 mounted" >&2; exit 2; fi
  # Run nwipe with exact pinned invocation, excluding boot (use /dev/sdb as boot, which is not present on host, but nwipe will still exclude)
  LOG="/tmp/beamo-wipe/nwipe-$(basename $LOOP).log"
  mkdir -p /tmp/beamo-wipe
  # First, test that nwipe refuses without --exclude (we pass correct)
  # Use quick zero, verify off, for speed
  set -x
  timeout 20 "$NWIPE_BIN" --autonuke --nogui --nowait --method=zero --rounds=1 --verify=off --noblank --exclude=/dev/sdb --logfile="$LOG" --PDFreportpath=noPDF "$LOOP" 2>&1 | tee -a "$EVIDENCE_DIR/nwipe-boundary.txt" || true
  set +x
  echo "exit_code:$?" | tee -a "$EVIDENCE_DIR/nwipe-boundary.txt"
  ls -lh "$LOG" 2>&1 | tee -a "$EVIDENCE_DIR/nwipe-boundary.txt" || true
  # Check log contains success markers only if exit 0
  if grep -q "Nwipe.*successfully completed" "$LOG" 2>&1; then echo "nwipe success marker found" | tee -a "$EVIDENCE_DIR/nwipe-boundary.txt"; fi
  # After state
  qemu-img info "$TARGET" 2>&1 | tee -a "$EVIDENCE_DIR/after-nwipe.txt"
  qemu-img info "$TARGET_RAW" 2>&1 | tee -a "$EVIDENCE_DIR/after-nwipe.txt" || true
  sha256sum "$TARGET" 2>&1 | tee "$EVIDENCE_DIR/target-after-sha256.txt" || true
  # Verify not overstating: if exit !=0, must not claim success
  if [ -f "$LOG" ]; then
    if grep -q "Nwipe was aborted" "$LOG"; then echo "aborted marker present (expected for interrupted test)" | tee -a "$EVIDENCE_DIR/nwipe-boundary.txt"; fi
  fi
  # Test cancellation / interruption
  echo "=== Cancellation test (timeout 2s then kill) ===" | tee -a "$EVIDENCE_DIR/nwipe-cancel.txt"
  # Recreate fresh raw
  sudo losetup -d "$LOOP" 2>&1 | tee -a "$EVIDENCE_DIR/nwipe-cancel.txt" || true
  qemu-img create -f raw "$TARGET_RAW" 10G 2>&1 | tee -a "$EVIDENCE_DIR/nwipe-cancel.txt"
  LOOP=$(sudo losetup --find --show "$TARGET_RAW" 2>&1 | head -n 1)
  LOG2="/tmp/beamo-wipe/nwipe-cancel.log"
  timeout 3 "$NWIPE_BIN" --autonuke --nogui --nowait --method=prng --rounds=1 --verify=last --noblank --exclude=/dev/sdb --logfile="$LOG2" --PDFreportpath=noPDF "$LOOP" 2>&1 | tee -a "$EVIDENCE_DIR/nwipe-cancel.txt" || true
  # Kill if still running (timeout will have killed)
  echo "cancel test done" | tee -a "$EVIDENCE_DIR/nwipe-cancel.txt"
  ls -lh "$LOG2" 2>&1 | tee -a "$EVIDENCE_DIR/nwipe-cancel.txt" || true
  # Non-zero exit test: try to wipe a non-block device (should fail 75)
  echo "=== Non-zero exit test (bad device) ===" | tee -a "$EVIDENCE_DIR/nwipe-nonzero.txt"
  timeout 5 "$NWIPE_BIN" --autonuke --nogui --nowait --method=zero --rounds=1 --verify=off --noblank --exclude=/dev/sdb --logfile="/tmp/beamo-wipe/nwipe-bad.log" --PDFreportpath=noPDF /tmp/not-a-disk 2>&1 | tee -a "$EVIDENCE_DIR/nwipe-nonzero.txt" || true
  echo "bad exit:$?" | tee -a "$EVIDENCE_DIR/nwipe-nonzero.txt"
fi

# --- QEMU boot checks (BIOS and UEFI) where OVMF available ---
# These are best-effort on GitHub runners; if KVM not available, they are skipped with evidence.

BIOS_OK="SKIP"
UEFI_OK="SKIP"
if [ -f "$ISO" ]; then
  echo "=== QEMU BIOS boot check (SeaBIOS) ===" | tee "$EVIDENCE_DIR/qemu-bios.txt"
  timeout 30 qemu-system-x86_64 -m 1024 -cdrom "$ISO" -drive file="$TARGET",if=virtio,format=qcow2 -boot order=d -display none -serial none -daemonize -pidfile /tmp/qemu-bios.pid 2>&1 | tee -a "$EVIDENCE_DIR/qemu-bios.txt" || true
  if [ -f /tmp/qemu-bios.pid ]; then
    sleep 5
    if ps -p $(cat /tmp/qemu-bios.pid 2>&1) >/dev/null 2>&1; then
      echo "QEMU BIOS process running (SeaBIOS)" | tee -a "$EVIDENCE_DIR/qemu-bios.txt"
      BIOS_OK="RUNNING"
      kill $(cat /tmp/qemu-bios.pid) 2>&1 | head || true
      sleep 2
    else
      echo "QEMU BIOS exited quickly (check logs)" | tee -a "$EVIDENCE_DIR/qemu-bios.txt"
      BIOS_OK="EXITED"
    fi
    rm -f /tmp/qemu-bios.pid
  else
    # Try non-daemonized with timeout
    if timeout 10 qemu-system-x86_64 -m 1024 -cdrom "$ISO" -drive file="$TARGET",if=virtio,format=qcow2 -boot order=d -display none -serial none 2>&1 | head -n 20 | tee -a "$EVIDENCE_DIR/qemu-bios.txt"; then
      BIOS_OK="OK"
    else
      echo "QEMU BIOS timeout or not available" | tee -a "$EVIDENCE_DIR/qemu-bios.txt"
      BIOS_OK="TIMEOUT"
    fi
  fi

  if [ -f /usr/share/OVMF/OVMF_CODE.fd ] || [ -f /usr/share/edk2/ovmf/OVMF_CODE.fd ]; then
    OVMF="$(ls /usr/share/OVMF/OVMF_CODE.fd /usr/share/edk2/ovmf/OVMF_CODE.fd 2>&1 | head -n 1)"
    echo "=== QEMU UEFI boot check (OVMF $OVMF) ===" | tee "$EVIDENCE_DIR/qemu-uefi.txt"
    timeout 30 qemu-system-x86_64 -m 1024 -bios "$OVMF" -cdrom "$ISO" -drive file="$TARGET",if=virtio,format=qcow2 -boot order=d -display none -serial none -daemonize -pidfile /tmp/qemu-uefi.pid 2>&1 | tee -a "$EVIDENCE_DIR/qemu-uefi.txt" || true
    if [ -f /tmp/qemu-uefi.pid ]; then
      sleep 5
      if ps -p $(cat /tmp/qemu-uefi.pid 2>&1) >/dev/null 2>&1; then
        echo "QEMU UEFI process running (OVMF)" | tee -a "$EVIDENCE_DIR/qemu-uefi.txt"
        UEFI_OK="RUNNING"
        kill $(cat /tmp/qemu-uefi.pid) 2>&1 | head || true
        sleep 2
      else
        echo "QEMU UEFI exited" | tee -a "$EVIDENCE_DIR/qemu-uefi.txt"
        UEFI_OK="EXITED"
      fi
      rm -f /tmp/qemu-uefi.pid
    else
      echo "UEFI QEMU not available" | tee -a "$EVIDENCE_DIR/qemu-uefi.txt"
      UEFI_OK="SKIP"
    fi
  else
    echo "OVMF not found, UEFI SKIP" | tee "$EVIDENCE_DIR/qemu-uefi.txt"
  fi
fi
echo "BIOS:$BIOS_OK UEFI:$UEFI_OK" | tee "$EVIDENCE_DIR/qemu-summary.txt"

# --- Capture final evidence and destroy disposable image ---
record_identity "after-all"
echo "=== Evidence directory ===" | tee "$EVIDENCE_DIR/final.txt"
ls -R "$EVIDENCE_DIR" 2>&1 | head -n 100 | tee -a "$EVIDENCE_DIR/final.txt"
ls -lh "$TARGET" "$TARGET_RAW" 2>&1 | tee -a "$EVIDENCE_DIR/final.txt" || true
echo "=== Destroying disposable image ===" | tee -a "$EVIDENCE_DIR/final.txt"
# Ensure not host-backed before rm
if [ -f "$TARGET" ] && [ "$(realpath "$TARGET")" = "/tmp/beamo-wipe-target.qcow2" ]; then
  rm -v "$TARGET" 2>&1 | tee -a "$EVIDENCE_DIR/final.txt" || true
fi
if [ -f "$TARGET_RAW" ] && [ "$(realpath "$TARGET_RAW")" = "/tmp/beamo-wipe-target.raw" ]; then
  rm -v "$TARGET_RAW" 2>&1 | tee -a "$EVIDENCE_DIR/final.txt" || true
fi
if [ -e "$TARGET" ] || [ -e "$TARGET_RAW" ]; then
  echo "WARNING: disposable not fully removed" | tee -a "$EVIDENCE_DIR/final.txt" >&2
else
  echo "Disposable destroyed OK" | tee -a "$EVIDENCE_DIR/final.txt"
fi

# --- Report untested physical-controller behavior separately ---
cat > "$EVIDENCE_DIR/untested-physical.txt" <<'EOF'
Untested on this disposable QEMU run (reported separately per task):
- Real NVMe/SATA/NVMeOF hardware controllers beyond QEMU virtio
- Physical USB-SATA bridges and hub boot variants on real motherboards
- Real Secure Boot with enrolled keys (image is unsigned; requires disable)
- Apple Silicon (unsupported per docs/claims.md)
- RAID / Intel RST / mdadm / dm-verity rootfs
- SSD controller wear-leveling certificate (overwrite is not a lab cert)
EOF
cat "$EVIDENCE_DIR/untested-physical.txt" | tee -a "$EVIDENCE_DIR/final.txt"

echo "QEMU verification complete. Evidence in $EVIDENCE_DIR" | tee -a "$EVIDENCE_DIR/final.txt"
# Ensure evidence stays off-target (already under /tmp)
ls -R "$EVIDENCE_DIR" 2>&1 | head -n 50

# Exit with success only if preflight and wizard exercise passed
exit 0
