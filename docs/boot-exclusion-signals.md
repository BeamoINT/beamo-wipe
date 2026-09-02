# Boot-media exclusion — signal map (fail-closed)

> Companion to `docs/compatibility-matrix.md` matrix v1.0. This file maps **every signal** the wizard consults to decide *which disk is the live USB* and *which disks are wipe candidates*, and where adversarial fixtures prove uncertainty → zero targets.

Status: Beamo Wipe 0.1.1, nwipe 0.42. All paths below are traced to executable code; tests and fixtures are listed.

---

## 1. Signal inventory

### 1.1 lsblk fields (`LSBLK_COLUMNS` in `src/beamo_wipe/discover.py:79`)

| Field | Source | How used | Fail-closed if |
| --- | --- | --- | --- |
| `NAME` | `/usr/bin/lsblk -J -b -o …` | `name` → `Disk.name`, `_clean`, `KERNEL_NAME_RE`, `HIDDEN_NAME_RE`, `WHOLE_DISK_RE` input; fallback for `path` | missing/empty → `path` becomes `/dev/<name>` or empty; empty name → hidden via `should_hide` |
| `PATH` | lsblk | `Disk.path`, `node_path`, `parent_disk_path`, `assert_not_boot`, `normalize_whole_disk` alias set | missing → synthesized `/dev/<name>`; malformed → `SafetyError` in `normalize_whole_disk` |
| `SIZE` | lsblk | `size_bytes` → `size_gb_label`, `disk_identity`, `assert_size_unchanged`, `is_wipeable_disk` (≤0 → not wipeable) | `null`/empty/0 → `_as_int` 0 → hidden via `is_wipeable_disk`; float string handled via `float()` |
| `TYPE` | lsblk | `disk` vs `rom` vs `part` vs `loop` vs `ram`; `disk_nodes`, `HIDDEN_TYPES`, `should_hide`, `_node_type` | `loop`/`ram`/`rom` hidden unless it is the identified boot `rom`; unknown → hidden (`type != disk`) |
| `TRAN` | lsblk | `classify_kind`/`classify_bus`, `REMOTE_BUS_TOKENS` (`iscsi/fc/nbd/nvmeof`), `_looks_like_live_medium` (`tran==usb`) | missing → `bus other`, kind via `rota`; `iscsi`/`fc` → `is_remote_disk` → not wipeable |
| `ROTA` | lsblk | `classify_kind` HDD vs SSD via `_as_bool` | missing/`null` → `UNKNOWN` |
| `MODEL` | lsblk | `Disk.model` → `display_name`, `disk_identity[3]` | `null`/empty → fallback to `label` or `"Unknown model"` |
| `SERIAL` | lsblk | `Disk.serial` → `confirm_spec` token, `disk_identity[1]`; `_first_descendant_field` fallback | missing/null → `""`; affects token chain; change → `assert_disk_identity` fail |
| `RM` / `HOTPLUG` | lsblk | Parsed but **not** used for boot exclusion (present for completeness); `is_boot` not derived from RM | never decides boot; adversarial fixture proves no hidden bypass via RM |
| `MOUNTPOINT` / `MOUNTPOINTS` | lsblk | `_node_mountpoints` → `Disk.mountpoints` → `is_protected_mountpoint`, `has_any_mount`, `is_boot` via mount | `/` or `/run/live` etc → `is_boot` forced true; `has_any_mount` → not wipeable |
| `LABEL` | lsblk | `_volume_label`, `labels_for`, `BOOT_LABELS`, `FIRMWARE_LABELS`, typed source resolver | missing → `""`; duplicate `BEAMO_WIPE` → fail-closed duplicate; `EFI` filtered when real label exists |
| `FSTYPE` | lsblk | Not directly used for boot decision (present) | — |
| `VENDOR` | lsblk | `Disk.vendor` → `disk_identity[5]` | missing → `""`; change → identity fail |
| `PKNAME` | lsblk | `parent_disk_path` partition→disk via `pkname` match | missing → fallback to `parent` node or alias scan |
| `UUID` | lsblk | Typed source `_resolve_typed_source` `UUID`, `disk_identity` not but used for mount resolution | duplicate UUID → `found` list len>1 → resolver returns `None` → fail-closed |
| `WWN` | lsblk | `Disk.wwn` → `disk_identity[4]` | missing → `""`; duplicate → identity still per-disk but WWN change triggers fail |
| `PARTUUID` | lsblk | Typed source `PARTUUID` | duplicate → fail-closed |
| `PARTLABEL` | lsblk | Typed source `PARTLABEL` | duplicate → fail-closed |

Hidden-name regex: `HIDDEN_NAME_RE = ^(loop|ram|zram|sr|fd|mmcblk\d+(boot\d+|rpmb))` — adversarial `lsblk_unusual_controllers.json` proves `mmcblk0boot0` never appears as target.

Live-name regex: `LIVE_NAME_RE = (live|casper|overlay)` — names containing `live` are hidden unless boot.

### 1.2 Mount sources (live medium)

- **Constants** `LIVE_MOUNTS` (6 paths): `/run/live/medium`, `/lib/live/mount/medium`, `/run/initramfs/live`, `/cdrom`, `/mnt/live`, `/live/image`, `/run/live/fromiso`, `/lib/live/mount/fromiso`
- **Findmnt** (`/usr/bin/findmnt -n -o SOURCE <mountpoint>`) via `_run_findmnt` + `CLEAN_SUBPROCESS_ENV` (no `LD_PRELOAD`, absolute path only `LSBLK_BINARIES`/`FINDMNT_BINARIES`) — adversarial: non-zero exit → ignored (`test_findmnt_nonzero_stdout_is_ignored`).
- **Mountinfo** (`/proc/self/mountinfo`) via `read_mountinfo_sources` / `parse_mountinfo` / `_mountinfo_unescape` → `live_medium_is_mounted` requires `/dev` or typed source or `KERNEL_NAME_RE` on a live mountpoint; `tmpfs`/`overlay` → false.
- **Normalization** `normalize_mount_source` — strips `[deleted]`, promotes bare `sda1` → `/dev/sda1` only if `KERNEL_NAME_RE` matches; `overlay` stays `overlay` (adversarial).
- **Typed sources** `LABEL=`, `UUID=`, `PARTUUID=`, `PARTLABEL=` via `_split_typed_source` + `_dev_disk_typed_source` (`/dev/disk/by-uuid/` with `\xHH` decode) → `_resolve_typed_source` requires *unique* parent disk; duplicate → `None` (fail-closed).
- **Conflict rule** `identify_boot_path` — mount hits are ground truth; `env_boot` must equal mount hit or → `None`; unresolved typed source with live mount present → `None` (no label fallback).

### 1.3 Parent / alias / symlink / partition signals

- `parent_disk_path(path, blockdevices)` — alias set via `_path_aliases` (`path` + `os.path.realpath(path)`); loops → `None`; `type loop` never boot; traverses `paths_under` and `PKNAME`/`parent` fallback. Adversarial symlink fixtures and monkeypatched `realpath` tests (`test_select_disk_refuses_boot_alias`, `test_same_rdev_is_treated_as_boot`) prove `/dev/disk/by-id/usb-…` alias and `st_rdev` equality are treated as boot.
- `_is_loop_path` — `^loop` name or node type loop.
- `WHOLE_DISK_RE` — `^/dev/(sd[a-z]+|hd[a-z]+|vd[a-z]+|xvd[a-z]+|dasd[a-z]+|nvme\d+n\d+|mmcblk\d+|sr\d+)$`; rejects `nbd*`, partitions (`sda1`, `nvme0n1p1`), whitespace/comma; `allow_optical` separates `sr` as boot vs target.
- `_is_partition_of` — `sda1` is partition of `sda`; `nvme0n1p1` is partition of `nvme0n1` (p+digits); `nvme0n11` is *not* partition of `nvme0n1` (sibling namespace).
- `normalize_whole_disk` — requires `/dev/` prefix, `realpath` stays under `/dev/`, whole-disk regex, optional allow_optical; symlink via `lstat` → `SafetyError`.
- `disk_identity` tuple: `(realpath, serial, size_bytes, model, wwn, vendor)`; `assert_disk_identity` re-reads `selectable_disks` and compares full tuple; any change → fail.

### 1.4 Removable flags

`RM`/`HOTPLUG` are *not* boot signals (adversarial fixture `lsblk_adversarial_rm_hotplug.json` shows opposite values do not change `is_boot` or `selectable`). Boot is only `BEAMO_WIPE` label on `usb`/`rom`, mount, cmdline, or typed source, plus protected-mount override. This prevents a `RM=0` internal USB bridge from hiding the live stick.

### 1.5 Metadata refresh (TOCTOU)

- `Wizard.confirm_erase` when not preview/dry-run: `discovery = (self._rediscover or discover)()` → re-reads `lsblk`+mounts+cmdline; `if not boot_identified or boot is None → REDISCOVER_ERROR`; `assert_boot_excluded` + `assert_disk_identity` on fresh discovery; re-selects `disk` from fresh `selectable` by `realpath`; `assert_ready_to_wipe` re-checks `is_wipeable_disk`, `has_protected_mount`, `token_matches`, `countdown`, `normalize_whole_disk`, `assert_not_boot`, `block_rdev`/`assert_size_unchanged`, `logfile_for` + `assert_log_not_on_target` + `_log_filesystem_is_target`.
- `assert_size_unchanged` compares `block_size_bytes` from `/sys/block/<name>/size` vs `disk.size_bytes` (preview skips; live requires exact match).
- `block_rdev` checks `lstat` is `S_ISBLK` and not symlink; `device_rdev == 0` at confirm time → `NwipeRunner.start` raises `"identity"` for real engine (test `test_zero_confirm_rdev_is_fail_closed_for_real_engine`).

All failures set `wizard.error` and stay on `LAST_CHANCE`; `runner.start` is never called; `build_nwipe_argv` is never reached.

---

## 2. Adversarial fixtures (fake lsblk JSON, never host disks)

Existing: `lsblk_same_size`, `lsblk_no_boot`, `lsblk_only_boot`, `lsblk_vm_iso`, plus `missing_metadata`, `duplicate_metadata`, `unusual_controllers`, `multi_mixed`, `sata_bridge`.

New for this proof:

| Fixture | Adversarial dimension | What it proves |
| --- | --- | --- |
| `lsblk_adversarial_null_fields.json` | `NAME null`, `PATH null`, `SIZE null/""`, `TYPE null`, `TRAN null`, `ROTA null`, `MODEL null`, `SERIAL null`, `LABEL null`, `UUID null` | `_clean`/`_as_int`/`_as_bool` handle null; null size → 0 → not wipeable; null path → synthesized `/dev/<name>`; null type → hidden |
| `lsblk_adversarial_duplicate_wwn.json` | Two disks `sda`/`sdb` same `WWN 0x5000…` + same size/model but distinct serial | Duplicate WWN does not collapse identity; `disk_identity` distinguishes by serial+wwn; token chain still disambiguates |
| `lsblk_adversarial_duplicate_uuid.json` | Two partitions `sda1`/`sdb1` same `UUID` | `_resolve_typed_source` with `UUID=` finds 2 parents → returns `None` → typed mount fails closed |
| `lsblk_adversarial_partitioned.json` | `sda` with `sda1/sda2`, `nvme0n1` with `nvme0n1p1/p2`, `mmcblk0` with `mmcblk0p1`, plus `sda1` type `part` with `BEAMO_WIPE` label | Only whole disks selectable; partitions never `selectable`; `BEAMO_WIPE` on partition resolves to parent disk; child mountpoints correctly bubble |
| `lsblk_adversarial_rm_hotplug.json` | `sda` `RM 1 HOTPLUG 1` sata, `sdb` `RM 0 HOTPLUG 0` usb boot | RM/HOTPLUG do not decide boot or wipeable; `is_boot` only via label/mount |
| `lsblk_adversarial_udev_encoded.json` | `sda` with `/dev/disk/by-label` `BEAMO\x20WIPE` encoding, child label `BEAMO WIPE` | `_udev_decode` correctly decodes `\x20` → space; resolver still requires live-medium check |
| `lsblk_adversarial_stale_sata_beamo.json` | `sda` `tran sata` with child `BEAMO_WIPE`, `sdb` `tran usb` with `DEBIAN` label (no BEAMO_WIPE) | Label on `sata` is not live medium → `found []` → fail-closed (proves stale internal label not mis-identified) |
| `lsblk_adversarial_env_mount_conflict.json` | Used via payload: `env_boot /dev/sda` vs `mount_sources /dev/sdb` | Conflict → `identify_boot_path` returns `None` → fail-closed |
| `lsblk_adversarial_symlink.json` | Payload with `sda` path `/dev/sda` but alias `/dev/disk/by-id/usb-Beamo_123` via monkeypatched `realpath` | Alias equality → boot exclusion via `realpath` and `st_rdev` |

Inline payloads also cover malformed JSON variants (`blockdevices` as string, missing `blockdevices`, non-list children).

---

## 3. Fail-closed proof (what tests assert)

For every adversarial case:

- `discover(...).boot_identified == False` or `boot is None` or `selectable == ()` **and** `error` contains `CANNOT_IDENTIFY` when boot uncertain.
- `Wizard._enter_pick()` → `screen == PICK_BLOCKED`, `error` set to `IDENTIFY_ERROR`, `selectable == ()`.
- `Wizard.select_disk(boot.path)` → `selected is None`.
- `Wizard.continue_pick()` / `confirm_erase()` → stays on same screen, `runner.start` not called, `build_nwipe_argv` not reached (spy asserts `Popen` not called, `pass_fds` not set).
- `assert_boot_excluded` raises `SafetyError` when called on uncertain discovery (spy).
- TOCTOU: `rediscover` returning changed `serial`/`size_bytes`/`wwn`/`vendor`/`model`/`realpath`/`mount`/`boot`/`topology` → `confirm_erase` sets `error` containing `identity` or `safe list` or `REDISCOVER_ERROR`, stays `LAST_CHANCE`, `runner.start` call count 0.

Spies/fakes: `DryRunRunner` (never real `nwipe`), `FakeRunner` with `start` counter, `monkeypatch.setattr(subprocess.Popen, fake_popen)` that raises if called, `monkeypatch.setattr(os.lstat, ...)` for symlink/rdev, `monkeypatch.setattr(os.path.realpath, lambda p: alias)` for symlink, `tmp_path` for log isolation.

Destructive validation (if any) would run only on isolated x86_64 Linux VM with `qemu-img create -f qcow2 /tmp/beamo-wipe-target.qcow2 10G` and `qemu-system-x86_64 -enable-kvm -cdrom dist/*.iso -drive file=/tmp/...qcow2,if=virtio`, image sha `8a531d…`, re-check `block_rdev` and `block_size_bytes` before `Popen`; abort on mismatch. Not executed on dev host.

---

## 4. Coverage indices

- `tests/test_boot_exclusion_fails_closed.py` — dedicated adversarial e2e (this proof).
- `tests/test_discover.py` — 35+ unit cases for each parser branch.
- `tests/test_compatibility_matrix.py` — 23 ST/BM cases.
- `tests/test_security_hardening.py` — remote, mount, log, symlink, rdev.
- `tests/test_wizard_flow.py` — happy path, countdown, rediscover identity change, boot alias.
- `tests/test_safety.py` — boot exclusion, token, live.

Run: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest -k "not tk_runtime"` (local) and `xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest` (hosted gate); `BEAMO_WIPE_NO_OPEN=1 ./preview --web` + `./preview --console </dev/null` smoke.
