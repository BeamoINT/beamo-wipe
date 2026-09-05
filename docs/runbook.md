# Beamo Wipe — Production support and incident runbook

> **Version 1.1 — 2026-09-05 | Owner: Accountable senior engineer (this checkout) | Next review 2026-12-05**
> Pinned wrapper `0.2.2` / `nwipe v0.42` commit `6082bde060091e66365d852a1877f2ee80c67105` at `/usr/lib/beamo-wipe/nwipe`
> Wrapper GPL-3.0-or-later; nwipe GPL-2.0. See `docs/storage-and-controller-limits.md`, `docs/compatibility-matrix.md`.

This runbook is for the support operator who answers "the USB won't boot / it shows no disks / the erase failed." It separates **verified behavior** (code, tests, build) from **unknowns**, gives decision trees that never weaken a safety gate, and defines how to reproduce safely, collect evidence with redaction, communicate, and when to quarantine or stop-ship.

No step in this runbook allows disabling boot-media exclusion, skipping owner/type-to-confirm/5 s delay, manually targeting `/dev/...` without safe identification, or running `nwipe` on a developer/host disk.

---

## 1. Safety boundary (read first, applies to every tree)

- **Never run `nwipe` against a real disk from the development Mac.** Local repro uses fake `lsblk` JSON only (`tests/fixtures/*.json`, `src/beamo_wipe/demo_*.json`), `BEAMO_WIPE_DRY_RUN=1`, `DryRunRunner`. See `docs/vm-test.md` for the isolation rule.
- **ISO builds and destructive-path/QEMU repro only on isolated x86_64** with `scripts/qemu-verify.sh`, which creates a private `mktemp` workspace plus fresh qcow2/raw files and re-proves loop backing before execution. No host-disk passthrough; tear the VM down after. The arm64 development Mac is **not** the QEMU host.
- **Fail closed on uncertainty.** Missing/conflicting/stale/changed boot or target identity, state, or evidence → no selectable targets, `SafetyError`, no `nwipe` invoked (`docs/boot-exclusion-signals.md` signal map).
- **Invariants never relaxed** for reproduction, debugging, or customer convenience: boot exclusion, exact whole-disk binding (`/dev/sda` not `sda1`, `/dev/nvme0n1` not `n1p1`, rejects `sr0`/`nbd*`), ownership checkbox, type-to-confirm (`SAFE_TOKEN_RE`, trimmed casefold), `COUNTDOWN_S=5.0`, no-auto-start, pinned `nwipe` `/usr/lib/beamo-wipe/nwipe` (ELF `7F 45 4C 46`, root-owned, `nwipe version 0.42` line), logs under `/tmp/beamo-wipe/` never on target (`FORBIDDEN_LOG_ROOTS`, `_log_filesystem_is_target`, `O_NOFOLLOW` `0o600`). Any change is a `safety:` commit with a test.
- **Unsupported environments are out of scope.** Apple Silicon `M1/M2/M3`, Chromebooks, RAID controllers (`megaraid/aacraid/dm-raid`), Apple T2 internal, `nbd/iscsi/fc/nvmeof`, hardware RAID behind a single virtual disk — correctly listed-with-no-targets or fails closed. Do not claim or retarget.

---

## 2. Roles, severity, and SLA

| Role | Who | Owns |
|---|---|---|
| **L1 Support** | Front-line support (Beamo) — first queue, owns the ticket, talks to customer, collects evidence, follows this runbook. | Decision trees §4, evidence §5, comms §7 |
| **On-call Engineer** | Repo owner / accountable senior engineer — owns code, CI, ISO build, manifest, QEMU fixturing. Paged on SEV-1/2. | Reproduction §8, triage §6, rollback/quarantine §9 |
| **Release Manager** | Owner of `dist/*.iso`, `gs://beamo-wipe_cloudbuild/releases/` artifacts, GitHub releases. | Stop-ship / quarantine / promotion §9 |

| Severity | Definition | Example | SLA |
|---|---|---|---|
| **SEV-1** | Data-loss or wrong-disk wipe risk, boot exclusion believed bypassed, evidence shows host disk targeted | Customer claims the USB device was listed as a target, or `nwipe` logged a host `nvme0n1` as target alongside `BEAMO_WIPE` USB | Acknowledge 30 min, engineer paged immediately, quarantine §9, do not ask customer to retry |
| **SEV-2** | Wipe systematically fails on supported hardware where docs claim supported, or result is ambiguous and customer needs a certificate | `Done Fail` with `No sane device geometry` on healthy ST500/WDC/Samsung 970 per `docs/compatibility-matrix.md` ST-01/ST-03, or `verified` vs `completed` confusion on `zero` method | Acknowledge 2 h, L1 follows §4.g–h, engineer reproduces via §8 within 24 h |
| **SEV-3** | Single-machine boot/disk identification failure within documented degraded/unsupported bucket, or blank/low-res UI cosmetic | `PICK_EMPTY` on eMMC-only tablet (expected degraded), 800×600 footer needs scroll, Secure Boot rejects USB | L1 resolves from this runbook within 1 business day, no escalation unless pattern |
| **SEV-4** | Docs/claim sync drift, copy typo, packaging label request | Missing link to storage limits doc | Next release |

Escalation: L1→On-call→Release Manager. Handoffs are recorded in the ticket with timestamp, symptom, fixture/hash tried, and evidence attached (redacted). No handoff may add `--force` or manual `/dev/` targeting.

---

## 3. What to collect — evidence checklist (privacy-safe)

For a wipe that cannot start, collect only the [startup diagnostic report](startup-diagnostics.md). The disk-identifying evidence and raw inventory rows below do not apply to startup diagnostics. If boot identity cannot be re-established, report export stays blocked; do not bypass it.

Collect in order shown. Redaction is mandatory before leaving the support queue.

| Evidence | Where | Redaction | Notes |
|---|---|---|---|
| Ticket summary | Customer words | No disk serials unless customer volunteered | Symptom in customer's language |
| Photo of screen | Customer phone photo of wizard or `PICK_EMPTY/BLOCKED` | Blur any serial if posted publicly | Must show step label (Step X of 8) + message |
| `diagnostic.json` + `.sha256` + `COMPLETE` | Blocked/empty/start-failure screen: **Diagnostic report** → Prepare → insert one new FAT32 USB → Save | Fixed codes, exact application/build identity, discovery status, unverified UTC and monotonic session time; no disk identifiers or raw logs | Startup support only; not erase evidence. See [startup diagnostics](startup-diagnostics.md). |
| `result.json` + `result.json.sha256` | Live USB `/tmp/beamo-wipe/` (tmpfs, not target), then the Finished-screen **Save report to USB** workflow | Already redacted: contains `device.realpath/serial/wwn/vendor`, `method`, `boot_device`, `outcome`, `failure_reason`, `verification`, `log_checksum_sha256`, `provenance.evidence_file` — no hostname/IP/user | The USB bundle is accepted only after a completion marker, read-only remount verification, and final unmount. |
| `nwipe.log` or `nwipe-tail.log` + `.sha256` | Same private bundle; only the exact authenticated log suffix recorded in terminal evidence is exported, and a suffix shorter than the current file is explicitly marked as a tail | Contains the engine markers used by `evaluate_nwipe_completion`: `is reported as IN USE`, `Nwipe was aborted`, `Unable to open device`, `No sane device geometry`, `>>> FAILURE! <<<`, `| Erased |`, `SIGUSR1` progress | Never copy to target disk; see `FORBIDDEN_LOG_ROOTS`. Missing, changed, or unsafe logs are recorded as unavailable rather than silently trusted. |
| `lsblk` JSON snapshot | Live: run `lsblk -J -b -o NAME,PATH,SIZE,TYPE,TRAN,ROTA,MODEL,SERIAL,WWN,RM,HOTPLUG,MOUNTPOINTS,LABEL,FSTYPE,VENDOR,PKNAME,UUID` into a file on the second USB | Contains serials — treat as PII, keep in ticket private field | For L1 to file a fake fixture that reproduces without hardware (see §8) |
| Manifest + ISO hash | Customer reads `dist/*.manifest.json` + `dist/beamo-wipe-*.iso.sha256` or `gs://…` object, or wrapper `NWIPE_VERSION` on USB | No customer PII | Proves build input pin |
| Environment | Wrapper version (`src/beamo_wipe/__init__.py 0.2.2`), live `NWIPE_VERSION` on USB, firmware mode (BIOS vs UEFI, Secure Boot on/off), machine vendor/model, bus of target (`TRAN`), kind (`ROTA`→HDD vs SSD per `classify_kind`) | Strip customer name | Needed for §3 wear/raid decision |

**Privacy rule:** Support queue shows `device.serial` only to on-call and only when the customer consented. Public issues use `size_gb_label` + `kind` + sanitized `evidence.outcome`/`failure_reason` with serial replaced by `***`.

---

## 4. Decision trees — do not weaken the gate

Each tree ends in exactly one of: **resolve with guidance**, **collect evidence and escalate**, or **quarantine/stop-ship**. No branch says "disable exclusion" or "hand-type `/dev/sda` into nwipe."

### 4.a Failed boot — USB never appears in firmware boot menu

```
Symptom: stick never appears (Dell F12, HP F9/Esc, Lenovo F12 not listed)
  ├─ Ask: does live USB show on *another* x64 PC with Secure Boot **disabled**?
  │   ├─ No on any PC → suspect stick or flash. Check `scripts/build-iso.sh` ISO hash (`CD001` at 32769, ≥80 MiB, sha256)
  │   │       Reflash on Linux: `sudo dd if=dist/beamo-wipe-0.2.2-amd64.iso ...` (verify `/dev/sdX` *is* USB via `lsblk`), or BalenaEtcher. Retry.
  │   └─ Yes on at least one PC → firmware setting issue.
  ├─ Secure Boot enabled? → This image is unsigned (docs/claims.md). Do NOT ship a bypass.
  │        Guidance: allow USB boot / disable Secure Boot per vendor, or use a PC with Secure Boot off. Link helper/index.html.
  ├─ Fast Boot / USB legacy disabled? → Guidance: disable Fast Boot, enable USB legacy/CSM, try direct USB-A/C port not a keyboard hub.
  └─ Still not listed → degraded boot findability (docs/compatibility-matrix.md DISP/ FW). Collect vendor/model/BIOS version, photo of boot menu, manifest hash, and file as SEV-3 (escalate if ≥2 vendors systematically).
Action: never "force boot via efibootmgr on customer PC."
```

### 4.b Blank / low-resolution UI (old 800×600 laptop, VNC 96 DPI)

```
Symptom: footer buttons off-screen, text clipped, splash not centered
  ├─ Check: is live USB X at 72 DPI? (packaging/live/config/includes.chroot/etc/X11/xorg.conf.d/10-beamo.conf sets 72 DPI)
  │       VNC `DISPLAY=:1` at 96 DPI will clip by ~33% — not the gate. Hosted gate uses `DISPLAY=:99` @72 DPI.
  ├─ Window is `minsize 1024×740` (oldest laptops) with hero `CONTENT_W 940`. At 800×600 the pick list scrolls; footer is packed `side=BOTTOM` last so actions stay reachable via Tab — degraded (docs/accessibility-lowres-matrix.md DISP-05/DISP-06) not a safety failure.
  └─ If *all* screens blank → check `docs/ci.md` failure triage `TclError: no display` vs real regression; reproduce with Xvfb 72 DPI.
Action: no change to `tk scaling 1.0` pin (keeps fonts deterministic). If customer needs 800×600 daily, note as degraded and track as feature request.
```

### 4.c Missing disks — `PICK_EMPTY` (no other disks)

```
Wizard shows `No disk to erase`
  ├─ Expected when only the Beamo USB exists (verify: customer photo shows no other disk line). Guidance: shut down, attach target disk, boot again.
  ├─ Expected degraded when only soldered eMMC (`mmcblk0boot0` 4 MB hidden via HIDDEN_NAME_RE → correctly not shown) → PICK_EMPTY with one USB (see storage-and-controller-limits §3).
  ├─ Check: is target a network/SAN disk (`nbd/iscsi/fc/nvmeof` → REMOTE_BUS_TOKENS) or dm-raid (`megaraid`)? → Unsupported, correctly hidden (§7 unsupported table). Do NOT offer to target via /dev nbd.
  └─ Otherwise → collect `lsblk -J` snapshot (see §3), wrapper/manifest hash, firmware mode. File SEV-3; engineer adds fixture `lsblk_unusual_controllers.json`-style and pins via tests/test_compatibility_matrix.py without weakening HIDDEN_NAME_RE.
```

### 4.d Extra disks / uncertain boot media — `PICK_BLOCKED` (cannot tell which disk is this USB)

```
Wizard shows `We cannot tell which disk is this USB. Unplug extra USB sticks and start again.`
  ├─ Tell customer to unplug every USB except the Beamo stick + restart (hubs hide sticks, docs/boot-card.md). Do NOT suggest picking the USB as a target.
  ├─ Check: two sticks both labeled BEAMO_WIPE? → duplicate label triggers fail-closed duplicate (fixture lsblk duplicate BEAMO_WIPE on sda+sdb, both usb → boot_identified False). Guidance same: one stick only.
  ├─ Stale BEAMO_WIPE on internal SATA (sda tran sata label BEAMO_WIPE) + real USB as sdb with DEBIAN label → label fallback correctly ignores sda (must be usb/rom, _looks_like_live_medium) and mount wins. If still blocked, collect mount sources + cmdline (`boot=live` token).
  └─ Still blocked → collect `lsblk`, `cat /proc/cmdline`, `findmnt --json` from live (via second USB), file SEV-2/3. Engineer adds fixture `lsblk_sata_bridge.json` style. Never "export BEAMO_WIPE_BOOT_DEVICE" to customer.
Prohibition: support never runs `export BEAMO_WIPE_BOOT_DEVICE=/dev/sdX` for a customer to force a pick.
```

### 4.e Confirmation failures — token mismatch

```
Confirm screen type-to-confirm does not enable Continue
  ├─ Re-read together: "Type these numbers so we know it is the right disk: <token>" — token is size label or last 4 of serial or device name via SAFE_TOKEN_RE (casefold trimmed). Continue is disabled until token_ok (takefocus=0 on disabled primary).
  ├─ Check: are two disks same size `size_gb_label`? → same_size_conflict → token is serial suffix, not size (see copy.py confirm_warning). Hint: "Two disks are the same size. Look at the characters under the name" + SSD footer if SSD.
  ├─ Customer typed `O` vs `0`? → Explain mono token, letter vs digit; qwerty `I/l`.
  └─ Still blocked → collect photo of disk summary (model+serial+size) vs token shown, verify `confirm_spec` for that size/serial pair. No bypass.
Never: "paste mtab" or "temporarily bypass token."
```

### 4.f Interrupted wipes

A confirmed user cancellation is “Stopped by you.” System interruption, inability
to confirm termination, and missing completion evidence have different outcomes
in the table below. A closed lid or power loss does not establish which part of
an erase completed. If temporary evidence was lost, the result is indeterminate.
Save available evidence and contact support. Do not resume from a percentage or
automatically retry an erase.

### 4.g nwipe errors — structured outcomes and safe next steps

`nwipe_runner.py` interprets process termination and target-specific log evidence.
`outcomes.py` then maps validated evidence to the following visible explanations.
Technical codes and bounded diagnostics remain available for support. Never
infer success from exit 0 or a progress percentage alone. Successful completion
requires an explicit successful completion marker accepted by the validator,
consistent method/verification facts, and no conflicting failure or interruption.

| Code | Visible explanation and safe next step |
| --- | --- |
| `start_failed` | The erase could not start. Keep the disks connected and contact support. Do not bypass protection. |
| `verified` | Erase completed; verification passed. Read-back checked exposed storage only. Hidden copies may remain. Save the report if needed. |
| `unverified` | Erase completed; verification was not performed. The erase was not checked by a read-back pass. Save the report if needed. |
| `occupied` | The disk is in use. The erase did not complete. Save the report and ask support what is using the disk. Do not force access. |
| `open_failed` | The disk could not be opened. Files may still be on the disk. Save the report if available and contact support. Shut down before disconnecting. |
| `geometry_unusable` | The disk could not be used safely. Files may still be on the disk. Save the report if available and contact support. Shut down before disconnecting. |
| `verification_failed` | Read-back verification failed. Files may still be on the disk. Save the report if available and contact support. Shut down before disconnecting. |
| `interrupted` | The erase was interrupted. Files may still be on the disk. Save the report if available and contact support. Shut down before disconnecting. |
| `cancelled` | Stopped by you. Files may still be on the disk. Save the report if available and contact support. Shut down before disconnecting. |
| `completion_missing` | Erase completion could not be confirmed. Files may still be on the disk. Save the report if available and contact support. Shut down before disconnecting. |
| `process_failed` | The erase did not finish. Files may still be on the disk. Save the report if available and contact support. Shut down before disconnecting. |
| `engine_failed` | The disk reported an erase error. Files may still be on the disk. Save the report if available and contact support. Shut down before disconnecting. |
| `indeterminate` | The result could not be confirmed. Files may still be on the disk. Save the report if available and contact support. Shut down before disconnecting. |
| `stop_unconfirmed` | The erase may still be running. Keep the disk and Beamo USB connected. Do not start another erase. Contact support. |

Diagnostic markers include `is reported as IN USE`, `Nwipe was aborted by the user`,
`Unable to open device`, `No sane device geometry`, `>>> FAILURE! <<<`, and the
selected target's `| Erased |` row. SIGUSR1 progress is not an independent
verification result. Use the structured record and validator instead of asking
an operator to reinterpret isolated log lines. Never add `--force` or bypass a
lock, identity check, or confirmation.

### 4.h Ambiguous results — result interpretation & log collection

`completed` means successful erasure without verification; `verified` means the
requested read-back verification passed according to validated evidence. Neither
proves coverage of inaccessible or remapped storage. Missing or inconsistent
completion evidence remains indeterminate, separate from confirmed cancellation
and interruption. Do not automatically re-run an erase or edit evidence into success.

Keep report media unplugged during target selection, confirmation, and erasing.
After the erase has stopped and **Save report to USB** is available, leave the
boot USB and target attached, insert exactly one new FAT32 USB, then choose Save.
Any unsaved report is lost when the live session shuts down or loses power.
The optional **Need a report?** preference does not export or prevent shutdown.
See [Advanced report guidance](ADVANCED.md#logs) for early insertion, refresh,
unsupported filesystems, and safe removal. Logs remain
under `/tmp/beamo-wipe/`. The guarded exporter excludes all original devices,
writes a unique bundle, syncs, unmounts, remounts read-only, verifies exact bytes,
and unmounts again. Its `COMPLETE` file authenticates bundle contents; only the
live success message after final unmount confirms safe removal. No formatting,
repair, force-unmount or lazy-unmount is offered.

Reports are not a formal certificate. Collect available `result-*.json`, checksum
sidecars, authenticated log suffix, and image manifest. Keep device serials out
of public issues. If power loss removed the temporary evidence, preserve any
remaining records and contact support; do not infer a successful erase.

### 4.i Quarantine cue — when to stop instead of help the customer continue

```
If any of: SEV-1 wrong-disk risk, systematic ST-01/ST-03 failure on healthy HDD where docs claim supported, evidence shows host nvme0n1 as target, or ISO hash mismatch on the field ISO → do not triage further. Jump to §9 rollback/quarantine/stop-ship, page on-call, keep artifact hashes, do not ask customer to retry on same hardware.
```

---

## 5. Severity already defined at §2 — customer communication templates (privacy-safe)

Use these verbatim or close; they contain no bypass instruction.

*Failed boot:* "Thanks for the photo. This image is unsigned (Secure Boot: allow USB boot) and not for Apple Silicon. Please try the steps at `helper/index.html` (F12/Esc/F9), direct USB-A/C port not a hub, disable Fast Boot, and try one more x64 PC with Secure Boot off. If it still doesn't appear, attach `beamo-wipe-*.manifest.json` hash and the PC model/BIOS version (no serial) and we'll add a fixture."

*PICK_EMPTY / hidden eMMC:* "This machine's only internal storage is soldered eMMC; the 4 MB `mmcblk0boot0` area is intentionally not shown and not wiped. That's expected degraded behavior — see `docs/storage-and-controller-limits.md` §3. For soldered boards, the recommendation is vendor erase or destruction per §5."

*PICK_BLOCKED / uncertain USB:* "We refuse to list disks when we can't tell which is this USB — that's fail-closed and correct. Please unplug every USB except this stick and restart. If it still says that, we need the screen photo plus `lsblk -J -b` contents saved to a second USB (kept private) so we can file a fixture without asking you to hand-type a device name."

*Token mismatch:* "That screen wants the numbers/4 characters under the name on that row (size label or last 4 of serial). Capitals don't matter; type it exactly. Continue stays off until it matches — that's the gate."

*Interrupted / Failed:* "`The erase did not finish. Files may still be on the disk.` There's no resume. If Save report to USB is available after the erase has stopped, leave the Beamo USB and selected disk attached, insert exactly one FAT32 USB, and choose **Save report to USB**. Wait for `Report saved and verified` before removing it. That report lets support match the exact failure (`IN USE`, `No sane device geometry`, `Unable to open device`, failure row, or non-zero exit)."

*SSD certificate request:* "This USB does an overwrite pass with nwipe. On a hard disk that's usually what people want. On an SSD the drive's controller decides where writes land, so spare area can still hold old copies. We don't call that certified. If your contract needs spare-area guarantees, use the drive maker's erase tool for that model, or destroy the drive — details at `docs/storage-and-controller-limits.md` §5. Your `result.json` only records overwrite evidence (`verified` vs `completed`) not a lab certificate."

All replies link to the relevant `docs/*.md` anchor and state that no `--force` or manual `/dev/` targeting will be offered.

---

## 6. Safe reproduction — fake fixtures first, isolated QEMU second

### 6.a Prohibitions (support must never)

- Do not `dd`, `hdparm`, `nvme sanitize`, `lsblk` *without* a fixture file, `mount /dev/sda*`, `echo 1 > /sys/block/...`, `smartctl --scan` on the development Mac pointing at a real user disk.
- Do not `gcloud compute ssh` to a persistent VM that mounts a customer's disk image as host `/dev/sda`. Only ephemeral VMs with throwaway `qcow2`.
- Do not `export BEAMO_WIPE_BOOT_DEVICE=…` to silence `PICK_BLOCKED` for a customer session.
- Do not pass `--force` to `nwipe` to clear "IN USE" — `validate_argv` forbids it and the bypass hides the mount that made the data still visible.

### 6.b Reproduce with fake fixtures (first, always)

The production-readable path that never touches host block devices:

```bash
# from repo root, no real disks
BEAMO_WIPE_DRY_RUN=1 python3 -m pytest -k "not tk_runtime"  # fast gate

# Single signal repro — pick a fixture that matches the ticket's TRAN/SIZE/SERIAL shape:
ls tests/fixtures/*.json
cat tests/fixtures/lsblk_missing_metadata.json | head -n 40   # model null fallback → WINDOWS label
cat tests/fixtures/lsblk_unusual_controllers.json | head -n 60  # mmcblk0boot0 hidden via HIDDEN_NAME_RE

python3 - <<'PY'
from pathlib import Path
from beamo_wipe.discover import discover
import json
payload = Path("tests/fixtures/lsblk_missing_metadata.json").read_text()
result = discover(lsblk_payload=payload, boot_path="/dev/sdb")
print("boot_identified", result.boot_identified, "boot", result.boot and result.boot.path)
print("selectable", [d.path for d in result.selectable])
print("listed", [(d.path, d.is_boot) for d in result.disks if d.path])
PY

# Full wizard state-machine repro with fake disks (no nwipe):
BEAMO_WIPE_DEMO=1 BEAMO_WIPE_DRY_RUN=1 python3 -m beamo_wipe --demo --scenario happy  # via ./preview
BEAMO_WIPE_NO_OPEN=1 ./preview --web && ls web-preview/index.html   # click-through
python3 -m pytest tests/test_accessibility_lowres.py -v  # low-res/focus proof still at 72 DPI
```

Add a new fixture `tests/fixtures/lsblk_<ticket>.json` (redacted serial, keep `TRAN`, `ROTA`, `SIZE`, `WWN` shape) and a test in `tests/test_compatibility_matrix.py` that asserts the ticket's expected `selectable` set and the `SAFE_TOKEN_RE` token chain (size label → last4 serial → device name) before closing the ticket. The commit message is `test: ...` not `safety:` unless the gate itself changed.

### 6.c Isolated disposable QEMU (second, only on x86_64, only when fixture repro is insufficient)

Only when the ticket needs to see `nwipe` exit path (`IN USE`, `Unable to open device`, `No sane device geometry`, `| Erased |`, signal, timeout) that fake-disks cannot model.

On a throwaway x86_64 Linux VM with `/dev/kvm`, no host block passthrough, one newly created disposable virtual target — never on the development Mac or a real user disk. Record and re-check isolation and disposable-disk identity immediately before execution; abort on any mismatch.

```bash
# On a throwaway x86_64 Linux VM with /dev/kvm (e.g., GCE n2-standard-4), ephemeral:
BEAMO_WIPE_VERSION=0.2.2 ./scripts/qemu-verify.sh
evidence_dir=$(cat qemu-evidence/PATH)
find "$evidence_dir" -maxdepth 1 -type f -print
# Tear down the VM (gcloud compute instances delete ... --quiet)
```

`scripts/qemu-verify.sh` requires Linux x86_64 and an exact manifest-bound ISO. It creates unpredictable private paths, uses only image files, and rechecks `findmnt`, `lsblk TYPE=loop`, and `losetup -j` before the shipped `nwipe` binary is invoked. Any mismatch aborts (see `docs/qemu-verify.md`).

Reference for controller limits that QEMU virtio does **not** model: `untested-physical.txt` in the qemu artifact (`real NVMe/SATA controllers beyond QEMU virtio, USB-SATA bridges, Secure Boot enrolled keys, Apple Silicon, RAID, SSD wear-leveling certificate`), per `docs/storage-and-controller-limits.md`.

---

## 7. Escalation and incident walkthroughs — gaps, timing, handoffs

The support-intended operator is **L1 Support** (on-boarded via this doc + `docs/screens.md` + one shadow of `tests/test_wizard_flow.py`). We walked three representative tickets end-to-end (fake-disk repro only, no host wipe) and logged gaps below.

### 7.a Walk-through Inc-1 — PICK_BLOCKED on two-USB hub (customer at recycle day)

*Scenario:* School IT boots Dell 7410 from Beamo stick behind a USB hub that also powers a second stick with photos. Wizard shows `PICK_BLOCKED` `We cannot tell which disk is this USB.`

*T+0:00* L1 receives photo showing Step 3 header + blocked copy. No serial needed. Replies with blocked template (unplug every USB except Beamo + restart, direct port not hub). Attaches `helper/index.html` F12 line.
*T+0:08* Customer retries directly on USB-A, still blocked. L1 asks for `result-*.json` reading shows none (wizard never left pick), so asks for `lsblk -J -b` saved to second USB on next reboot (privacy note: keep private).
*T+0:25* Customer pastes redacted `TRAN usb` both sticks both `LABEL BEAMO_WIPE`? Actually second stick is `LABEL PHOTOS`. Lsblk shows `sda` `TRAN sata`? No — but fixture reveals USB-SATA bridge presenting `tran sata` for the Beamo stick → label-only fallback would fail closed (`sata` not `usb` per `_looks_like_live_medium`). L1 sees the mount source line `/dev/sdb1 on /run/live/medium` with cmdline `boot=live` — mount wins, not label. L1 realizes hub wasn't the issue; the bridge was. Updates reply with `boot=live` mount-wins note.
*T+0:40* Engineer adds fixture `lsblk_sata_bridge.json` (already present) and a ticket-scoped test asserting `discover(..., mount_sources=["/dev/sdb1"], cmdline="boot=live")` still identifies boot `sdb` despite `tran sata` bridge. Test committed as `test: ...` (no gate change).
*Gap found & fixed:* First template omitted "mount wins over label on SATA bridge." Added to §4.d's bridge paragraph. Timing: 40 min wall, 2 handoffs (L1→eng→L1). Missing at start: `TRAN` field in lsblk snapshot — checklist §3 now requires `TRAN`/`ROTA`/`WWN` explicitly.

### 7.b Walk-through Inc-2 — nwipe `IN USE` on SATA HDD that looked healthy

*Scenario:* Customer picks `sda 500 GB WDC 5000AAKX` and native `prng` aborts with `is IN USE but --force is not set`. `result.json` outcome `failed`, `failure_reason` `nwipe skipped the disk because it is in use`, log contains `is reported as IN USE`.

*T+0:00* L1 receives `result.json` + `nwipe.log` tail (hash matched sidecar). Classifies via §4.g as busy/mounted, not geometry. Asks: did you mount `sda1` via another console? Customer says no, but photo shows the panel at `PICK` listed `sda1` mountpoint `/media/data`? Actually `lsblk` shows `sda1` `mountpoint /media/data` → `has_any_mount` → should not have been selectable? Check `src/beamo_wipe/safety.py: is_wipeable_disk` → not wipeable when child has mount, so `selectable` should be empty and wizard would show `PICK_EMPTY` not `IN USE`. Something is stale: disk was added after boot.
*T+0:15* L1 asks customer to reboot and note if `PICK` again lists the disk after fresh boot. Customer retries → now `PICK` shows `PICK_EMPTY` with "plug in the drive you want to erase" — correct, the other OS had it mounted before. Engineer reproduces via fake `lsblk_sata_bridge.json` style mounted media fixture `sda1 mountpoint /media/data` → `test_mounted_media_disk_is_not_selectable` proves not selectable, explains `IN USE` was stale rediscover.
*T+0:30* Customer question: "Can you just `--force` it?" L1 answers from §4.g: `Never pass --force` — `validate_argv` forbids it precisely because the mount means the OS's view of data is still live. Guidance: reboot without mounting.
*Gap found & fixed:* Runbook's `IN USE` row lacked the "stale after hot-plug" why. Added sentence under `IN USE`: target was busy/mounted at the moment of the wipe attempt; fresh boot without auto-mount is the fix, not `--force`. Handoff: L1 stayed solo, no escalation, 30 min.

### 7.c Walk-through Inc-3 — Ambiguous `Done` on NVMe where SSD limit matters

*Scenario:* Small business retires 10 Samsung 970 EVOs, runs `quick zero --verify=off` for speed, gets `Done` with `outcome completed` and asks for a certificate for the auditor.

*T+0:00* L1 receives `result.json` rows: `method id quick_zero`, `verification requested off, verified false`, `outcome completed`. Explains per §4.h: `completed` is not `verified`; `zero` trades verification for speed; and §5 table: any SSD/NVMe where contract says "no prior LBA can be read from spare area" is not sufficient with overwrite — consult the manufacturer about supported coverage for the exact model, or use qualified destruction if required assurance cannot be established. Additional Beamo passes do not fix inaccessible flash coverage, and Beamo does not certify a vendor process.
*T+0:15* Customer pushes: "Just say certified sanitized." L1 uses consistent-language table §8 of `docs/storage-and-controller-limits.md`: must say "overwrite … Not a formal certificate" and must not say "sanitize/certified/DoD/NIST …" (pinned by `tests/test_storage_limits.py` + `tests/test_ui_system.py`). Escalates to release manager only to record the stop-request, not to issue a certificate.
*T+0:25* Customer agrees to destroy the batch instead; L1 provides destruction manifest suggestion and notes physical destruction row in §5.
*Gap found & fixed:* Follow-up added to this doc's §4.h snippet showing the exact `verification.requested: off, verified: false, outcome: completed` line to paste. Also added reminder in §9 that a "please certify my quick-zero NVMe batch" request is never a certificate issuance — stop-ship does not apply (no release defect) but the language quarantine does: no staff may hand-edit `result.json` to add `certificate`.

Timing summary for all three walks: first response <15 min via template, fake-fixture repro <10 min, QEMU not needed (all three were diagnosable via `lsblk/MOUNT` fixtures). No host-disk passthrough at any step. The three gaps above are closed in this same doc revision.

---

## 8. Release rollback, artifact quarantine, and stop-ship criteria

### 8.a How to know a release is bad

A release is suspect if any of:

- `test_boot_exclusion_fails_closed` negative test stops failing (gate in `docs/ci.md`).
- `result.json` shows a host disk (e.g. `boot_device` equals `device`, or `boot_device_in_selectable` regression) in QEMU evidence `wizard-exercise.txt` or `nwipe-boundary.txt`.
- Evidence shows `certificate`/`compliant` fields (forbidden by `tests/test_storage_limits.py`).
- ISO `sha256` mismatch between `dist/beamo-wipe-*.iso` and `dist/*.iso.sha256` + `manifest.json.sha256` and the published `SHA256SUMS` in `gs://beamo-wipe_cloudbuild/releases/<BUILD_ID>/` and GitHub release sidecars.
- Manifest `pinned nwipe commit 6082bde060091e66365d852a1877f2ee80c67105` or `__version__` drift from `src/beamo_wipe/__init__.py` (currently `0.2.2`; check `python -m pytest tests/test_live_image.py::test_staged_chroot_package_matches_src`).
- QEMU preflight aborts on host-backed device.

### 8.b Immediate actions (page release manager)

1. **Quarantine.** Mark the GitHub release `prerelease`/`draft` and add note "Do not flash — pending verification." Do not delete the `gs://…` objects immediately; they are evidence. Add a `QUARANTINE.txt` alongside with `BUILD_ID` + reason hash.
2. **Stop-ship.** Hold `scripts/build-iso.sh` / `cloudbuild.yaml` promotion until the accountable engineer clears the manifested diff (`git diff HEAD packaging/live/config/{bootstrap,binary} src/beamo_wipe/__init__.py`).
3. **Notify.** Post to the shared checkout channel and to the support queue header: "Beamo Wipe <version> quarantined — do not guide customers to flash it. Support follows this runbook §4.i and only uses the prior SHA until cleared."
4. **Rollback.** The designated prior stable ISO is `beamo-wipe-0.2.0-amd64.iso` hash `62437ec152a5b2ffc7c89fc503a7659d561c32699376a8851ab838f665491c74` mirrored in the release manifest's `prior stable` row and `docs/release-verification.md`. Guidance to customers reverts to that hash. The rollback is `git revert <quarantined commit>` or `git checkout <prior tag>` + fresh Cloud Build `BEAMO_WIPE_VERSION=... ./scripts/build-iso.sh` with manifest regeneration `scripts/generate-release-manifest.sh`. Verification: `sha256sum -c dist/*.sha256`, `isoinfo -d` `CD001`, `verify_evidence_checksum()`, full `pytest -q -k "not tk_runtime"` (see §10).
5. **Post-mortem.** After clearing, append a backlog finding `BF-0xx` row to `docs/compatibility-matrix.md` §11 exactly as the existing `BF-001…009` are recorded, with symptom, hash, and fix commit.

### 8.c Stop-ship release criteria (what must be true before the next promo)

- Full verification gate green: `python3 -m ruff check`, `python -m py_compile src/beamo_wipe`, `python3 -m pytest -q -k "not tk_runtime"` (fake-device), `BEAMO_WIPE_NO_OPEN=1 ./preview --web` + `web-preview/index.html` 54K, `scripts/build-iso.sh` on isolated x86_64 (or Cloud Build) with `CD001` + `≥80 MiB` + manifest + sidecars, `scripts/qemu-verify.sh` with disposable qcow2 preflight re-checked before each destructive assertion, and `verify_manifest.py` `verified true`.
- No forbidden claim regression (`tests/test_ui_system.py` + `tests/test_copy.py` + `tests/test_storage_limits.py`).
- Stages `packaging/live/config/includes.chroot/usr/lib/python3/dist-packages/beamo_wipe/` exactly match `src/beamo_wipe/` (`python -m pytest tests/test_live_image.py::test_staged_chroot_package_matches_src`).

The release manager must not `publish, release, promote, or distribute an ISO` without separate explicit operator authorization (non-negotiable gate).

---

## 9. Explicit prohibitions for support and for any reproduction

Support, the customer, and the engineer **must not**:

| Prohibited | Why |
|---|---|
| Disable boot-media exclusion, set `BEAMO_WIPE_BOOT_DEVICE`, or add a manual `--exclude` of something other than the identified boot, to "make the list appear" | Fails open — `discover.py` correctly refuses to list when uncertain; the correct help is §4.d |
| Skip `owner_ok`, hand-type token, or shorten the 5 s delay (`COUNTDOWN_S`) | Ownership and token are `safety:` gates (tests `test_wizard_flow.py`, `test_confirmation_gates.py`); short delay is the "last chance to stop" copy |
| Pass `--force` to `nwipe` | `nwipe_runner.py: validate_argv` forbids it; it hides the mounted/in-use truth that §4.g diagnoses |
| Run `nwipe` on a `qemu-img info` not equal to the disposable `/tmp/beamo-wipe-target.qcow2`/`raw` just created, or on `lsblk` `TYPE disk` that is the host `nvme0n1`/`sda` | Prevents wrong-disk destruction; §6.c requires `sha256sum` + `findmnt` + `losetup -j` re-check immediately before each `nwipe` invocation |
| `dd`, `hdparm --security-erase`, `nvme format --ses`, or `shred` a real customer disk from the support machine | Those tools are for vendor sanitize per customer's own model with their own authorization and their own host with no host-disk passthrough; they are not run by Beamo support as "help me wipe my work PC remotely" |
| Target a partition (`sda1`, `nvme0n1p1`) or `sr0`/`nbd*` | `safety.py: normalize_whole_disk` rejects partitions/`sr0`/`nbd*`; UI never offers them; evidence `device.path` is whole-disk only |
| Collect a serial into a public issue without customer consent | Privacy rule §3 |

When a customer asks for any of the above, reply with the linked decision tree and offer the next verifiable step.

---

## 10. Checks you can run right now (no real wipe)

```bash
# Fake-device repro (always first)
BEAMO_WIPE_DRY_RUN=1 python3 -m pytest -k "not tk_runtime"   # fast gate
python3 -m pytest tests/test_storage_limits.py tests/test_copy.py tests/test_ui_system.py -v
BEAMO_WIPE_NO_OPEN=1 ./preview --web && ls web-preview/index.html
grep -c "Not a formal certificate" web-preview/index.html     # SSD footer in gallery
python3 -m pytest tests/test_evidence.py -v                  # outcome truth

# Build/manifest gate (needs Docker amd64, not on this Mac's TCG)
# BEAMO_WIPE_VERSION=0.1.1 ./scripts/build-iso.sh && sha256sum dist/beamo-wipe-*.iso
# python -m beamo_wipe.release_manifest verify  dist/beamo-wipe-0.1.1-amd64.manifest.json

# Isolated QEMU gate (needs isolated x86_64, see §6.c and docs/vm-test.md)
# BEAMO_WIPE_VERSION=0.1.1 ./scripts/qemu-verify.sh  # abort on Darwin or existing target
# Evidence then in /tmp/beamo-wipe-qemu-evidence/*.txt + sidecars, with untuned-physical note
```

All three spies prove no real nwipe on the support host: `NwipeRunner.start` raises `SafetyError("Refusing to exec nwipe in preview or dry-run.")`; `DryRunRunner` fakes `WipeResult`; `subprocess.Popen` spy in `test_nwipe_runner.py` asserts `pass_fds`, `cwd="/"`, `shell False`, `start_new_session True`.

---

## 11. Change control for this runbook

This doc is versioned with the wrapper (`1.1` for `0.2.2`) and reviewed with `docs/storage-and-controller-limits.md` and `docs/compatibility-matrix.md` on each release or when the pinned nwipe commit, Debian base, or method mapping changes. Update `Version / Next review` at the top, `docs/compatibility-matrix.md` §15 changelog, and `tests/test_runbook.py` (below) in the same commit; CI (`test_ui_system` + `test_copy` + `test_storage_limits` + `test_runbook`) must still pass before push.

---

*Verification before merge: every branch above either collects evidence or gives guidance without weakening a gate, every nwipe log marker has a corresponding evidence outcome row, no file in `src/ docs/ helper/` asserts guaranteed recovery impossibility outside a "forbidden" list, and the three fake-fixture-first walk-throughs are reproducible without QEMU.*
