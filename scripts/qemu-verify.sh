#!/usr/bin/env bash
# Destructive-path verification for an isolated x86_64 Linux worker only.
# QEMU receives only newly-created image files; no host block device is passed.
set -Eeuo pipefail
umask 077

# Redirected verification commands keep potentially noisy or sensitive output
# in the private evidence directory. Preserve a safe failure location on stderr
# so a hosted stop can be diagnosed without dumping that evidence into CI logs.
on_error() {
  local rc="$1" line="$2"
  trap - ERR
  printf 'ABORT: qemu verification failed at line %s (exit %s)\n' "$line" "$rc" >&2
  exit "$rc"
}
trap 'on_error "$?" "$LINENO"' ERR

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

BOOT_WAIT_SECONDS=120
if [[ ! -r /dev/kvm ]]; then BOOT_WAIT_SECONDS=300; fi

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
# Both the shipped ISO and this 1 GiB fake target round to a 1 GB display
# label.  A stable serial therefore supplies the wizard's disambiguating
# confirmation token and lets the harness exercise that safety path exactly.
QEMU_TARGET_SERIAL="0001"
ISO_MOUNT="$RUN_ROOT/iso"
SQUASH_MOUNT="$RUN_ROOT/squash"
NWIPE_BIN="$RUN_ROOT/nwipe"
REPORT_RAW="$RUN_ROOT/report-usb.raw"
REPORT_MOUNT="$RUN_ROOT/report-usb"
mkdir -m 0700 "$EVIDENCE_DIR" "$ISO_MOUNT" "$SQUASH_MOUNT" "$REPORT_MOUNT"
mkdir -p "$ROOT/qemu-evidence"
printf '%s\n' "$EVIDENCE_DIR" >"$ROOT/qemu-evidence/PATH"

LOOP=""
BOOT_LOOP=""
REPORT_LOOP=""
REPORT_LOOP_RO=""
ISO_MOUNTED=0
SQUASH_MOUNTED=0
REPORT_MOUNTED=0
BIOS_PID=""
UEFI_PID=""
CLEANED_UP=0

loop_matches() {
  local loop="$1" backing="$2" expected_ro="${3:-either}" attached type ro
  [[ "$loop" =~ ^/dev/loop[0-9]+$ && -f "$backing" ]] || return 1
  attached="$(sudo losetup -j "$backing" | awk -F: '{print $1}')"
  type="$(lsblk -dn -o TYPE "$loop" 2>/dev/null | tr -d '[:space:]')"
  ro="$(lsblk -dn -o RO "$loop" 2>/dev/null | tr -d '[:space:]')"
  [[ "$attached" == "$loop" && "$type" == loop ]] || return 1
  [[ "$expected_ro" == either || "$ro" == "$expected_ro" ]]
}

prove_unmounted_loop() {
  local label="$1" loop="$2" backing="$3" expected_ro="${4:-either}"
  if ! loop_matches "$loop" "$backing" "$expected_ro"; then
    printf 'ABORT: %s loop backing, type, or read-only state changed\n' "$label" >&2
    return 1
  fi
  if findmnt -rn -S "$loop" | grep -q .; then
    printf 'ABORT: %s loop is already mounted\n' "$label" >&2
    return 1
  fi
}

detach_owned_loop() {
  local label="$1" loop="$2" backing="$3" expected_ro="${4:-either}"
  [[ -n "$loop" ]] || return 0
  if ! loop_matches "$loop" "$backing" "$expected_ro"; then
    printf 'ABORT: refusing to detach unproved %s loop %s\n' "$label" "$loop" >&2
    return 1
  fi
  sudo losetup -d "$loop"
}

stop_pid() {
  local pid="$1"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 0
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    for _attempt in $(seq 1 50); do
      kill -0 "$pid" 2>/dev/null || break
      [[ "$(ps -o stat= -p "$pid" 2>/dev/null)" =~ ^Z ]] && break
      sleep 0.1
    done
    if kill -0 "$pid" 2>/dev/null &&
        [[ ! "$(ps -o stat= -p "$pid" 2>/dev/null)" =~ ^Z ]]; then
      kill -KILL "$pid" 2>/dev/null || true
    fi
  fi
  wait "$pid" 2>/dev/null || true
}

cleanup() {
  [[ "$CLEANED_UP" == 0 ]] || return 0
  CLEANED_UP=1
  set +e
  trap - EXIT HUP INT TERM ERR
  local bios_pid="$BIOS_PID" uefi_pid="$UEFI_PID"
  local report_loop="$REPORT_LOOP" report_loop_ro="${REPORT_LOOP_RO:-either}"
  local target_loop="$LOOP" boot_loop="$BOOT_LOOP"
  local report_detached=1
  BIOS_PID=""
  UEFI_PID=""
  REPORT_LOOP=""
  REPORT_LOOP_RO=""
  LOOP=""
  BOOT_LOOP=""
  stop_pid "$bios_pid"
  stop_pid "$uefi_pid"
  if [[ "$REPORT_MOUNTED" == 1 ]]; then
    if sudo umount "$REPORT_MOUNT"; then
      REPORT_MOUNTED=0
    else
      echo "ABORT: cleanup could not unmount the report image" >&2
    fi
  fi
  if [[ "$REPORT_MOUNTED" == 0 && -n "$report_loop" ]]; then
    if ! detach_owned_loop report "$report_loop" "$REPORT_RAW" "$report_loop_ro"; then
      report_detached=0
    fi
  elif [[ -n "$report_loop" ]]; then
    report_detached=0
  fi
  detach_owned_loop target "$target_loop" "$TARGET_RAW" 0
  detach_owned_loop boot "$boot_loop" "$ISO" 1
  if [[ "$SQUASH_MOUNTED" == 1 ]]; then
    if sudo umount "$SQUASH_MOUNT"; then
      SQUASH_MOUNTED=0
    else
      echo "ABORT: cleanup could not unmount the live SquashFS" >&2
    fi
  fi
  if [[ "$ISO_MOUNTED" == 1 ]]; then
    if sudo umount "$ISO_MOUNT"; then
      ISO_MOUNTED=0
    else
      echo "ABORT: cleanup could not unmount the ISO" >&2
    fi
  fi
  rm -f -- "$TARGET" "$TARGET_RAW" "$NWIPE_BIN" "$RUN_ROOT/ovmf-vars.fd"
  if [[ "$REPORT_MOUNTED" == 0 && "$report_detached" == 1 ]]; then
    rm -f -- "$REPORT_RAW"
  fi
  rm -f -- "$RUN_ROOT"/*.qmp
}

on_signal() {
  local code="$1"
  cleanup
  exit "$code"
}

trap cleanup EXIT
trap 'on_signal 129' HUP
trap 'on_signal 130' INT
trap 'on_signal 143' TERM

log() {
  printf '[qemu-verify] %s\n' "$*" | tee -a "$EVIDENCE_DIR/run.txt"
}

log "worker_os=Linux worker_arch=x86_64"
printf '%s\n' \
  'No physical hardware was tested by this gate; SATA, NVMe, USB bridges, firmware, and controllers remain field-test risks.' \
  >"$EVIDENCE_DIR/untested-physical.txt"
qemu-system-x86_64 --version >"$EVIDENCE_DIR/qemu-version.txt"
git rev-parse HEAD >"$EVIDENCE_DIR/source-commit.txt"

# Verify every consumer checksum and bind the manifest to the actual ISO bytes.
(
  cd "$ROOT/dist"
  sha256sum -c "$(basename "$ISO").sha256"
  sha256sum -c "$(basename "$MANIFEST").sha256"
) >"$EVIDENCE_DIR/checksums.txt" 2>&1
log "artifact checksums verified"
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
for forbidden in nano less iproute2 pciutils usbutils eject gcc git; do
  if dpkg-query --admindir="$SQUASH_MOUNT/var/lib/dpkg" -W -f='${db:Status-Abbrev}' "$forbidden" 2>/dev/null | grep -q '^ii'; then
    echo "forbidden package present in ISO: $forbidden" >&2
    exit 2
  fi
done
# Debian bookworm's libparted2 on amd64 has a hard dependency on dmidecode.
# Pinned nwipe needs libparted; its mandatory --quiet argument anonymizes the
# unique disk and DMI values. Keep the dependency intact and prove that its
# helpers have no set-id or non-root write permissions.
if ! dpkg-query --admindir="$SQUASH_MOUNT/var/lib/dpkg" -W \
    -f='${db:Status-Abbrev}' dmidecode 2>/dev/null | grep -q '^ii'; then
  echo "required libparted2 dependency missing from ISO: dmidecode" >&2
  exit 2
fi
for helper in dmidecode biosdecode ownership vpddecode; do
  helper_path="$SQUASH_MOUNT/usr/sbin/$helper"
  [[ -f "$helper_path" ]] || { echo "dmidecode helper missing: $helper" >&2; exit 2; }
  if find "$helper_path" \( ! -user root -o ! -group root -o -perm /6022 \) -print -quit | grep -q .; then
    echo "unsafe dmidecode helper permissions: $helper" >&2
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
log "live filesystem package and permission policy verified"
for helper in mount umount unshare sync; do
  [[ -x "$SQUASH_MOUNT/usr/bin/$helper" ]] || {
    echo "report export helper missing from ISO: $helper" >&2
    exit 2
  }
done
find "$SQUASH_MOUNT/lib/modules" -type f -name 'vfat.ko*' -print -quit | grep -q . || {
  echo "FAT32 kernel module missing from ISO" >&2
  exit 2
}
grep -q '^PrivateMounts=yes$' \
  "$SQUASH_MOUNT/etc/systemd/system/beamo-wipe-kiosk.service" || {
  echo "kiosk private mount namespace is missing" >&2
  exit 2
}
for symbol in 'def export_to_new_usb(' 'def write_report_bundle(' 'def verify_report_bundle('; do
  grep -qF "$symbol" \
    "$SQUASH_MOUNT/usr/lib/python3/dist-packages/beamo_wipe/support_export.py" || {
    echo "shipped report workflow is incomplete: $symbol" >&2
    exit 2
  }
done

# Prepare the second-USB fixture. It is a whole-disk FAT32 image backed only by
# a private regular file. A short host-namespace crash probe establishes that
# `unshare --mount --propagation private` cannot leak a child mount; the actual
# shipped export_to_new_usb -> private worker path is exercised in QEMU below.
qemu-img create -f raw "$REPORT_RAW" 64M >"$EVIDENCE_DIR/report-image.txt" 2>&1
mkfs.vfat -F 32 -n BEAMO_RPT "$REPORT_RAW" >>"$EVIDENCE_DIR/report-image.txt" 2>&1
REPORT_LOOP_RO=0
REPORT_LOOP="$(sudo losetup --find --show "$REPORT_RAW")"
prove_unmounted_loop report "$REPORT_LOOP" "$REPORT_RAW" 0
# A killed helper must not leak its mount into the kiosk/service namespace.
# unshare runs the child in a private namespace; exit 137 is intentional.
crash_code=0
# Redirect is intentionally opened by the unprivileged CI shell into its own
# mode-0700 evidence directory; only unshare/mount need sudo.
# shellcheck disable=SC2024
sudo unshare --mount --propagation private -- \
  sh -c 'mount -t vfat -o rw,nodev,nosuid,noexec,nosymfollow,umask=077 "$1" "$2" && kill -KILL $$' \
  sh "$REPORT_LOOP" "$REPORT_MOUNT" \
  >"$EVIDENCE_DIR/report-helper-crash.txt" 2>&1 || crash_code=$?
[[ "$crash_code" == 137 ]] || {
  echo "private report helper crash probe returned $crash_code, expected 137" >&2
  exit 2
}
if findmnt -rn -S "$REPORT_LOOP" | grep -q .; then
  echo "private report helper leaked a mount after crashing" >&2
  exit 2
fi
prove_unmounted_loop report "$REPORT_LOOP" "$REPORT_RAW" 0
detach_owned_loop report "$REPORT_LOOP" "$REPORT_RAW" 0
REPORT_LOOP=""
REPORT_LOOP_RO=""
log "private report helper crash left no host-namespace mount"
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
log "fake-disk confirmation and boot-exclusion checks passed"

# The only destructive process-boundary check uses a newly-created sparse raw
# file attached to a loop node whose backing file is re-proved before each run.
qemu-img create -f raw "$TARGET_RAW" 256M >"$EVIDENCE_DIR/qemu-img.txt" 2>&1
python3 - "$TARGET_RAW" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
chunk = b"\xa5" * (1024 * 1024)
with path.open("r+b") as stream:
    for _ in range(256):
        stream.write(chunk)
PY
if cmp -n 1048576 "$TARGET_RAW" /dev/zero >/dev/null 2>&1; then
  echo "disposable target prefill did not produce nonzero bytes" >&2
  exit 2
fi
LOOP="$(sudo losetup --find --show "$TARGET_RAW")"
BOOT_LOOP="$(sudo losetup --find --show --read-only "$ISO")"
[[ "$LOOP" =~ ^/dev/loop[0-9]+$ && "$BOOT_LOOP" =~ ^/dev/loop[0-9]+$ ]] || {
  echo "unexpected loop device path" >&2
  exit 2
}
prove_unmounted_loop target "$LOOP" "$TARGET_RAW" 0
prove_unmounted_loop boot "$BOOT_LOOP" "$ISO" 1
log "disposable target and boot loop identities verified"
NWIPE_LOG="$RUN_ROOT/nwipe.log"
nwipe_code=0
timeout 45 "$NWIPE_BIN" --autonuke --nogui --nowait --quiet --method=zero \
  --rounds=1 --verify=off --noblank --exclude="$BOOT_LOOP" \
  --logfile="$NWIPE_LOG" --PDFreportpath=noPDF "$LOOP" \
  >"$EVIDENCE_DIR/nwipe-boundary.txt" 2>&1 || nwipe_code=$?
[[ "$nwipe_code" == 0 ]] || { echo "nwipe boundary run failed: $nwipe_code" >&2; exit 2; }
grep -Eq 'quiet[[:space:]]*=[[:space:]]*1' "$NWIPE_LOG" || {
  echo "nwipe did not confirm anonymized logging" >&2
  exit 2
}
grep -Eq '\|[[:space:]]*Erased[[:space:]]*\||100\.00%' "$NWIPE_LOG" || {
  echo "nwipe exited without a target success marker" >&2
  exit 2
}
sync
cmp -n 268435456 "$TARGET_RAW" /dev/zero >/dev/null 2>&1 || {
  echo "nwipe reported success but disposable target is not all zero" >&2
  exit 2
}
log "pinned nwipe boundary and anonymized logging verified"

# A non-block target must never return success. Cancellation races are covered
# by the fake-device Python suite above without touching a host disk.
bad_code=0
timeout 5 "$NWIPE_BIN" --autonuke --nogui --nowait --quiet --method=zero \
  --rounds=1 --verify=off --noblank --exclude="$BOOT_LOOP" \
  --logfile="$RUN_ROOT/bad.log" --PDFreportpath=noPDF "$RUN_ROOT/not-a-device" \
  >"$EVIDENCE_DIR/nwipe-invalid-target.txt" 2>&1 || bad_code=$?
[[ "$bad_code" != 0 ]] || { echo "nwipe accepted a non-block target" >&2; exit 2; }
prove_unmounted_loop target "$LOOP" "$TARGET_RAW" 0
prove_unmounted_loop boot "$BOOT_LOOP" "$ISO" 1
detach_owned_loop target "$LOOP" "$TARGET_RAW" 0
LOOP=""
detach_owned_loop boot "$BOOT_LOOP" "$ISO" 1
BOOT_LOOP=""

# BIOS and UEFI get only the ISO and the disposable qcow2 file. The BIOS run
# drives every shipped Tk safety gate and hotplugs the file-backed FAT32 report
# disk only after DONE. UEFI still has to reach the real Tk WHAT screen.
qemu-img create -f qcow2 "$TARGET" 1G >>"$EVIDENCE_DIR/qemu-img.txt" 2>&1
qemu-io -f qcow2 -c 'write -P 0xa5 0 1M' "$TARGET" \
  >>"$EVIDENCE_DIR/qemu-img.txt" 2>&1

qmp_request() {
  local socket_path="$1" action="$2" value="${3:-}"
  python3 - "$socket_path" "$action" "$value" <<'PY'
import json
import socket
import sys

socket_path, action, value = sys.argv[1:]

with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
    client.settimeout(10)
    client.connect(socket_path)
    pending = b""

    def receive():
        global pending
        while b"\n" not in pending:
            chunk = client.recv(65536)
            if not chunk:
                raise RuntimeError("QMP closed before replying")
            pending += chunk
        line, pending = pending.split(b"\n", 1)
        return json.loads(line.strip())

    def execute(command, arguments, request_id):
        message = {"execute": command, "arguments": arguments, "id": request_id}
        client.sendall(json.dumps(message, separators=(",", ":")).encode() + b"\r\n")
        while True:
            reply = receive()
            if reply.get("id") != request_id:
                continue
            if "error" in reply:
                raise RuntimeError(f"QMP {command} failed: {reply['error']}")
            return reply.get("return")

    greeting = receive()
    if "QMP" not in greeting:
        raise RuntimeError("invalid QMP greeting")
    execute("qmp_capabilities", {}, "capabilities")
    if action == "query":
        execute("query-status", {}, "query")
    elif action == "key-tap":
        key = {"type": "qcode", "data": value}
        execute(
            "send-key",
            {"keys": [key], "hold-time": 100},
            action,
        )
    elif action in {"key-down", "key-up"}:
        key = {"type": "qcode", "data": value}
        execute(
            "input-send-event",
            {
                "events": [
                    {
                        "type": "key",
                        "data": {"down": action == "key-down", "key": key},
                    }
                ]
            },
            action,
        )
    elif action == "hotplug-report":
        execute(
            "blockdev-add",
            {
                "node-name": "beamo-report-node",
                "driver": "raw",
                "read-only": False,
                "file": {"driver": "file", "filename": value},
            },
            "blockdev-add",
        )
        execute(
            "device_add",
            {
                "driver": "usb-storage",
                "drive": "beamo-report-node",
                "id": "beamo-report-usb",
                "bus": "beamo-xhci.0",
                "removable": True,
            },
            "device_add",
        )
    else:
        raise RuntimeError(f"unsupported QMP action: {action}")
PY
}

guest_pid() {
  if [[ "$1" == bios ]]; then
    printf '%s\n' "$BIOS_PID"
  else
    printf '%s\n' "$UEFI_PID"
  fi
}

marker_count() {
  local label="$1" marker="$2" serial
  serial="$EVIDENCE_DIR/${label}-serial.txt"
  [[ -f "$serial" ]] || { printf '0\n'; return 0; }
  awk -v marker="$marker" '
    { sub(/\r$/, "", $0); if ($0 == marker) count++ }
    END { print count + 0 }
  ' "$serial"
}

report_marker_summary() {
  local label="$1" marker count
  for marker in \
    BEAMO_WIPE_KIOSK_READY \
    BEAMO_WIPE_SCREEN_WHAT \
    BEAMO_WIPE_SCREEN_OWNER \
    BEAMO_WIPE_OWNER_CHECKED \
    BEAMO_WIPE_CONFIRM_FOCUSED \
    BEAMO_WIPE_CONFIRM_UNFOCUSED \
    BEAMO_WIPE_CONFIRM_MATCHED \
    BEAMO_WIPE_SCREEN_PICK \
    BEAMO_WIPE_SCREEN_PICK_BLOCKED \
    BEAMO_WIPE_SCREEN_PICK_EMPTY \
    BEAMO_WIPE_RETURN_RESULT_OWNER \
    BEAMO_WIPE_RETURN_RESULT_PICK \
    BEAMO_WIPE_RETURN_RESULT_PICK_BLOCKED \
    BEAMO_WIPE_RETURN_RESULT_PICK_EMPTY \
    BEAMO_WIPE_RETURN_RESULT_CONFIRM \
    BEAMO_WIPE_RETURN_RESULT_METHOD \
    BEAMO_WIPE_RETURN_RESULT_LAST_CHANCE \
    BEAMO_WIPE_RETURN_RESULT_WORKING \
    BEAMO_WIPE_RETURN_RESULT_DONE \
    BEAMO_WIPE_SCREEN_CONFIRM \
    BEAMO_WIPE_SCREEN_METHOD \
    BEAMO_WIPE_SCREEN_LAST_CHANCE \
    BEAMO_WIPE_SCREEN_WORKING \
    BEAMO_WIPE_SCREEN_DONE \
    BEAMO_WIPE_REPORT_SAVING \
    BEAMO_WIPE_REPORT_SAVED \
    BEAMO_WIPE_REPORT_ERROR \
    BEAMO_WIPE_EXPORT_CONTROLLER_STARTED \
    BEAMO_WIPE_EXPORT_EVIDENCE_VERIFIED \
    BEAMO_WIPE_EXPORT_SCAN_ONE \
    BEAMO_WIPE_EXPORT_SELECT_ONE \
    BEAMO_WIPE_EXPORT_SCAN_TWO \
    BEAMO_WIPE_EXPORT_CONTROLLER_SELECTED \
    BEAMO_WIPE_EXPORT_CONTROLLER_IDENTIFIED \
    BEAMO_WIPE_EXPORT_WORKER_DECODED \
    BEAMO_WIPE_EXPORT_WORKER_SELECTED \
    BEAMO_WIPE_EXPORT_WORKER_IDENTIFIED \
    BEAMO_WIPE_EXPORT_WORKER_OPENED \
    BEAMO_WIPE_EXPORT_RW_MOUNTED \
    BEAMO_WIPE_EXPORT_BUNDLE_WRITTEN \
    BEAMO_WIPE_EXPORT_RW_UNMOUNTED \
    BEAMO_WIPE_EXPORT_RO_MOUNTED \
    BEAMO_WIPE_EXPORT_READBACK_VERIFIED \
    BEAMO_WIPE_EXPORT_RO_UNMOUNTED \
    BEAMO_WIPE_EXPORT_WORKER_FAILED \
    BEAMO_WIPE_EXPORT_FAIL_METADATA \
    BEAMO_WIPE_EXPORT_FAIL_BASELINE \
    BEAMO_WIPE_EXPORT_FAIL_REMOVABLE \
    BEAMO_WIPE_EXPORT_FAIL_COUNT \
    BEAMO_WIPE_EXPORT_FAIL_MOUNTED \
    BEAMO_WIPE_EXPORT_FAIL_LAYOUT \
    BEAMO_WIPE_EXPORT_FAIL_DEVICE_PATH \
    BEAMO_WIPE_EXPORT_FAIL_CHILDREN \
    BEAMO_WIPE_EXPORT_FAIL_AMBIGUOUS \
    BEAMO_WIPE_EXPORT_FAIL_UNSUPPORTED_LAYOUT \
    BEAMO_WIPE_EXPORT_FAIL_PARENT_LINK \
    BEAMO_WIPE_EXPORT_FAIL_VOLUME_PATH \
    BEAMO_WIPE_EXPORT_FAIL_SIZE \
    BEAMO_WIPE_EXPORT_FAIL_FAT32 \
    BEAMO_WIPE_EXPORT_FAIL_OTHER \
    BEAMO_WIPE_KEY_RETURN_RELEASED \
    BEAMO_WIPE_KEY_SPACE_RELEASED
  do
    count="$(marker_count "$label" "$marker")"
    if [[ "$count" -gt 0 ]]; then
      printf 'QEMU %s observed exact marker %s count=%s\n' \
        "$label" "$marker" "$count" >&2
    fi
  done
}

wait_for_qmp() {
  local label="$1" qmp_socket="$2" pid
  pid="$(guest_pid "$label")"
  for _attempt in $(seq 1 100); do
    if [[ -S "$qmp_socket" ]] && qmp_request "$qmp_socket" query >/dev/null 2>&1; then
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "QEMU $label exited before QMP became ready" >&2
      wait "$pid" || true
      return 1
    fi
    sleep 0.1
  done
  echo "QEMU $label QMP socket did not become ready" >&2
  return 1
}

wait_for_marker() {
  local label="$1" marker="$2" limit="$3" pid
  pid="$(guest_pid "$label")"
  for _attempt in $(seq 1 "$limit"); do
    if [[ "$(marker_count "$label" "$marker")" -gt 0 ]]; then
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "QEMU $label exited before marker $marker" >&2
      report_marker_summary "$label"
      wait "$pid" || true
      return 1
    fi
    sleep 1
  done
  # The marker can arrive during the final bounded sleep. Recheck before
  # diagnosing a timeout so the gate cannot report success evidence as absent.
  if [[ "$(marker_count "$label" "$marker")" -gt 0 ]]; then
    return 0
  fi
  report_marker_summary "$label"
  echo "QEMU $label never emitted marker $marker" >&2
  return 1
}

wait_for_new_marker() {
  local label="$1" marker="$2" prior="$3" limit="$4" pid
  pid="$(guest_pid "$label")"
  for _attempt in $(seq 1 "$limit"); do
    if [[ "$(marker_count "$label" "$marker")" -gt "$prior" ]]; then
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "QEMU $label exited before new marker $marker" >&2
      report_marker_summary "$label"
      wait "$pid" || true
      return 1
    fi
    sleep 1
  done
  if [[ "$(marker_count "$label" "$marker")" -gt "$prior" ]]; then
    return 0
  fi
  report_marker_summary "$label"
  echo "QEMU $label never emitted a new exact marker $marker" >&2
  return 1
}

send_key() {
  local qmp_socket="$1" key="$2"
  qmp_request "$qmp_socket" key-tap "$key"
  sleep 0.4
}

send_key_for_marker() {
  local label="$1" qmp_socket="$2" key="$3" marker="$4" limit="$5"
  local prior release_marker="" release_prior=0
  prior="$(marker_count "$label" "$marker")"
  case "$key" in
    ret) release_marker=BEAMO_WIPE_KEY_RETURN_RELEASED ;;
    spc) release_marker=BEAMO_WIPE_KEY_SPACE_RELEASED ;;
  esac
  if [[ -n "$release_marker" ]]; then
    release_prior="$(marker_count "$label" "$release_marker")"
    qmp_request "$qmp_socket" key-down "$key"
    if ! wait_for_new_marker "$label" "$marker" "$prior" "$limit"; then
      qmp_request "$qmp_socket" key-up "$key" || true
      return 1
    fi
    qmp_request "$qmp_socket" key-up "$key"
    wait_for_new_marker "$label" "$release_marker" "$release_prior" 20
    return
  fi
  qmp_request "$qmp_socket" key-tap "$key"
  wait_for_new_marker "$label" "$marker" "$prior" "$limit"
}

type_token_for_marker() {
  local label="$1" qmp_socket="$2" token="$3" marker="$4" limit="$5" index
  if [[ ! "$token" =~ ^[0-9]+$ ]]; then
    echo "ABORT: QEMU confirmation token is not numeric" >&2
    return 1
  fi
  for ((index = 0; index < ${#token} - 1; index++)); do
    send_key "$qmp_socket" "${token:index:1}"
  done
  send_key_for_marker \
    "$label" "$qmp_socket" "${token: -1}" "$marker" "$limit"
}

wait_for_report_saved() {
  local label="$1" pid
  pid="$(guest_pid "$label")"
  for _attempt in $(seq 1 120); do
    if [[ "$(marker_count "$label" BEAMO_WIPE_REPORT_SAVED)" -gt 0 ]]; then
      return 0
    fi
    if [[ "$(marker_count "$label" BEAMO_WIPE_REPORT_ERROR)" -gt 0 ]]; then
      report_marker_summary "$label"
      echo "shipped report workflow emitted BEAMO_WIPE_REPORT_ERROR" >&2
      return 1
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "QEMU $label exited before BEAMO_WIPE_REPORT_SAVED" >&2
      report_marker_summary "$label"
      wait "$pid" || true
      return 1
    fi
    sleep 1
  done
  if [[ "$(marker_count "$label" BEAMO_WIPE_REPORT_SAVED)" -gt 0 ]]; then
    return 0
  fi
  if [[ "$(marker_count "$label" BEAMO_WIPE_REPORT_ERROR)" -gt 0 ]]; then
    report_marker_summary "$label"
    echo "shipped report workflow emitted BEAMO_WIPE_REPORT_ERROR" >&2
    return 1
  fi
  report_marker_summary "$label"
  echo "shipped report workflow never emitted BEAMO_WIPE_REPORT_SAVED" >&2
  return 1
}

drive_report_export() {
  local label="$1" qmp_socket="$2"
  send_key_for_marker "$label" "$qmp_socket" ret BEAMO_WIPE_SCREEN_OWNER 20
  send_key_for_marker "$label" "$qmp_socket" spc BEAMO_WIPE_OWNER_CHECKED 20
  send_key_for_marker "$label" "$qmp_socket" ret BEAMO_WIPE_SCREEN_PICK 20
  send_key_for_marker "$label" "$qmp_socket" down BEAMO_WIPE_SCREEN_PICK 20
  send_key_for_marker "$label" "$qmp_socket" ret BEAMO_WIPE_SCREEN_CONFIRM 20
  wait_for_marker "$label" BEAMO_WIPE_CONFIRM_FOCUSED 20
  type_token_for_marker "$label" "$qmp_socket" "$QEMU_TARGET_SERIAL" BEAMO_WIPE_CONFIRM_MATCHED 20
  send_key_for_marker "$label" "$qmp_socket" ret BEAMO_WIPE_SCREEN_METHOD 20
  send_key_for_marker "$label" "$qmp_socket" 3 BEAMO_WIPE_SCREEN_METHOD 20
  send_key_for_marker "$label" "$qmp_socket" ret BEAMO_WIPE_SCREEN_LAST_CHANCE 20
  sleep 6
  send_key_for_marker "$label" "$qmp_socket" ret BEAMO_WIPE_SCREEN_WORKING 20
  wait_for_marker "$label" BEAMO_WIPE_SCREEN_DONE 300

  # device_add is deliberately after DONE: the export selector accepts only a
  # newly inserted USB that was absent from the wipe's protected baseline.
  qmp_request "$qmp_socket" hotplug-report "$REPORT_RAW"
  sleep 5
  send_key "$qmp_socket" tab
  send_key_for_marker "$label" "$qmp_socket" spc BEAMO_WIPE_REPORT_SAVING 20
  wait_for_report_saved "$label"
}

boot_probe() {
  local label="$1" exercise_export="$2" qmp_socket pid
  shift 2
  qmp_socket="$RUN_ROOT/${label}.qmp"
  rm -f -- "$qmp_socket"
  : >"$EVIDENCE_DIR/${label}-serial.txt"
  qemu-system-x86_64 -machine accel=kvm:tcg -m 1024 -nic none \
    "$@" -cdrom "$ISO" \
    -blockdev "driver=file,node-name=beamo-target-file,filename=$TARGET" \
    -blockdev "driver=qcow2,node-name=beamo-target,file=beamo-target-file" \
    -device "virtio-blk-pci,drive=beamo-target,serial=$QEMU_TARGET_SERIAL" \
    -device qemu-xhci,id=beamo-xhci \
    -boot order=d -display none -serial "file:$EVIDENCE_DIR/${label}-serial.txt" \
    -qmp "unix:$qmp_socket,server=on,wait=off" \
    -no-reboot >"$EVIDENCE_DIR/${label}-qemu.txt" 2>&1 &
  pid=$!
  if [[ "$label" == bios ]]; then BIOS_PID="$pid"; else UEFI_PID="$pid"; fi
  wait_for_qmp "$label" "$qmp_socket"
  # The rendered Tk screen is the authoritative kiosk-ready boundary.  The
  # supervisor's earlier serial marker is best-effort and deliberately
  # suppresses device/write failures even when the shipped UI starts.
  wait_for_marker "$label" BEAMO_WIPE_SCREEN_WHAT "$BOOT_WAIT_SECONDS" || {
    echo "QEMU $label never rendered the shipped Tk WHAT screen" >&2
    return 1
  }
  if [[ "$exercise_export" == yes ]]; then
    drive_report_export "$label" "$qmp_socket"
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "QEMU $label exited immediately after its final marker" >&2
    wait "$pid" || true
    return 1
  fi
  stop_pid "$pid"
  if [[ "$label" == bios ]]; then BIOS_PID=""; else UEFI_PID=""; fi
  if [[ "$exercise_export" == yes ]]; then
    log "$label boot completed the shipped Wizard report export"
  else
    log "$label boot reached the shipped Tk WHAT screen"
  fi
}

boot_probe bios yes

# The GUI path must have changed the exact nonzero region seeded above. QEMU is
# stopped, so qemu-io has exclusive access to the file-backed target.
qemu-io -f qcow2 -c 'read -P 0x00 0 1M' "$TARGET" \
  >"$EVIDENCE_DIR/guest-target-readback.txt" 2>&1 || {
  echo "shipped Wizard reported success but did not zero the guest target" >&2
  exit 2
}
log "shipped Wizard zeroed the guest target prefill"

# QEMU is gone before the host opens the report image. Re-prove a read-only
# loop, require a clean FAT, mount read-only, and independently validate every
# completion-manifest hash written by the real guest worker.
REPORT_LOOP_RO=1
REPORT_LOOP="$(sudo losetup --find --show --read-only "$REPORT_RAW")"
prove_unmounted_loop report "$REPORT_LOOP" "$REPORT_RAW" 1
# Redirect is opened by the unprivileged shell into its mode-0700 evidence dir.
# shellcheck disable=SC2024
sudo fsck.vfat -n "$REPORT_LOOP" >"$EVIDENCE_DIR/report-fsck.txt" 2>&1
prove_unmounted_loop report "$REPORT_LOOP" "$REPORT_RAW" 1
sudo mount -t vfat -o ro,nodev,nosuid,noexec,nosymfollow,umask=077 \
  "$REPORT_LOOP" "$REPORT_MOUNT"
REPORT_MOUNTED=1
findmnt -rn -M "$REPORT_MOUNT" -S "$REPORT_LOOP" -t vfat \
  -o SOURCE,FSTYPE,OPTIONS,TARGET >"$EVIDENCE_DIR/report-mount.txt"
# Redirect is opened by the unprivileged shell into its mode-0700 evidence dir.
# shellcheck disable=SC2024
sudo python3 -sP - "$REPORT_MOUNT" >"$EVIDENCE_DIR/report-bundle.txt" <<'PY'
import hashlib
import json
import pathlib
import re
import stat
import sys

mountpoint = pathlib.Path(sys.argv[1])
reports = mountpoint / "BEAMO-WIPE-REPORTS"
top = sorted(path.name for path in mountpoint.iterdir())
if top != ["BEAMO-WIPE-REPORTS"]:
    raise SystemExit(f"unexpected report filesystem root: {top!r}")
sessions = sorted(reports.iterdir())
if (
    len(sessions) != 1
    or not sessions[0].is_dir()
    or not re.fullmatch(r"report-[0-9a-f]{24}", sessions[0].name)
):
    raise SystemExit("expected exactly one valid report session")
session = sessions[0]
actual = {}
for path in session.iterdir():
    opened = path.lstat()
    if not stat.S_ISREG(opened.st_mode):
        raise SystemExit(f"non-regular report entry: {path.name}")
    actual[path.name] = path.read_bytes()
if "COMPLETE" not in actual or "result.json" not in actual or "result.json.sha256" not in actual:
    raise SystemExit("report completion files are missing")
complete = json.loads(actual["COMPLETE"].decode("utf-8"))
expected_complete_keys = {
    "files",
    "log_status",
    "manifest_scope",
    "safe_to_remove",
    "schema_version",
}
if set(complete) != expected_complete_keys:
    raise SystemExit("unexpected report completion schema")
if (
    complete["manifest_scope"] != "content_only"
    or complete["safe_to_remove"] is not False
    or type(complete["schema_version"]) is not int
    or complete["schema_version"] != 1
    or complete["log_status"] not in {"complete", "tail", "unavailable"}
):
    raise SystemExit("invalid report completion marker")
manifest = complete.get("files")
if not isinstance(manifest, dict) or set(actual) != set(manifest) | {"COMPLETE"}:
    raise SystemExit("completion manifest does not match report files")
for name, expected in manifest.items():
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise SystemExit(f"invalid digest for {name}")
    if hashlib.sha256(actual[name]).hexdigest() != expected:
        raise SystemExit(f"report digest mismatch: {name}")
result_digest = hashlib.sha256(actual["result.json"]).hexdigest()
if actual["result.json.sha256"] != f"{result_digest}  result.json\n".encode("ascii"):
    raise SystemExit("result.json sidecar mismatch")
result = json.loads(actual["result.json"].decode("utf-8"))
if result.get("outcome") not in {"completed", "verified"}:
    raise SystemExit("guest report is not a successful terminal wipe")
print(f"session={session.name}")
print(f"outcome={result['outcome']}")
print(f"files={','.join(sorted(actual))}")
PY
sudo umount "$REPORT_MOUNT"
REPORT_MOUNTED=0
if findmnt -rn -M "$REPORT_MOUNT" | grep -q .; then
  echo "report USB remained mounted after host verification" >&2
  exit 2
fi
prove_unmounted_loop report "$REPORT_LOOP" "$REPORT_RAW" 1
detach_owned_loop report "$REPORT_LOOP" "$REPORT_RAW" 1
REPORT_LOOP=""
REPORT_LOOP_RO=""
log "guest report passed clean-FAT, completion, checksum, read-only, and unmount checks"

OVMF_CODE=""
for candidate in /usr/share/OVMF/OVMF_CODE_4M.fd /usr/share/OVMF/OVMF_CODE.fd; do
  if [[ -f "$candidate" ]]; then OVMF_CODE="$candidate"; break; fi
done
[[ -n "$OVMF_CODE" ]] || { echo "OVMF firmware missing" >&2; exit 2; }
OVMF_VARS="${OVMF_CODE/CODE/VARS}"
if [[ -f "$OVMF_VARS" ]]; then
  cp "$OVMF_VARS" "$RUN_ROOT/ovmf-vars.fd"
  boot_probe uefi no \
    -drive "if=pflash,format=raw,readonly=on,file=$OVMF_CODE" \
    -drive "if=pflash,format=raw,file=$RUN_ROOT/ovmf-vars.fd"
else
  boot_probe uefi no -bios "$OVMF_CODE"
fi

printf 'iso_sha256=%s\nnwipe_sha256=%s\nbios=pass\nuefi=pass\nreport_export=pass\n' \
  "$(sha256sum "$ISO" | awk '{print $1}')" "$shipped_sha" \
  >"$EVIDENCE_DIR/summary.txt"
log "PASS; evidence=$EVIDENCE_DIR"
