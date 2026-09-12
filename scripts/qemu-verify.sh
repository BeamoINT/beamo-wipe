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

VERSION="${BEAMO_WIPE_VERSION:-0.2.7}"
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "ABORT: invalid BEAMO_WIPE_VERSION" >&2
  exit 2
fi
ISO="$ROOT/dist/beamo-wipe-${VERSION}-amd64.iso"
USB_IMAGE="$ROOT/dist/beamo-wipe-${VERSION}-amd64.img"
MANIFEST="$ROOT/dist/beamo-wipe-${VERSION}-amd64.manifest.json"
[[ -f "$ISO" && -f "$MANIFEST" ]] || {
  echo "ABORT: exact versioned ISO and manifest are required" >&2
  exit 2
}

RUN_ROOT="$(mktemp -d /tmp/beamo-wipe-qemu.XXXXXX)"
EVIDENCE_DIR="$RUN_ROOT/evidence"
TARGET="$RUN_ROOT/target.qcow2"
TARGET_RAW="$RUN_ROOT/target.raw"
# Small disks still display as 1 GB (size_gb_label floors at 1). Unique
# serials therefore remain the confirmation tokens against the ISO, which
# also rounds to 1 GB. Method flags stay the production mapping; only the
# fixture size is bounded.
QEMU_TARGET_SERIAL="0001"
HOST_METHOD_BYTES=67108864
# case|key|nwipe_method|verify|outcome|host_timeout_s|guest_done_timeout_s|serial
METHOD_CASES=$(cat <<'EOF'
everyday|1|prng|last|verified|90|180|0001
extra|2|dodshort|last|verified|180|300|0002
quick_zero|3|zero|off|completed|60|180|0003
EOF
)
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
  local report_detached=1 target_detached=1
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
  detach_owned_loop target "$target_loop" "$TARGET_RAW" 0 || target_detached=0
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
  if [[ "$target_detached" == 1 ]]; then
    rm -f -- "$TARGET" "$TARGET_RAW" "$NWIPE_BIN" "$RUN_ROOT/ovmf-vars.fd" \
      "$RUN_ROOT"/target-*.qcow2 "$RUN_ROOT"/host-*.raw "$RUN_ROOT"/guest-*-readback.raw
  fi
  if [[ "$REPORT_MOUNTED" == 0 && "$report_detached" == 1 ]]; then
    rm -f -- "$REPORT_RAW" "$RUN_ROOT"/report-*.raw
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
  sha256sum -c "$(basename "$USB_IMAGE").sha256"
  sha256sum -c "$(basename "$MANIFEST").sha256"
) >"$EVIDENCE_DIR/checksums.txt" 2>&1
log "artifact checksums verified"
PYTHONPATH="$ROOT/src" python3 -c \
  'import pathlib,sys; from beamo_wipe.release_manifest import verify_build_manifest; verify_build_manifest(pathlib.Path(sys.argv[1]))' \
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
PYTHONPATH="$ROOT/src" python3 -m beamo_wipe.ci_evidence inventory --image-root "$SQUASH_MOUNT"
SHIPPED_NWIPE="$SQUASH_MOUNT/usr/lib/beamo-wipe/nwipe"
[[ -x "$SHIPPED_NWIPE" ]] || { echo "pinned nwipe missing from ISO" >&2; exit 2; }
"$SHIPPED_NWIPE" -V >"$EVIDENCE_DIR/nwipe-version.txt" 2>&1
grep -qiE '^nwipe version 0\.42([[:space:]]|$)' "$EVIDENCE_DIR/nwipe-version.txt" || {
  echo "ISO nwipe version is not the exact pin" >&2
  exit 2
}

# Boot menus carry Beamo Wipe identity and never imply booting erases.
# BIOS boots isolinux; UEFI boots grub. Both entries must exist with the
# branded labels, the troubleshooting entry keeps the failsafe kernel line,
# and reaching the wizard must not be presented as starting an erase.
BIOS_LIVE="$ISO_MOUNT/isolinux/live.cfg"
EFI_GRUB="$ISO_MOUNT/boot/grub/grub.cfg"
[[ -f "$BIOS_LIVE" ]] || { echo "ISO BIOS menu isolinux/live.cfg missing" >&2; exit 2; }
[[ -f "$EFI_GRUB" ]] || { echo "ISO UEFI menu boot/grub/grub.cfg missing" >&2; exit 2; }
if grep -Eiq '^[[:space:]]*menu[[:space:]]+help[[:space:]]' "$BIOS_LIVE"; then
  echo "ISO BIOS boot entry was replaced with a help-file action" >&2; exit 2
fi
grep -q "Beamo Wipe: start the erase guide" "$BIOS_LIVE" || {
  echo "ISO BIOS menu lost the branded normal entry" >&2; exit 2; }
# Syslinux's caret marks the menu hotkey and is not displayed to the owner.
grep -Eq 'Beamo Wipe: \^?troubleshoot startup' "$BIOS_LIVE" || {
  echo "ISO BIOS menu lost the troubleshooting entry" >&2; exit 2; }
grep -q "Nothing is erased until you pick a disk" "$BIOS_LIVE" || {
  echo "ISO BIOS menu lost the no-erase statement" >&2; exit 2; }
grep -q "Beamo Wipe: start the erase guide (nothing is erased yet)" "$EFI_GRUB" || {
  echo "ISO UEFI menu lost the branded normal entry" >&2; exit 2; }
grep -q "Beamo Wipe: troubleshoot startup (nothing is erased yet)" "$EFI_GRUB" || {
  echo "ISO UEFI menu lost the troubleshooting entry" >&2; exit 2; }
if grep -q "Live system (" "$BIOS_LIVE" "$EFI_GRUB"; then
  echo "ISO boot menu still shows the stock Debian entry" >&2; exit 2
fi
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
# Import the actual shipped GTK runtime from the read-only image. No device
# nodes or host filesystem are mounted into this dependency check.
{ sudo chroot "$SQUASH_MOUNT" /usr/bin/python3 -B -sP -c '
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
from beamo_wipe.ui.accessible_wizard import AccessibleWizard
assert Gtk.get_major_version() == 3
print("Shipped GTK 3 and accessible wizard import passed")
'; } >"$EVIDENCE_DIR/accessible-runtime.txt"
for helper in mount umount unshare sync orca pulseaudio dbus-run-session; do
  [[ -x "$SQUASH_MOUNT/usr/bin/$helper" ]] || {
    echo "required runtime helper missing from ISO: $helper" >&2
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
LOGIND_POLICY="$SQUASH_MOUNT/etc/systemd/logind.conf.d/beamo-kiosk.conf"
SLEEP_POLICY="$SQUASH_MOUNT/etc/systemd/sleep.conf.d/beamo-kiosk.conf"
XORG_POLICY="$SQUASH_MOUNT/etc/X11/xorg.conf.d/10-beamo.conf"
[[ -f "$LOGIND_POLICY" && -f "$SLEEP_POLICY" && -f "$XORG_POLICY" ]] || {
  echo "live-session power policy missing from ISO" >&2
  exit 2
}
grep -q '^HandleLidSwitch=ignore$' "$LOGIND_POLICY" || {
  echo "logind lid policy is not ignore" >&2
  exit 2
}
grep -q '^HandlePowerKey=ignore$' "$LOGIND_POLICY" || {
  echo "logind power-key policy is not ignore" >&2
  exit 2
}
grep -q '^IdleAction=ignore$' "$LOGIND_POLICY" || {
  echo "logind idle action is not ignore" >&2
  exit 2
}
grep -q '^AllowSuspend=no$' "$SLEEP_POLICY" || {
  echo "OS suspend is not refused" >&2
  exit 2
}
grep -q 'Option "BlankTime" "10"' "$XORG_POLICY" || {
  echo "display blanking policy missing" >&2
  exit 2
}
grep -q 'Option "SuspendTime" "0"' "$XORG_POLICY" || {
  echo "Xorg suspend time is not display-idle zero" >&2
  exit 2
}
for unit in sleep.target suspend.target hibernate.target hybrid-sleep.target \
  suspend-then-hibernate.target
do
  [[ "$(readlink "$SQUASH_MOUNT/etc/systemd/system/${unit}" 2>/dev/null || true)" == /dev/null ]] || {
    echo "sleep unit is not masked: $unit" >&2
    exit 2
  }
done
if grep -R -l 'xfce4-power-manager\|gnome-settings-daemon-power\|power-profiles-daemon' \
  "$SQUASH_MOUNT/var/lib/dpkg/status" 2>/dev/null | grep -q .; then
  echo "desktop power manager present in ISO" >&2
  exit 2
fi
log "live-session power policy present in squashfs"
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

# Destructive process-boundary checks use newly-created sparse raw files
# attached to loop nodes whose backing files are re-proved before each run.
# Each production method gets its own 64 MiB fixture. Timeouts bound the
# fixture, not the method definition.
prefill_raw() {
  local path="$1"
  python3 - "$path" "$HOST_METHOD_BYTES" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
total = int(sys.argv[2])
chunk = b"\xa5" * (1024 * 1024)
written = 0
with path.open("r+b") as stream:
    while written < total:
        n = min(len(chunk), total - written)
        stream.write(chunk[:n])
        written += n
PY
  if cmp -n 1048576 "$path" /dev/zero >/dev/null 2>&1; then
    echo "disposable target prefill did not produce nonzero bytes" >&2
    return 1
  fi
}

run_host_method_boundary() {
  local case="$1" nwipe_method="$2" verify="$3" timeout_s="$4"
  local raw="$RUN_ROOT/host-${case}.raw"
  local logf="$EVIDENCE_DIR/host-${case}.log"
  local out="$EVIDENCE_DIR/host-${case}-nwipe.txt"
  qemu-img create -f raw "$raw" "${HOST_METHOD_BYTES}" >>"$EVIDENCE_DIR/qemu-img.txt" 2>&1
  prefill_raw "$raw"
  # Rebind TARGET_RAW so cleanup detaches this method's loop, not a stale path.
  TARGET_RAW="$raw"
  LOOP="$(sudo losetup --find --show "$raw")"
  [[ "$LOOP" =~ ^/dev/loop[0-9]+$ ]] || {
    echo "unexpected loop device path" >&2
    return 1
  }
  prove_unmounted_loop target "$LOOP" "$raw" 0
  prove_unmounted_loop boot "$BOOT_LOOP" "$ISO" 1
  log "host method $case loop identities verified"
  local nwipe_code=0
  timeout "$timeout_s" "$NWIPE_BIN" --autonuke --nogui --nowait --quiet \
    --method="$nwipe_method" --rounds=1 --verify="$verify" --noblank \
    --exclude="$BOOT_LOOP" --logfile="$logf" --PDFreportpath=noPDF "$LOOP" \
    >"$out" 2>&1 || nwipe_code=$?
  [[ "$nwipe_code" == 0 ]] || {
    echo "nwipe $case boundary run failed: $nwipe_code" >&2
    return 1
  }
  grep -Eq 'quiet[[:space:]]*=[[:space:]]*1' "$logf" || {
    echo "nwipe $case did not confirm anonymized logging" >&2
    return 1
  }
  if ! python3 - "$logf" "$nwipe_method" "$verify" <<'PY'
import pathlib
import re
import sys

log = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
method, verify = sys.argv[2], sys.argv[3]
labels = {"zero": "Fill With Zeros", "prng": "PRNG Stream", "dodshort": "DoD Short"}
method_at = re.search(rf"method\s*=\s*{re.escape(labels[method])}\s*$", log, re.M)
verify_at = re.search(rf"verify\s*=\s*{0 if verify == 'off' else 1}\s*\({'off' if verify == 'off' else 'last pass'}\)", log)
rounds_at = re.search(r"rounds\s*=\s*1(?:\s|$)", log)
success_at = re.search(r"\|\s*Erased\s*\|", log)
if not (method_at and verify_at and rounds_at and success_at):
    raise SystemExit("nwipe log is missing configured method, verify, rounds, or success")
if not all(m.start() < success_at.start() for m in (method_at, verify_at, rounds_at)):
    raise SystemExit("nwipe success marker appeared before method/verify/rounds configuration")
passes = 3 if method == "dodshort" else 1
cursor = 0
for number in range(1, passes + 1):
    for phase in ("Starting", "Finished"):
        marker = f"{phase} pass {number}/{passes}, round 1/1, on "
        index = log.find(marker, cursor)
        if index < 0 or index > success_at.start():
            raise SystemExit("nwipe overwrite phase missing or out of order")
        cursor = index + len(marker)
verification = list(re.finditer(r"Verifying pass \d+ of \d+, round \d+ of \d+, on ", log))
if verify == "last":
    start = log.find(f"Verifying pass {passes} of {passes}, round 1 of 1, on ")
    finish = log.find(f"Verified pass {passes} of {passes}, round 1 of 1, on ", start)
    write_start = log.find(f"Starting pass {passes}/{passes}, round 1/1, on ")
    write_finish = log.find(f"Finished pass {passes}/{passes}, round 1/1, on ")
    if len(verification) != 1 or not (write_start < start < finish < write_finish < success_at.start()):
        raise SystemExit("nwipe last-pass verification missing or out of order")
elif verification:
    raise SystemExit("nwipe unexpectedly verified an unverified method")

PY
  then
    echo "nwipe $case operation phases are not in the expected order" >&2
    return 1
  fi
  sync
  if [[ "$nwipe_method" == zero ]]; then
    cmp -n "$HOST_METHOD_BYTES" "$raw" /dev/zero >/dev/null 2>&1 || {
      echo "nwipe $case reported success but disposable target is not all zero" >&2
      return 1
    }
  else
    if ! python3 - "$raw" <<'PY'
import pathlib
import sys
blob = pathlib.Path(sys.argv[1]).read_bytes()[:1048576]
if blob == b"\xa5" * len(blob):
    raise SystemExit(1)
PY
    then
      echo "nwipe $case left the 0xa5 prefill unchanged" >&2
      return 1
    fi
  fi
  prove_unmounted_loop target "$LOOP" "$raw" 0
  detach_owned_loop target "$LOOP" "$raw" 0
  LOOP=""
  TARGET_RAW="$RUN_ROOT/target.raw"
  log "pinned nwipe $case boundary verified"
}

BOOT_LOOP="$(sudo losetup --find --show --read-only "$ISO")"
[[ "$BOOT_LOOP" =~ ^/dev/loop[0-9]+$ ]] || {
  echo "unexpected boot loop device path" >&2
  exit 2
}
prove_unmounted_loop boot "$BOOT_LOOP" "$ISO" 1
while IFS='|' read -r case key nwipe_method verify outcome host_timeout guest_timeout serial; do
  [[ -n "$case" ]] || continue
  run_host_method_boundary "$case" "$nwipe_method" "$verify" "$host_timeout"
  run_host_method_boundary "${case}-repeat" "$nwipe_method" "$verify" "$host_timeout"
done <<<"$METHOD_CASES"
log "pinned nwipe boundary and anonymized logging verified for all methods"

# A non-block target must never return success. Cancellation races are covered
# by the fake-device Python suite above without touching a host disk.
bad_code=0
timeout 5 "$NWIPE_BIN" --autonuke --nogui --nowait --quiet --method=zero \
  --rounds=1 --verify=off --noblank --exclude="$BOOT_LOOP" \
  --logfile="$RUN_ROOT/bad.log" --PDFreportpath=noPDF "$RUN_ROOT/not-a-device" \
  >"$EVIDENCE_DIR/nwipe-invalid-target.txt" 2>&1 || bad_code=$?
[[ "$bad_code" != 0 ]] || { echo "nwipe accepted a non-block target" >&2; exit 2; }
prove_unmounted_loop boot "$BOOT_LOOP" "$ISO" 1
detach_owned_loop boot "$BOOT_LOOP" "$ISO" 1
BOOT_LOOP=""

# BIOS and UEFI get only the ISO and disposable qcow2 files. Each production
# method gets an isolated BIOS journey, its own 64 MiB target, and its own
# FAT32 report image. UEFI still has to reach the real Tk WHAT screen.
make_guest_target() {
  local img="$1"
  qemu-img create -f qcow2 "$img" "${HOST_METHOD_BYTES}" >>"$EVIDENCE_DIR/qemu-img.txt" 2>&1
  qemu-io -f qcow2 -c "write -P 0xa5 0 $HOST_METHOD_BYTES" "$img" >>"$EVIDENCE_DIR/qemu-img.txt" 2>&1
}

make_report_image() {
  local img="$1"
  qemu-img create -f raw "$img" 64M >>"$EVIDENCE_DIR/qemu-img.txt" 2>&1
  mkfs.vfat -F 32 -n BEAMO_RPT "$img" >>"$EVIDENCE_DIR/qemu-img.txt" 2>&1
}

assert_guest_overwrite() {
  local case="$1" nwipe_method="$2" img="$3"
  local raw="$RUN_ROOT/guest-${case}-readback.raw" code=0
  # A pattern mismatch and an I/O failure share qemu-io's nonzero status.
  # Require successful conversion before inspecting the complete fixture.
  qemu-img convert -f qcow2 -O raw "$img" "$raw" \
    >"$EVIDENCE_DIR/guest-${case}-readback.txt" 2>&1 || return 1
  python3 - "$raw" "$nwipe_method" "$HOST_METHOD_BYTES" \
    >>"$EVIDENCE_DIR/guest-${case}-readback.txt" <<'PY' || code=$?
import hashlib
import pathlib
import sys

path, method, expected_size = pathlib.Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
if path.stat().st_size != expected_size:
    raise SystemExit("guest readback size mismatch")
digest = hashlib.sha256()
with path.open("rb") as stream:
    while chunk := stream.read(1024 * 1024):
        if method == "zero":
            if chunk != bytes(len(chunk)):
                raise SystemExit("guest target was not completely zeroed")
        elif b"\xa5" * 512 in chunk:
            raise SystemExit("guest target retained an untouched prefill sector")
        digest.update(chunk)
print(f"verified_bytes={expected_size}")
print(f"readback_sha256={digest.hexdigest()}")
PY
  rm -f -- "$raw"
  [[ "$code" == 0 ]] || return "$code"
  log "shipped Wizard $case overwrote the complete guest target prefill"
}

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
  if [[ "$1" == bios* ]]; then
    printf '%s\n' "$BIOS_PID"
  else
    printf '%s\n' "$UEFI_PID"
  fi
}

record_qemu_cmdline() {
  local out="$1"
  shift
  # Join argv with spaces so multi-token flags such as `-nic none` remain
  # greppable. Per-line printing would split them across lines and the
  # `-nic none` assertion below would never match.
  printf '%s ' "$@" >"$out"
  printf '\n' >>"$out"
  local arg previous="" network_disabled=0
  for arg in "$@"; do
    if [[ "$arg" == *"/dev/"* ]]; then
      echo "ABORT: QEMU command mentions a host block device" >&2
      return 1
    fi
    if [[ "$previous" == -nic && "$arg" == none ]]; then network_disabled=1; fi
    previous="$arg"
  done
  [[ "$network_disabled" == 1 ]] || {
    echo "ABORT: QEMU command is missing -nic none" >&2
    return 1
  }
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
    BEAMO_WIPE_STAGE_STARTING \
    BEAMO_WIPE_STAGE_BOOT_USB \
    BEAMO_WIPE_STAGE_FINDING \
    BEAMO_WIPE_STAGE_DONE \
    BEAMO_WIPE_STAGE_FAILED \
    BEAMO_WIPE_STAGE_STALLED \
    BEAMO_WIPE_SCREEN_SPLASH \
    BEAMO_WIPE_SCREEN_KEYBOARD \
    BEAMO_WIPE_SCREEN_WHAT \
    BEAMO_WIPE_SCREEN_OWNER \
    BEAMO_WIPE_OWNER_CHECKED \
    BEAMO_WIPE_CONFIRM_FOCUSED \
    BEAMO_WIPE_CONFIRM_UNFOCUSED \
    BEAMO_WIPE_CONFIRM_MATCHED \
    BEAMO_WIPE_SCREEN_PICK \
    BEAMO_WIPE_SCREEN_PICK_BLOCKED \
    BEAMO_WIPE_SCREEN_PICK_EMPTY \
    BEAMO_WIPE_DISCOVERY_BOOT_UNIDENTIFIED \
    BEAMO_WIPE_DISCOVERY_DEPENDENCY_MISSING \
    BEAMO_WIPE_DISCOVERY_DISCOVERY_COMMAND_FAILED \
    BEAMO_WIPE_DISCOVERY_DISCOVERY_FAILED \
    BEAMO_WIPE_DISCOVERY_DISCOVERY_INVALID \
    BEAMO_WIPE_DISCOVERY_DISCOVERY_TIMEOUT \
    BEAMO_WIPE_DISCOVERY_ENGINE_START_FAILED \
    BEAMO_WIPE_DISCOVERY_GRAPHICAL_UNAVAILABLE \
    BEAMO_WIPE_DISCOVERY_RECOVERY_INDETERMINATE \
    BEAMO_WIPE_DISCOVERY_IDENTITY_REJECTED \
    BEAMO_WIPE_DISCOVERY_IO_FAILED \
    BEAMO_WIPE_DISCOVERY_NO_ELIGIBLE_DISKS \
    BEAMO_WIPE_DISCOVERY_PERMISSION_DENIED \
    BEAMO_WIPE_DISCOVERY_PREFLIGHT_REJECTED \
    BEAMO_WIPE_DISCOVERY_REDISCOVERY_FAILED \
    BEAMO_WIPE_DISCOVERY_REFRESH_FAILED \
    BEAMO_WIPE_DISCOVERY_STARTUP_REFUSED \
    BEAMO_WIPE_DISCOVERY_UNEXPECTED_STARTUP_FAILURE \
    BEAMO_WIPE_BOOT_FINDMNT_MULTIROW \
    BEAMO_WIPE_BOOT_SOURCE_UNRESOLVED \
    BEAMO_WIPE_BOOT_SOURCE_LOOP \
    BEAMO_WIPE_BOOT_SOURCE_TYPED \
    BEAMO_WIPE_BOOT_SOURCE_DEVICE \
    BEAMO_WIPE_BOOT_SOURCE_OVERLAY \
    BEAMO_WIPE_BOOT_SOURCE_OTHER \
    BEAMO_WIPE_BOOT_SOURCE_CONFLICT \
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
      printf 'QEMU %s reached marker %s\n' "$label" "$marker" >&2
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
    printf 'QEMU %s reached marker %s\n' "$label" "$marker" >&2
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
      printf 'QEMU %s reached new marker %s\n' "$label" "$marker" >&2
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
    printf 'QEMU %s reached new marker %s\n' "$label" "$marker" >&2
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
    # Recover an unacknowledged emulator event by retrying only the idempotent
    # release, never the press that might confirm erasure. A fresh guest
    # release acknowledgement is still mandatory within the original bound.
    for release_attempt in $(seq 1 20); do
      if [[ "$(marker_count "$label" "$release_marker")" -gt "$release_prior" ]]; then
        return 0
      fi
      if [[ "$release_attempt" == 5 || "$release_attempt" == 10 ]]; then
        qmp_request "$qmp_socket" key-up "$key"
      fi
      sleep 1
    done
    wait_for_new_marker "$label" "$release_marker" "$release_prior" 1
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
  local label="$1" qmp_socket="$2" method_key="${3:-3}" token="${4:-$QEMU_TARGET_SERIAL}"
  local done_limit="${5:-300}" report_img="${6:-$REPORT_RAW}"
  send_key_for_marker "$label" "$qmp_socket" ret BEAMO_WIPE_SCREEN_OWNER 20
  send_key_for_marker "$label" "$qmp_socket" spc BEAMO_WIPE_OWNER_CHECKED 20
  send_key_for_marker "$label" "$qmp_socket" ret BEAMO_WIPE_SCREEN_PICK 20
  send_key_for_marker "$label" "$qmp_socket" down BEAMO_WIPE_SCREEN_PICK 20
  send_key_for_marker "$label" "$qmp_socket" ret BEAMO_WIPE_SCREEN_CONFIRM 20
  wait_for_marker "$label" BEAMO_WIPE_CONFIRM_FOCUSED 20
  type_token_for_marker "$label" "$qmp_socket" "$token" BEAMO_WIPE_CONFIRM_MATCHED 20
  send_key_for_marker "$label" "$qmp_socket" ret BEAMO_WIPE_SCREEN_METHOD 20
  send_key_for_marker "$label" "$qmp_socket" "$method_key" BEAMO_WIPE_SCREEN_METHOD 20
  send_key_for_marker "$label" "$qmp_socket" ret BEAMO_WIPE_SCREEN_LAST_CHANCE 20
  sleep 6
  # The final screen starts with Back focused. Explicitly select Erase now;
  # Return follows focus and must never erase from the safe default button.
  send_key "$qmp_socket" tab
  send_key_for_marker "$label" "$qmp_socket" ret BEAMO_WIPE_SCREEN_WORKING 20
  wait_for_marker "$label" BEAMO_WIPE_SCREEN_DONE "$done_limit"

  # device_add is deliberately after DONE: the export selector accepts only a
  # newly inserted USB that was absent from the wipe's protected baseline.
  qmp_request "$qmp_socket" hotplug-report "$report_img"
  sleep 5
  # From Shut down, Tab visits the keyboard-accessible Show more control,
  # then Save report. Keep this in sync with the real Tk traversal test.
  send_key "$qmp_socket" tab
  send_key "$qmp_socket" tab
  send_key_for_marker "$label" "$qmp_socket" spc BEAMO_WIPE_REPORT_SAVING 20
  wait_for_report_saved "$label"
}

boot_probe() {
  local label="$1" exercise_export="$2"
  local method_key=3 token="${QEMU_TARGET_SERIAL:-}"
  local target_img="${TARGET:-}" report_img="${REPORT_RAW:-}" done_limit=300
  local qmp_socket pid machine
  shift 2
  if [[ "${1:-}" =~ ^[123]$ ]]; then method_key="$1"; shift; fi
  if [[ "${1:-}" =~ ^[A-Za-z0-9._:-]+$ && "${1:-}" != -* && "${1:-}" != *.qcow2 && "${1:-}" != *.raw ]]; then
    token="$1"
    shift
  fi
  if [[ "${1:-}" == *.qcow2 ]]; then target_img="$1"; shift; fi
  if [[ "${1:-}" == *.raw ]]; then report_img="$1"; shift; fi
  if [[ "${1:-}" =~ ^[0-9]+$ ]]; then done_limit="$1"; shift; fi
  qmp_socket="$RUN_ROOT/${label}.qmp"
  rm -f -- "$qmp_socket"
  : >"$EVIDENCE_DIR/${label}-serial.txt"
  machine="pc,accel=kvm:tcg"
  if [[ "$label" == secureboot-usb ]]; then machine="q35,accel=kvm:tcg,smm=on"; fi
  local media_args=(-cdrom "$ISO" -boot order=d)
  if [[ "$label" == *-usb ]]; then
    media_args=(-drive "if=none,id=beamo-boot-media,format=raw,readonly=on,file=$USB_IMAGE"
      -device "usb-storage,drive=beamo-boot-media,serial=BEAMOBOOT,bootindex=1")
  fi
  # shellcheck disable=SC2054 # commas are inside QEMU values, not separators
  local qemu_args=(
    qemu-system-x86_64 -machine "$machine" -m 1024 -nic none
    -device qemu-xhci,id=beamo-xhci
    "$@" "${media_args[@]}"
    -blockdev "driver=file,node-name=beamo-target-file,filename=$target_img"
    -blockdev "driver=qcow2,node-name=beamo-target,file=beamo-target-file"
    -device "virtio-blk-pci,drive=beamo-target,serial=$token"
    -display none -serial "file:$EVIDENCE_DIR/${label}-serial.txt"
    -qmp "unix:$qmp_socket,server=on,wait=off"
    -no-reboot
  )
  record_qemu_cmdline "$EVIDENCE_DIR/${label}-cmdline.txt" "${qemu_args[@]}"
  "${qemu_args[@]}" >"$EVIDENCE_DIR/${label}-qemu.txt" 2>&1 &
  pid=$!
  if [[ "$label" == bios* ]]; then BIOS_PID="$pid"; else UEFI_PID="$pid"; fi
  wait_for_qmp "$label" "$qmp_socket"
  wait_for_marker "$label" BEAMO_WIPE_SCREEN_KEYBOARD "$BOOT_WAIT_SECONDS"
  send_key_for_marker "$label" "$qmp_socket" ret BEAMO_WIPE_SCREEN_WHAT 20
  # The rendered Tk screen is the authoritative kiosk-ready boundary.  The
  # supervisor's earlier serial marker is best-effort and deliberately
  # suppresses device/write failures even when the shipped UI starts.
  wait_for_marker "$label" BEAMO_WIPE_SCREEN_WHAT "$BOOT_WAIT_SECONDS" || {
    echo "QEMU $label never rendered the shipped Tk WHAT screen" >&2
    return 1
  }
  if [[ "$label" == secureboot-usb ]]; then
    wait_for_marker "$label" 'BEAMO_WIPE_SECURE_BOOT=1' 20
  fi
  if [[ "$exercise_export" == yes ]]; then
    drive_report_export "$label" "$qmp_socket" "$method_key" "$token" "$done_limit" "$report_img"
  elif [[ "$label" == *-usb ]]; then
    # A visible welcome screen alone does not prove the new FAT32 layout is
    # recognized as protected boot media. Reach the disposable target's exact
    # confirmation without accepting it or starting an erase in these probes.
    send_key_for_marker "$label" "$qmp_socket" ret BEAMO_WIPE_SCREEN_OWNER 20
    send_key_for_marker "$label" "$qmp_socket" spc BEAMO_WIPE_OWNER_CHECKED 20
    send_key_for_marker "$label" "$qmp_socket" ret BEAMO_WIPE_SCREEN_PICK 20
    send_key_for_marker "$label" "$qmp_socket" down BEAMO_WIPE_SCREEN_PICK 20
    send_key_for_marker "$label" "$qmp_socket" ret BEAMO_WIPE_SCREEN_CONFIRM 20
    wait_for_marker "$label" BEAMO_WIPE_CONFIRM_FOCUSED 20
    # The 2 GiB USB image differs from the 1 GiB target, so this layout asks
    # for the unique displayed size. The ISO probe instead needs the serial
    # token because its optical boot medium also rounds to 1 GB.
    type_token_for_marker "$label" "$qmp_socket" 1 BEAMO_WIPE_CONFIRM_MATCHED 20
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "QEMU $label exited immediately after its final marker" >&2
    wait "$pid" || true
    return 1
  fi
  stop_pid "$pid"
  if [[ "$label" == bios* ]]; then BIOS_PID=""; else UEFI_PID=""; fi
  # Retain only allowlisted marker counts in hosted logs on successful runs
  # too; private raw serial output is never copied to stdout/stderr.
  report_marker_summary "$label"
  if [[ "$exercise_export" == yes ]]; then
    log "$label boot completed the shipped Wizard report export"
  else
    log "$label boot reached the shipped Tk WHAT screen"
  fi
}

verify_guest_report() {
  local case="$1" report_img="$2" expected_outcome="$3" expected_method="$4"
  local expected_nwipe="$5" expected_title="$6"
  REPORT_RAW="$report_img"
  REPORT_LOOP_RO=1
  REPORT_LOOP="$(sudo losetup --find --show --read-only "$report_img")"
  prove_unmounted_loop report "$REPORT_LOOP" "$report_img" 1
  # shellcheck disable=SC2024
  sudo fsck.vfat -n "$REPORT_LOOP" >"$EVIDENCE_DIR/guest-${case}-fsck.txt" 2>&1
  prove_unmounted_loop report "$REPORT_LOOP" "$report_img" 1
  sudo mount -t vfat -o ro,nodev,nosuid,noexec,nosymfollow,umask=077 \
    "$REPORT_LOOP" "$REPORT_MOUNT"
  REPORT_MOUNTED=1
  findmnt -rn -M "$REPORT_MOUNT" -S "$REPORT_LOOP" -t vfat \
    -o SOURCE,FSTYPE,OPTIONS,TARGET >"$EVIDENCE_DIR/guest-${case}-mount.txt"
  # shellcheck disable=SC2024
  sudo python3 -sP - "$REPORT_MOUNT" "$expected_outcome" "$expected_method" \
    "$expected_nwipe" "$expected_title" "${BUILD_ID:-local}" "$(git rev-parse HEAD)" \
    >"$EVIDENCE_DIR/guest-${case}-bundle.txt" <<'PY'
import hashlib
import json
import pathlib
import re
import stat
import sys

mountpoint = pathlib.Path(sys.argv[1])
expected_outcome, expected_method, expected_nwipe, expected_title = sys.argv[2:6]
expected_build_id, expected_source = sys.argv[6:8]
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
    "result_summary",
    "share_copy",
    "share_summary",
    "privacy_policy_version",
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
if complete["result_summary"] != "RESULT.txt" or "RESULT.txt" not in actual:
    raise SystemExit("invalid result summary declaration")
sharing = "SHARE.json" in actual
if (
    complete["share_copy"] != ("SHARE.json" if sharing else "")
    or complete["share_summary"] != ("SHARE.txt" if sharing else "")
    or ("SHARE.txt" in actual) != sharing
    or type(complete["privacy_policy_version"]) is not int
    or complete["privacy_policy_version"] != (1 if sharing else 0)
):
    raise SystemExit("invalid privacy summary declaration")
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
if result.get("source_commit") != expected_source or result.get("build_id") != expected_build_id:
    raise SystemExit("guest report is for another source or build")
if result.get("outcome") != expected_outcome:
    raise SystemExit(
        f"guest report outcome {result.get('outcome')!r} != {expected_outcome!r}"
    )
method = result.get("method") if isinstance(result.get("method"), dict) else {}
if method.get("id") != expected_method:
    raise SystemExit(f"guest method id {method.get('id')!r} != {expected_method!r}")
if method.get("nwipe_method") != expected_nwipe:
    raise SystemExit(
        f"guest nwipe method {method.get('nwipe_method')!r} != {expected_nwipe!r}"
    )
if method.get("rounds") != 1:
    raise SystemExit("guest method rounds is not the production value 1")
if method.get("noblank") is not True:
    raise SystemExit("guest method noblank is not the production value True")
if method.get("title") != expected_title:
    raise SystemExit(f"guest method title {method.get('title')!r} != {expected_title!r}")
expected_overwrites = {"prng": 1, "dodshort": 3, "zero": 1}[expected_nwipe]
if method.get("overwrite_passes") != expected_overwrites:
    raise SystemExit(
        f"guest overwrite_passes {method.get('overwrite_passes')!r} != {expected_overwrites!r}"
    )
if expected_outcome == "verified":
    expected_summary = {
        1: "One overwrite, followed by verification.",
        3: "Three overwrites, followed by verification.",
    }[expected_overwrites]
    expected_verify = "last"
    expected_verify_passes = 1
else:
    expected_summary = "One overwrite. Verification is not performed."
    expected_verify = "off"
    expected_verify_passes = 0
if method.get("operation_summary") != expected_summary:
    raise SystemExit(
        f"guest operation_summary {method.get('operation_summary')!r} != {expected_summary!r}"
    )
if method.get("verify") != expected_verify or method.get("verification_passes") != expected_verify_passes:
    raise SystemExit("guest verification fields do not match the production method")
nwipe = result.get("nwipe") if isinstance(result.get("nwipe"), dict) else {}
argv = nwipe.get("argv_redacted") if isinstance(nwipe.get("argv_redacted"), list) else []
for flag in (
    f"--method={expected_nwipe}",
    f"--verify={expected_verify}",
    "--rounds=1",
    "--noblank",
    "--quiet",
    "--autonuke",
):
    if flag not in argv:
        raise SystemExit(f"guest argv missing {flag}")
summary = actual.get("RESULT.txt", b"").decode("utf-8", "replace")
if expected_title not in summary:
    raise SystemExit(f"RESULT.txt missing method title {expected_title!r}")
if expected_summary not in summary:
    raise SystemExit("RESULT.txt missing operation summary")
if f"Overwrites: {expected_overwrites}" not in summary:
    raise SystemExit("RESULT.txt missing overwrite count")
if expected_outcome == "verified":
    if "Erase completed; verification passed" not in summary:
        raise SystemExit("RESULT.txt missing verified wording")
else:
    if "verification was not performed" not in summary.lower():
        raise SystemExit("RESULT.txt missing unverified wording")
print(f"session={session.name}")
print(f"outcome={result['outcome']}")
print(f"method={method.get('id')}")
print(f"nwipe_method={method.get('nwipe_method')}")
print(f"overwrite_passes={method.get('overwrite_passes')}")
print(f"files={','.join(sorted(actual))}")
PY
  sudo umount "$REPORT_MOUNT"
  REPORT_MOUNTED=0
  if findmnt -rn -M "$REPORT_MOUNT" | grep -q .; then
    echo "report USB remained mounted after host verification" >&2
    return 1
  fi
  prove_unmounted_loop report "$REPORT_LOOP" "$report_img" 1
  detach_owned_loop report "$REPORT_LOOP" "$report_img" 1
  REPORT_LOOP=""
  REPORT_LOOP_RO=""
  log "guest $case report passed clean-FAT, method, wording, checksum, and unmount checks"
}

method_title() {
  case "$1" in
    everyday) printf '%s\n' "Everyday" ;;
    extra) printf '%s\n' "Three overwrites" ;;
    quick_zero) printf '%s\n' "Quick zero" ;;
    *)
      echo "ABORT: unknown method case $1" >&2
      return 1
      ;;
  esac
}

assert_guest_phases() {
  local label="$1"
  python3 - "$EVIDENCE_DIR/${label}-serial.txt" <<'PY'
import pathlib
import sys

required = (
    "BEAMO_WIPE_SCREEN_KEYBOARD",
    "BEAMO_WIPE_SCREEN_WHAT",
    "BEAMO_WIPE_SCREEN_OWNER",
    "BEAMO_WIPE_OWNER_CHECKED",
    "BEAMO_WIPE_SCREEN_PICK",
    "BEAMO_WIPE_SCREEN_CONFIRM",
    "BEAMO_WIPE_CONFIRM_MATCHED",
    "BEAMO_WIPE_SCREEN_METHOD",
    "BEAMO_WIPE_SCREEN_LAST_CHANCE",
    "BEAMO_WIPE_SCREEN_WORKING",
    "BEAMO_WIPE_SCREEN_DONE",
    "BEAMO_WIPE_REPORT_SAVING",
    "BEAMO_WIPE_REPORT_SAVED",
)
path = pathlib.Path(sys.argv[1])
lines = [line.rstrip("\r") for line in path.read_text(encoding="utf-8", errors="replace").splitlines()]
index = 0
for marker in required:
    try:
        found = lines.index(marker, index)
    except ValueError as exc:
        raise SystemExit(f"guest phase {marker} missing or out of order") from exc
    index = found + 1
print("phases=" + ",".join(required))
PY
}

run_guest_method() {
  local case="$1" production_case="$2" key="$3" nwipe_method="$4"
  local outcome="$5" guest_timeout="$6" serial="$7"
  local local_target="$RUN_ROOT/target-${case}.qcow2"
  local local_report="$RUN_ROOT/report-${case}.raw"
  make_guest_target "$local_target"
  make_report_image "$local_report"
  TARGET="$local_target"
  REPORT_RAW="$local_report"
  QEMU_TARGET_SERIAL="$serial"
  boot_probe "bios-${case}" yes "$key" "$serial" "$local_target" "$local_report" "$guest_timeout"
  assert_guest_phases "bios-${case}"
  assert_guest_overwrite "$case" "$nwipe_method" "$local_target"
  verify_guest_report "$case" "$local_report" "$outcome" "$production_case" "$nwipe_method" "$(method_title "$production_case")"
}

EXECUTED_CASES=""
while IFS='|' read -r case key nwipe_method verify outcome host_timeout guest_timeout serial; do
  [[ -n "$case" ]] || continue
  run_guest_method "$case" "$case" "$key" "$nwipe_method" "$outcome" "$guest_timeout" "$serial"
  run_guest_method "${case}-repeat" "$case" "$key" "$nwipe_method" "$outcome" "$guest_timeout" "$serial"
  EXECUTED_CASES="${EXECUTED_CASES:+$EXECUTED_CASES,}$case"
done <<<"$METHOD_CASES"
[[ "$EXECUTED_CASES" == "everyday,extra,quick_zero" ]] || {
  echo "ABORT: executed cases were $EXECUTED_CASES, expected everyday,extra,quick_zero" >&2
  exit 2
}
log "all production methods completed isolated BIOS journeys"

TARGET="$RUN_ROOT/target-uefi.qcow2"
QEMU_TARGET_SERIAL="0001"
make_guest_target "$TARGET"

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

boot_probe bios-usb no
cp "$OVMF_VARS" "$RUN_ROOT/ovmf-usb-vars.fd"
boot_probe uefi-usb no \
  -drive "if=pflash,format=raw,readonly=on,file=$OVMF_CODE" \
  -drive "if=pflash,format=raw,file=$RUN_ROOT/ovmf-usb-vars.fd"

# Enrolled Microsoft keys and SMM enforcement. A bare OVMF boot is not
# Secure Boot evidence. The guest must report the actual firmware variable.
SECURE_CODE=/usr/share/OVMF/OVMF_CODE_4M.secboot.fd
SECURE_VARS=/usr/share/OVMF/OVMF_VARS_4M.ms.fd
[[ -f "$SECURE_CODE" && -f "$SECURE_VARS" ]] || { echo "Enrolled Secure Boot firmware missing" >&2; exit 2; }
cp "$SECURE_VARS" "$RUN_ROOT/secureboot-vars.fd"
boot_probe secureboot-usb no \
  -global driver=cfi.pflash01,property=secure,value=on \
  -drive "if=pflash,format=raw,readonly=on,file=$SECURE_CODE" \
  -drive "if=pflash,format=raw,file=$RUN_ROOT/secureboot-vars.fd"

printf 'iso_sha256=%s\nnwipe_sha256=%s\nsource_commit=%s\nbuild_id=%s\nrepetitions=2\ncases=%s\neveryday=pass\nextra=pass\nquick_zero=pass\nbios=pass\nuefi=pass\nbios_usb=pass\nuefi_usb=pass\nsecureboot_usb=pass\nreport_export=pass\n' \
  "$(sha256sum "$ISO" | awk '{print $1}')" "$shipped_sha" \
  "$(tr -d '\n' <"$EVIDENCE_DIR/source-commit.txt")" \
  "${BUILD_ID:-local}" "${EXECUTED_CASES}" \
  >"$EVIDENCE_DIR/summary.txt"
log "PASS; evidence=$EVIDENCE_DIR cases=$EXECUTED_CASES"
