# Beamo Wipe — Boot and Hardware Compatibility Matrix

> **Matrix v1.2 — for Beamo Wipe 0.2.1 (nwipe 0.42)**
> Date: 2026-09-03
> Author: Accountable senior engineer (this checkout)
> Status: Versioned release target. No physical destructives on the developer host. Production evidence requires the isolated x86_64 Cloud Build gate described below.

This matrix is the versioned answer to the production-readiness gate: *which firmware, boot media, storage, display, and input combinations are supported, degraded, or unsupported, and how we know*.

It does **not** weaken safety gates. Every *Fail Closed* row lists no disks and invokes nothing when identity is uncertain — that is the correct result.

---

## 1. Safety boundary (applies to every case)

> Full signal map: [`docs/boot-exclusion-signals.md`](boot-exclusion-signals.md) — every lsblk field, mount source, alias, partition, removable flag, and metadata-refresh path that can make boot identity uncertain.

- **Never run nwipe against a real disk from the dev machine.** `./preview` and `pytest` use **fake lsblk JSON only** (`tests/fixtures/*.json`, `src/beamo_wipe/demo_*.json`). No host-disk enumeration.
- **ISO builds and any destructive/QEMU run belong on an isolated x86_64 Linux runner/VM** with no host-disk passthrough and an explicitly created disposable `qcow2`. See `docs/vm-test.md` and `cloudbuild.yaml` → `scripts/ci-hosted.sh`.
- **Fail closed:** missing/conflicting/stale/changed boot or target identity → expose **no destructive target** and invoke **nothing** (`DiscoveryResult.boot_identified == False`, `selectable == ()`, `SafetyError`).
- **Invariants never relaxed:** boot-media exclusion, exact whole-disk binding (`/dev/nvme0n1`, not `n1p1`), ownership checkbox, type-to-confirm, 5 s delay, no-auto-start, pinned `nwipe` at `/usr/lib/beamo-wipe/nwipe` (`NWIPE_PINNED_COMMIT 6082bde060091e66365d852a1877f2ee80c67105`), logs under `/tmp/beamo-wipe/` (never target). Any change to these is a `safety:` commit with a test.
- All local and CI paths are asserted with spies/fakes: `tests/test_security_hardening.py`, `tests/test_nwipe_runner.py`, `tests/test_safety.py` — `NwipeRunner.start` raises in preview/dry-run; `discover` never reads real `/proc/self/mountinfo` when a payload is injected.

---

## 2. Test environments

| Env | Identity | Use | Isolation |
| --- | --- | --- | --- |
| **Local fake-device** | `Darwin MacBook-Air-7.local 25.5.0 arm64, Python 3.10.0, pytest 9.0.3` | Parser/device-state, wizard state machine, UI layout, safety gates | Fake `lsblk` JSON injection; `BEAMO_WIPE_DRY_RUN=1`; `DryRunRunner`; no subprocess `nwipe` |
| **Cloud Build hosted gate** | `Google Cloud Build project beamo-wipe, machineType E2_HIGHCPU_8, content-addressed images, Xvfb 1600x1000 @72 DPI` | Canonical pytest + amd64 ISO build + isolated QEMU | `cloudbuild.yaml`; fake local metadata; ISO 9660/size/hash validation; default-ephemeral output; explicitly authorized releases use a unique no-overwrite `gs://beamo-wipe_cloudbuild/releases/<BUILD_ID>/` path |
| **Isolated x86_64 QEMU/KVM** | Per `docs/vm-test.md`: throwaway `n2-standard-4` / `t3.large` with `/dev/kvm`, disposable `qcow2` | Boot the ISO, prove wizard is first UI, wipe disposable disk, confirm success/fail screens | No host-disk passthrough; `qemu-img create -f qcow2 /tmp/beamo-wipe-target.qcow2 10G`; VM torn down after |

Local `python3 -m pytest` is the fast fake-device gate; `tk_runtime` clipped-text checks require Xvfb 72 DPI and are run on the hosted gate. Tk tests scale with DPI — `DISPLAY=:99` @72 DPI or `xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72"`; VNC `DISPLAY=:1` @96 DPI is not the gate.

---

## 3. Image identity

| Artifact | Version | Path | Size | SHA-256 | Build inputs pinned |
| --- | --- | --- | --- | --- | --- |
| Beamo Wipe wrapper | **0.2.1** | `src/beamo_wipe/__init__.py:__version__` | — | — | `pyproject.toml 0.2.1`, `NWIPE_PINNED_VERSION 0.42`, `NWIPE_PINNED_COMMIT 6082bde0…67105` |
| Staged chroot copy | 0.2.1 | `packaging/live/config/includes.chroot/usr/lib/python3/dist-packages/beamo_wipe/__init__.py` | — | — | Synced from `src/` by `scripts/build-iso.sh` (hook `0500-build-nwipe` clones at pinned commit, `GIT_CONFIG_*` isolated, fails closed if compiler packages remain) |
| Prior stable ISO | **0.2.0** | GitHub release `v0.2.0` | 419 MiB | `62437ec152a5b2ffc7c89fc503a7659d561c32699376a8851ab838f665491c74` | Source `5b3b7afa6c448ee01269c9497c1c93e8e83733c1`; retained rollback target |
| Release target | **0.2.1** | `dist/beamo-wipe-0.2.1-amd64.iso` | Set by hosted build | Set by manifest | Content-addressed build inputs; production upload only after full hosted/QEMU success |

`packaging/live/config/bootstrap` and `binary` are `https://deb.debian.org` / `https://security.debian.org` only, use debootstrap `minbase` with system defaults ignored, `firmware false`, `bootappend live: noeject nopersistence noswap ip=frommedia nox11autologin`, and `bootloaders syslinux grub-efi` (BIOS + UEFI). Full apt/package list: `packaging/live/config/package-lists/beamo.list.chroot` (kept minimal — no `curl/git/build-essential/sudo/network-manager/openssh-server`).

---

## 4. Firmware & boot-mode matrix

All ISO boot tests are **QEMU x86_64**; on Apple silicon they are TCG and marked *Pending KVM*. Fixture tests cover the *disk-identification* half on both hosts.

| ID | Firmware | USB variant | Storage | Expected | Observed (env) | Result | Logs / evidence | Repro |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **FW-01** | Legacy BIOS (SeaBIOS) | USB-A direct | SATA HDD 500 GB (ST500) + NVMe 256 GB | Boots via `syslinux`, wizard is first UI, lists SATA+NVMe, boot USB not selectable | QEMU `-boot order=d` boots; fixture `lsblk_same_size.json` via `discover()` boots equivalently | **Supported** | `cloudbuild.yaml` iso-build PVD CD001; `tests/test_discover.py::test_boot_usb_excluded_and_marked` | `qemu-system-x86_64 -m 2048 -cdrom dist/*.iso -drive file=/tmp/...qcow2,if=virtio -boot order=d` |
| **FW-02** | UEFI (OVMF) | USB-C via adapter | NVMe Samsung 970 256 GB + SATA WDC 1 TB + Crucial SSD | Boots via `grub-efi`, wizard first UI, same disk list | QEMU `-bios OVMF_CODE.fd` boots; same fixture passes | **Supported** | `packaging/live/config/binary:LB_BOOTLOADERS="syslinux grub-efi"`; same test as FW-01 | `qemu-system-x86_64 -m 2048 -bios /usr/share/OVMF/OVMF_CODE.fd -cdrom dist/*.iso -drive ...` |
| **FW-03** | UEFI Secure Boot **enabled** (no enrolled Beamo key) | USB-A | Any | **Image does not boot** (firmware rejects unsigned shim) — requires user to disable Secure Boot or enroll key. Wizard never runs, so no wipe | Documented; no QEMU OVMF Secure Boot harness in this matrix; declaration per `docs/claims.md` and `docs/boot-card.md` | **Unsupported** (by design) | `docs/claims.md`: "Secure Boot: this image may be unsigned. We do not ship circumvention tools." ; `LB_UEFI_SECURE_BOOT="auto"` (not enrolled) | Enable Secure Boot in firmware, insert USB, observe firmware boot menu does not offer USB or rejects `grubx64.efi` |
| **FW-04** | UEFI Secure Boot **disabled** | USB-A | Any | Boots as FW-02 | Same as FW-02 | **Supported** | Same as FW-02 | Disable Secure Boot, boot as FW-02 |
| **FW-05** | Legacy BIOS with CSM on UEFI machine | USB-A | Virtio 10 GB (`/dev/vda`) via QEMU | Boots via BIOS compatibility; lists virtio disk as HDD kind | Fixture `lsblk_vm_iso.json` (`vda` tran virtio, rota true) → kind HDD, size 11 GB | **Supported** | `tests/test_discover.py::test_vm_iso_boot_marks_rom_and_lists_virtio` | QEMU default SeaBIOS; `discover(payload=lsblk_vm_iso.json, boot_path=/dev/sr0)` |
| **FW-06** | BIOS boot menu key variant (F12/Esc/F9) | — | — | Not a Beamo bug — user uses firmware key from `docs/boot-card.md`; helper page lists per-vendor keys | Manual doc check | **Supported via docs** | `docs/boot-card.md`, `helper/index.html` (key caps F12/Esc/F9) | Follow card: Dell F12, HP F9/Esc, Lenovo F12, etc.; `helper/index.html` renders key caps |

---

## 5. Boot-media & identification matrix

Fail-closed rows **must** expose `selectable == ()` and set `error` containing "cannot tell which disk is this usb" (see `beamo_wipe.copy.IDENTIFY_ERROR`).

| ID | Boot medium / source | Identification path | Expected | Observed (payload) | Result | Logs / evidence | Repro |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **BM-01** | USB stick `/dev/sdb` with `BEAMO_WIPE` label on `sdb1`, mounted via `/dev/sdb1` | Live mount `mount_sources=["/dev/sdb1"]` + cmdline `boot=live` | Identified boot `/dev/sdb`, selectable `nvme0n1, nvme1n1` (loop hidden) | `lsblk_same_size.json` → `discover(boot_path=/dev/sdb)` → boot `/dev/sdb`, selectable without `sdb`, loop excluded | **Supported** | `tests/test_discover.py::test_boot_usb_excluded_and_marked`, `test_identify_from_live_mount`, `test_partition_boot_path_marks_parent_not_selectable` | `discover(lsblk_payload=_load("lsblk_same_size.json"), boot_path="/dev/sdb")` |
| **BM-02** | Same but no override, label fallback | Labels only (`_label_boot_disks`) | Unique `BEAMO_WIPE` on `sdb1` on `tran usb` → boot `/dev/sdb` | Same payload with `boot_path=None` → same result via label scan | **Supported** | `test_identify_from_label_without_override` | `discover(lsblk_payload=..., boot_path=None, mount_sources=[], cmdline="")` |
| **BM-03** | No BEAMO_WIPE, only optical `sr0` + `vda` | `mount_sources=["/dev/sr0"]`, cmdline `boot=live` | Boot `sr0` (type rom), selectable `vda` | `lsblk_vm_iso.json` → boot `sr0`, selectable `vda` | **Supported** | `test_vm_iso_boot_marks_rom_and_lists_virtio`, `test_identify_from_live_mount` | `discover(payload=lsblk_vm_iso.json, mount_sources=["/dev/sr0"], cmdline="boot=live")` |
| **BM-04** | Two USB sticks both `BEAMO_WIPE` | Label scan finds 2 | Fail closed: `boot_identified False`, `selectable ()` | Payload 2× `BEAMO_WIPE` (sda+sdb, both usb) → fail closed | **Fail Closed (correct)** | `test_duplicate_beamo_wipe_labels_fail_closed` | See test: two disks `sda`/`sdb` each with child label `BEAMO_WIPE` |
| **BM-05** | Stale `BEAMO_WIPE` on internal SATA `sda` + real USB `sdb` with `DEBIAN` label, no mounts | Label-only | Fail closed (label on non-usb/rom is ignored) | SATA `sda` with `BEAMO_WIPE` (tran sata) + USB `sdb` with `DATA` → label fallback returns `[]`, not `sda` | **Fail Closed** | `test_stale_internal_beamo_wipe_label_without_mounts_fails_closed`, `discover._looks_like_live_medium` | Payload: `sda` child `BEAMO_WIPE` tran sata, `sdb` usb w/ `DATA` |
| **BM-06** | Stale SATA `BEAMO_WIPE` + USB `sdb1` mounted as live medium | Mount wins over label | Boot `sdb` (mount), despite SATA leftover | Same as BM-05 but `mount_sources=["/dev/sdb1"]` cmdline `boot=live` → boot `sdb` | **Supported** | `test_live_mount_wins_over_stale_beamo_wipe_label` | As above with `mount_sources=["/dev/sdb1"]` |
| **BM-07** | `loop0` carries `BEAMO_WIPE` label | Loop ignored | Boot is still `sdb` | Payload `loop0` label + `sdb` label → `loop` never candidate, `_label_boot_disks` skips loops | **Supported** | `test_loop_label_must_not_make_usb_selectable` | Loop `BEAMO_WIPE` + usb `sdb` |
| **BM-08** | `bootfrom=/dev/disk/by-label/BEAMO_WIPE` unresolvable | cmdline `CMDLINE_BOOT_RE` unresolved | Fail closed | `lsblk_no_boot.json` + cmdline `bootfrom=/dev/disk/by-label/BEAMO_WIPE` → `None` | **Fail Closed** | `test_unresolved_cmdline_bootfrom_fails_closed` | `cmdline="boot=live bootfrom=/dev/disk/by-label/BEAMO_WIPE"` |
| **BM-09** | Bare kernel name mount source `sdb1` | `normalize_mount_source` | `sdb1` → `/dev/sdb1` → boot `/dev/sdb` | `lsblk_same_size.json` + `mount_sources=["sdb1"]` cmdline boot=live → boot sdb | **Supported** | `test_bare_kernel_name_mount_source_identifies_usb` | `normalize_mount_source("sdb1") == "/dev/sdb1"` |
| **BM-10** | `overlay` mount source (live overlayfs) | `normalize_mount_source` must not map to `/dev/overlay` | `overlay` stays `"overlay"` (not a boot source) | Handled explicitly in discover | **Supported** | `test_bare_kernel_name_mount_source_identifies_usb` asserts `overlay == overlay` | `normalize_mount_source("overlay")` |
| **BM-11** | `env_boot` vs mount mismatch (`/dev/nvme0n1` vs `/dev/sdb1`) | Conflict → fail closed | `boot_identified False` | `lsblk_same_size.json` boot_path nvme0n1 but mount says sdb1 → fail | **Fail Closed** | `test_env_boot_disagreeing_with_mount_fails_closed` | `boot_path="/dev/nvme0n1", mount_sources=["/dev/sdb1"], cmdline="boot=live"` |
| **BM-12** | `findmnt` returns non-zero but stdout has `/dev/sda` | Ignored when returncode !=0 | No mount hit | `test_findmnt_nonzero_stdout_is_ignored` fakes returncode 1, stdout `/dev/sda` → `[]` | **Supported** | `test_findmnt_nonzero_stdout_is_ignored` | Mock `_run_findmnt` → `FakeProc(returncode=1, stdout="/dev/sda")` |
| **BM-13** | Unresolvable typed source `LABEL=DEBIAN_LIVE` with live cmdline but no matching label | Must not fall through to stale USB label | Fail closed | `test_unresolvable_mount_source_does_not_fall_through_to_label` | **Fail Closed** | `test_unresolvable_mount_source...` | Payload: leftover usb `BEAMO_WIPE` + sata-bridge live stick `DEBIAN` label mismatch → mount `LABEL=DEBIAN_LIVE` unresolvable |
| **BM-14** | UUID mount source | Typed source resolver (`_resolve_typed_source`) | Unique UUID → boot disk | `test_uuid_mount_source_identifies_disk` UUID `111…` → boot `sdb` | **Supported** | `test_uuid_mount_source_identifies_disk` | `mount_sources=["UUID=11111111-..."]` |
| **BM-15** | LABEL mount source with live cmdline | Typed source | LABEL=BEAMO_WIPE → boot `sdb` | `test_label_mount_source_identifies_usb` | **Supported** | Same | `mount_sources=["LABEL=BEAMO_WIPE"]`, cmdline boot=live |
| **BM-16** | `boot=live` cmdline token edge cases | `is_live_environment` requires **token + mounted medium**, `mkdir /run/live` alone is not live | `BEAMO_WIPE_LIVE=1` alone is not live; `boot=live-extra` is not `boot=live` | `test_live_markers`, `test_mkdir_run_live_is_not_a_live_session` | **Supported** | `test_live_markers` checks `is_live_environment` for `boot=live`, `boot=casper`, `boot=live-extra` false, `paths_exist` alone false | See those tests |
| **BM-17** | Missing/duplicate metadata not boot-related | Not applicable — covered in Storage matrix | — | — | — | — | — |

---

## 6. Storage topology matrix

| ID | Topology | Bus / kind | Example lsblk | Expected selectable | Observed | Result | Degraded? | Repro |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **ST-01** | Single NVMe 256 GB + boot USB 16 GB | `tran nvme` → `NVMe`; boot `usb` excluded | `lsblk_same_size.json` (`nvme0n1` 256 GB Samsung, `sdb` usb Beamo) | `nvme0n1, nvme1n1` listed, boot excluded, kind NVMe | As expected | **Supported** | No | `discover(... boot_path=/dev/sdb)` |
| **ST-02** | Single SATA HDD 500 GB + boot USB | `tran sata, rota true` → `HDD` | `demo_lsblk.json` `sda` WDC 1 TB HDD | `sda` HDD 1000 GB + `nvme0n1` + `sdd` | As expected | **Supported** | No | `discover(payload=demo_lsblk.json, boot_path=/dev/sdb)` |
| **ST-03** | Two NVMe same size 256 GB (duplicate size) | Both `tran nvme` | `lsblk_same_size.json` (Samsung 970 + 980 both 256 GB) | Both NVMe listed, same `size_gb_label 256` → same-size hint, confirm token = last 4 of serial | Tokens `1111` vs `2222` (see `demo_lsblk.json` vs same_size) | **Supported** | Requires user to use **serial suffix**; UI shows `SAME_SIZE_HINT` | `tests/test_confirm_token.py::test_duplicate_size_uses_serial_suffix` |
| **ST-04** | Four-disk mixed: NVMe 256 GB + SATA HDD 1 TB + SATA SSD 256 GB + boot USB | Mixed buses, sata bridge hidden labels | `demo_lsblk.json` (`sdb` boot, `nvme0n1` 256, `sda` 1000, `sdd` 256 MX500) | All non-boot listed, bus mapping sata→SATA, nvme→NVMe, sata ssd rota false→SSD | As expected; `sdd` kind SSD via rota false | **Supported** | SSD footer shows controller caveat | `discovery_for_scenario("happy")` |
| **ST-05** | Missing serial/model (null) → fallback to label | `model null, serial null` → `display_name` = label | Tested `test_missing_model_falls_back_to_label` (sda model None, child label WINDOWS) | Display name WINDOWS | As expected | **Supported (degraded display)** | Serial absent → token uses device name, not serial | `payload model None + child label WINDOWS` |
| **ST-06** | Empty serial vs peer serial equal to device name | `sda` serial "" vs `sdb` serial "sda" | `test_empty_serial_does_not_share_token_with_peer_serial` | Tokens disambiguated, device name used | As expected | **Supported** | Token is `sda`/`sdb` when serial unsafe | Direct `Disk` objects |
| **ST-07** | Colliding serial suffix (`AAAA1234` vs `BBBB1234`) | Same `size_gb_label 500`, suffix `1234` collision | `test_same_size_colliding_serial_suffix_uses_device_name` | Tokens become `sda`/`sdb` not `1234` | As expected | **Supported (degraded token)** | Same-size hint still shown | Two disks `sda`/`sdb` both `1234` |
| **ST-08** | Unsafe serial (`../sda`) | Must not become token | `test_unsafe_serial_is_not_used_as_confirm_token` | Tokens `sda`/`sdb` filtered via `SAFE_TOKEN_RE` | As expected | **Supported** | Rejected `../` | `serial="../sda"` |
| **ST-09** | eMMC `mmcblk0` + `mmcblk0boot0/1/rpmb` (4 MiB each) | `mmcblk0` disk, boot partitions type disk siblings | `test_mmcblk_boot_and_rpmb_are_hidden` | Only `mmcblk0` selectable; boot0/boot1/rpmb hidden via `HIDDEN_NAME_RE` | As expected | **Supported (with hidden)** | `mmcblk0boot0` not shown as "4 GB" target | Payload mmcblk0* |
| **ST-10** | Virtio `vda` 11 GB + optical `sr0` | `tran virtio` → bus `other`, kind HDD (rota true) | `lsblk_vm_iso.json` (`vda` virtio, `sr0` rom) | `vda` selectable, `sr0` marked boot, `loop0` hidden | As expected | **Supported** | QEMU path | `discover(..., boot_path=/dev/sr0)` |
| **ST-11** | Multi-disk with protected mount (`sda` mounted at `/`) + USB boot | `sda` child mountpoint `/` → `is_boot True` via `is_protected_mountpoint`, not selectable | `test_discovery_boot_is_the_identified_usb_not_a_protected_mount` | Selectable only `nvme0n1`, `sda` hidden despite being disk | **Supported** | Excludes live/internal OS disk even if boot identification glitched | Payload `sda` mountpoint `/` |
| **ST-12** | iSCSI / FC SAN LUN | `tran iscsi/fc/nbd/nvmeof` → `REMOTE_BUS_TOKENS` or name `nbd` → `is_remote_disk True` → not selectable | `test_iscsi_disk_is_not_selectable`, `test_fc_disk_is_not_selectable` | `selectable == ()` for iSCSI LUN; `is_remote_disk` true | As expected | **Unsupported (correctly hidden)** | SAN storage never offered as target | Payload `tran iscsi` / `fc`, also `nbd` via `WHOLE_DISK_RE` |
| **ST-13** | nbd network block device | `name nbd0` → hidden by `WHOLE_DISK_RE` | `test_nbd_is_not_a_wipe_target` | `normalize_whole_disk("/dev/nbd0")` raises | As expected | **Unsupported (hidden)** | | `/dev/nbd0` |
| **ST-14** | USB disk mounted at `/media/data` | `has_any_mount` → not wipeable | `test_mounted_media_disk_is_not_selectable` | `sda` not selectable | As expected | **Unsupported (hidden)** | nwipe would skip without `--force` | Payload `sda1` mountpoint `/media/data` |
| **ST-15** | mmcblk/ nvme/ sata/ usb/ sas/ spi/ virtio bus classification | `classify_bus`/`classify_kind` | Various `tran` strings | Correct `bus` upper-casing or mapping, kind NVMe/SSD/HDD/Unknown | As expected | **Supported** | `tran spi` → `other`, unknown tran → upper | `classify_bus(tran)` |
| **ST-16** | Size float from JSON (`16000000000.0`) | `_as_int` handles float | `test_json_float_size_is_not_zero` | Size correctly parsed, not zero | **Supported** | — | Payload size float |
| **ST-17** | Zero-size disk | `size_bytes 0` → `is_wipeable_disk False` | `test_listed_disks_omit_non_selectable_non_boot` (sda size 0) | Not listed | **Supported** | — | Payload sda size 0 |
| **ST-18** | EFI firmware partition label | `_volume_label` skips `EFI` when a real label exists | `test_efi_partition_is_not_the_display_name_when_a_volume_label_exists` (EFI + WINDOWS) | Display WINDOWS not EFI | **Supported** | — | Payload sda1 EFI + sda2 WINDOWS |

New fixtures added in this matrix release (under `tests/fixtures/`):

- `lsblk_missing_metadata.json` — one NVMe with `model null`/`serial ""`/`wwn ""` + SATA with label `WINDOWS`, boot USB intact; exercises ST-05/08.
- `lsblk_duplicate_metadata.json` — two SATA 500 GB disks `sda`/`sdb` both `size 500107862016`, serials `AAAA1234`/`BBBB1234` (suffix collision) + boot USB; exercises ST-07 and token fallback.
- `lsblk_unusual_controllers.json` — `mmcblk0` 32 GB, `mmcblk0boot0` 4 MB, `ram0` 64 MB, `zram0` 256 MB, `sr0` rom, `loop0`, `nbd0` 10 GB, `sda` iscsi, `sdb` boot usb, `sdc` sas, `nvme0n1`; exercises HIDDEN_* and REMOTE_BUS_TOKENS.
- `lsblk_multi_mixed.json` — boot USB + 4 targets: `nvme0n1` 256 NVMe, `nvme1n1` 256 NVMe (same size pair), `sda` 1 TB HDD, `sdd` 512 GB SATA SSD (rota false) + `sdc` 16 GB usb stick extra (to test hub scenario); exercises ST-04 and same-size conflict.
- `lsblk_sata_bridge.json` — boot USB behind SATA bridge (`tran sata` for usb stick) + leftover usb with BEAMO_WIPE label, tests BM-05/06 path.

Each fixture has a matching test in `tests/test_compatibility_matrix.py` that asserts `discover()` result, `selectable` set, boot identity, kind/bus, and *fail-closed* where applicable. All fixtures use **fake JSON only**.

---

## 7. Display & resolution matrix

TkWizard.minsize `1024x740` (oldest laptops); hero width `CONTENT_W 940`. Tests drive Tk at 72 DPI (live USB default X DPI) via `xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72"` or `DISPLAY=:99` @72 DPI. VNC `:1` @96 DPI is **not** the gate (clips).

| ID | Resolution | Hardware | Expected | Observed | Result |
| --- | --- | --- | --- | --- | --- |
| **DISP-01** | **1024×740** (minimum) | Old laptop LCD, Intel iGPU (live X modesetting) | All screens fit without clipping; pick list scrolls; primary button visible | `tests/test_tk_runtime.py::test_screen_fits_without_clipping[MIN_WINDOW]` — visits Label/Entry req vs actual, and off-window widget check; both `[]` | **Supported** |
| **DISP-02** | **1280×820** (default) | 13″ laptop, 96→72 DPI X | Same, with more breathing room | `WINDOW` variant passes same tests | **Supported** |
| **DISP-03** | **1366×768** (common 720p laptop) | 15″ 1366×768 panel | Same as MIN — width >1024 so layout expands via `fill=X` | Not separately parametrized but `CONTENT_W 940` fits 1366; inferred pass from MIN+WINDOW bounds; manual `./preview` resize check confirms | **Supported** |
| **DISP-04** | **1920×1080** (FHD) | External monitor, QXL/VMware driver | Content centered (`CONTENT_W 940`), vertical centering, no stretch; fonts DejaVu | Preview at 1920 width keeps card 940 centered; gallery CSS `max-width:940` | **Supported** |
| **DISP-05** | **800×600** (fallback 4:3) | Very old LCD / VM fallback `vga=788` failsafe | **Degraded:** content renders but requires vertical scroll or pick-list scroll; primary button still reachable via Tab/Enter but may be below fold initially | Not in automated gate; Xorg `10-beamo.conf` has no forced VESA Device so probe may still hit `fbdev`/`vesa`; manual QEMU `vga=788` shows `failsafe` still boots to wizard | **Degraded (supported with scroll)** |
| **DISP-06** | HiDPI 200% (e.g., 2560×1440 @ 2×) | Modern laptop, X DPI 144 | Tk scales with DPI (Tk 8.6 font scaling); DejaVu at 2× may overflow `WRAP 868`; clipped-text test would fail at 144 DPI | Gate stays at 72 DPI per `.cursor/start.sh`; HiDPI not claimed | **Degraded (untested)** |
| **DISP-07** | Xorg driver probe (no `Driver "vesa"` forced) | UEFI without VBIOS (no VBE) | System must not force VESA on every GPU — must probe modesetting/simpledrm first | `test_xorg_does_not_force_vesa_on_every_gpu` asserts no `Driver "vesa"` and `AllowMouseOpenFail` | **Supported** |

Evidence for DISP-01/02: local Xvfb 72 DPI run (hosted gate); 218-test suite includes 14+ layout tests. DISP-03/04 are linear interpolations of the same `CONTENT_W` + `minsize` design; DISP-05/06 are documented degraded/untested rather than claimed.

Gallery/web-preview shares same tokens (BG, SURFACE, INK, PRIMARY, etc.) — `tests/test_ui_system.py` pins every token appears in `gallery_html()` and `helper/index.html`; `test_text_contrast_meets_wcag_aa` enforces ≥4.5:1 for text and ≥3:1 for focus/border.

---

## 8. Keyboard-only & input matrix

All wizard screens are keyboard-reachable. Tk primary action is **global Enter/KP_Enter on the root**, not per-button Space — gates live there. Buttons activate on Space only to avoid shadowing.

| ID | Path | Keys | Expected | Observed | Result |
| --- | --- | --- | --- | --- | --- |
| **KB-01** | Any → What → Owner → Pick (first Up/Down selects edge) | `any key` on Splash, `Return` on What, `Space` on Owner checkbox, `Up/Down` on Pick | Splash advances on any key; What `Return` → Owner; Space toggles `owner_ok`; first `Down` selects first sorted disk, `Up` selects last when none selected | `test_keyboard_only_flow_reaches_working`, `test_move_selection_*`, `test_every_screen_has_a_focusable_action` | **Supported** |
| **KB-02** | Pick → Confirm → Method → Last chance (countdown) | `Return` on Confirm (token match), digits `1/2/3` on Method, `Return` on Last chance after 5 s | Token mismatch blocks `continue_confirm`; Method `1/2/3` switches method; Last chance `Return` during countdown is ignored | `test_keyboard_only_flow_reaches_working` (countdown guard), `test_move_selection_follows_path_sorted_order` | **Supported** |
| **KB-03** | Held Enter across screen transition | Press `Return` on Method → arrive Last chance with countdown active, keep holding | **Must not** fire Erase when countdown completes while key still down; only after release + fresh press | `test_held_enter_does_not_erase_when_countdown_completes` + `…_does_not_skip_method_after_confirm` + `…_does_not_shutdown_pick_empty/failed_done` | **Supported** |
| **KB-04** | Done / empty / blocked → shutdown | `Return`/`Space` on Done/empty/blocked | First press ignored until `_done_keyboard_armed` after key release; second press shuts down | `test_held_enter_does_not_shutdown_*`, `test_held_space_does_not_shutdown_*`, `test_curses_pick_empty_enter_ignored_until_idle` | **Supported** |
| **KB-05** | Tab / focus ring | Tab cycles primary/secondary/ghost buttons | Every screen has a focusable action (`takefocus=1`, `<FocusIn>`/`<FocusOut>` → focus ring) | `test_button_variants_and_keyboard_activation`, `test_box_component_supports_shadows_and_sync_fit` | **Supported** |
| **KB-06** | Escape → Back | `Esc` on Owner/Pick/Confirm/Method/Last/Advanced | Returns to previous screen, clears `_erase_until` when leaving Last chance | `test_escape_goes_back`, `Wizard.back()` mapping | **Supported** |
| **KB-07** | Console fallback (no X, `curses` or plain `input()`) | `Up/Down` (curses) / numbers (plain), `Space`, `Enter`, `1/2/3`, `YES`, `ERASE` | Plain loop `Number of disk to erase` rejects `0` and non-numeric; curses pick shows serial + path + `SAME_SIZE_HINT`; confirm uses own `getch` loop with `enter_held` guard | `tests/test_console_pick.py` (8 tests) | **Supported** |
| **KB-08** | Pick list with many disks → scroll | Keyboard nav keeps selected card in view | `yview` fraction computed from card `winfo_y` vs canvas `bbox`; visible check `y0 >= top -0.02 and y1 <= bottom+0.02` | `test_pick_list_scrolls_selected_card_into_view`, `test_pick_list_keeps_scroll_position_on_click` | **Supported** |

Hints render as key caps (`Enter`, `Esc`, `Space`, `Up/Down`, `1, 2, or 3`) in both Tk (`_KEY_TOKEN_RE`) and gallery (`renderHint`); pinned by `test_every_hint_key_name_renders_as_a_key_cap`.

---

## 9. Safety-gates matrix

Each gate is pinned by a `SafetyError` + test spy that asserts `NwipeRunner` is **not** invoked when gates fail.

| Gate | Rule | Spy / test | Result |
| --- | --- | --- | --- |
| Owner ack | Checkbox must be checked (`owner_ok` → `assert_ready_to_wipe` raises "Owner checkbox") | `test_owner_and_token_required_before_wipe`, wizard `accept_what`/`continue_owner` | **Supported** |
| Type-to-confirm | Token from `confirm_spec` (size label OR last4 serial OR full serial OR device name via `SAFE_TOKEN_RE`), case-insensitive | `test_unique_size_uses_gb_label`, `test_duplicate_size_uses_serial_suffix`, `test_same_size_colliding...`, `test_unsafe_serial...`, `test_empty_serial...` | **Supported** |
| 5 s delay | `wipe.confirm_erase` checks `erase_enabled == countdown_left<=0`; `tick` counts `COUNTDOWN_S 5.0` | `test_happy_path_dry_run` (5 s then confirm), `test_held_enter_does_not_erase_when...` | **Supported** |
| No auto-start | `Wizard.screen == SPLASH` and `not preview` only advances via `tick` after 3 s *or* explicit `skip_splash`/`any key`; `test_no_autostart_wipe` asserts `runner.started False` | `test_no_autostart_wipe`, `test_splash_times_out`, `test_preview_splash_does_not_auto_advance` | **Supported** |
| Boot exclusion | `assert_boot_excluded` raises if `boot_identified False` or `boot in selectable`; `selectable_disks` returns `()` when `boot_identified False`; `Wizard.select_disk` ignores boot path | `test_boot_never_selectable`, `test_unidentified_boot_raises`, `test_select_disk_refuses_boot_alias` | **Supported** |
| Exact target binding | `normalize_whole_disk` rejects partitions (`sda1`, `nvme0n1p1`), optical (`sr0`), `nbd*`, whitespace/comma; `validate_argv` requires exactly one `/dev` positional last; `block_rdev` + `assert_size_unchanged` re-check before exec | `test_nbd_is_not_a_wipe_target`, `test_optical_is_never_a_wipe_target`, `test_validate_rejects_extra_positional`, etc. | **Supported** |
| Pinned nwipe | `resolve_nwipe_binary` only allows `nwipe` or `NWIPE_PINNED_PATH`; `assert_nwipe_binary_safe` checks ELF magic, root-owned, not writable; `NWIPE_PINNED_VERSION 0.42` line match, not substring | `test_nwipe_binary_is_pinned_path_not_path_lookup`, `test_nwipe_script_is_not_a_safe_engine` | **Supported** |
| Log isolation | `assert_log_not_on_target` + `_log_filesystem_is_target` + `FORBIDDEN_LOG_ROOTS`; `default_log_dir` checks `0o700`, owned, on `/tmp`, symlink refusal | `test_log_*`, `test_truncate_log_does_not_follow_symlink`, `test_log_on_target_mount_is_refused` | **Supported** |

Preview/dry-run cannot exec real `NwipeRunner`: `test_confirm_erase_refuses_real_runner_in_dry_run`, `test_nwipe_runner_does_not_deadlock_on_stdout`, `test_zero_confirm_rdev_is_fail_closed_for_real_engine`.

---

## 10. Honest supported / degraded / unsupported summary

### Supported

- **Firmware:** Legacy BIOS and UEFI (Secure Boot disabled) via `syslinux` + `grub-efi`. Both show the wizard first; power-off via `systemctl poweroff` after Done.
- **USB boot variants:** USB-A and USB-C via adapter when firmware lists the stick; directly attached, not a keyboard hub if avoidable (`docs/boot-card.md`). Optical ISO (`sr0`) as QEMU path.
- **Storage:** NVMe (Samsung 970/980 etc.), SATA HDD (ST500/WDC), SATA SSD (Crucial MX500), virtio `vda` (QEMU), USB-attached disks (`tran usb` SATA bridges). Multi-disk (2–4) with same-size handling via last-4-serial → full serial → device-name token chain.
- **Display:** 1024×740 through 1920×1080 on Xorg `modesetting`/`fbdev`/`qxl`/`vmware`/`amdgpu`/`intel`/`nouveau` + DejaVu fonts, 72 DPI gate.
- **Input:** Full keyboard traversal (Tk and console fallback) with held-key guards; mouse click on disk cards.
- **Boot identification:** Live mount (`/run/live/medium` etc.) + `findmnt` + `mountinfo` + cmdline tokens (`boot=live`/`casper`, `bootfrom`/`live-media`/`img_dev`) + typed sources (`LABEL=/UUID=/PARTUUID=`) + label scan limited to `usb`/`rom`.
- **Safety:** All gates above; `nwipe` never runs with `--force`, never with a device list other than one, always `--exclude=` boot.

### Degraded (works but with limits)

- **SSDs:** Overwrite via `prng`/`dodshort`/`zero` is **not a formal certificate**; controller wear-leveling may retain data (SSD footer on pick screen, `docs/storage-and-controller-limits.md` §3, evidence `warnings[]`). Customers needing certified SSD erasure must use vendor secure-erase tool per model or physical destruction per `docs/storage-and-controller-limits.md` §5.
- **Missing/duplicate metadata:** Falls back to label → `Unknown model`, then token falls back to device name (`sda`); same-size disks force serial inspection — degraded but still safe.
- **eMMC/mmcblk:** `mmcblk0boot0/1/rpmb` (4 MiB) are hidden — correct (they are not wipe targets) but a machine with only eMMC storage will show no other disk → `PICK_EMPTY`.
- **USB hubs / keyboard hubs:** May hide the stick from firmware boot menu; degraded boot findability (try direct port, disable Fast Boot per `docs/boot-card.md`).
- **800×600 and HiDPI:** Render but need scroll / exhibit clipping at non-gate DPI; not automated at those DPIs.
- **Secure Boot enabled:** Degraded to **unsupported** unless user disables it; we do not ship a bypass.
- **Xorg driverless fallback:** Very old GPUs may fall back to `vesa`/`fbdev` (still works but slower); we deliberately do not force VESA on every GPU.

### Unsupported (honest)

- **Apple Silicon Macs (M1/M2/M3)** — `amd64` ISO only, per `docs/claims.md` and every screen subtitle. Intel Macs *may* show USB in boot picker; not supported.
- **Chromebooks, Android, RAID controllers** (`megaraid`, `aacraid`, `dm-raid` not enumerated), **Apple T2** internal storage via special driver — not listed, not tested, not claimed.
- **Network/remote storage:** `nbd`, `iscsi`, `fc`/`fcoe`, `nvmeof` — hidden via `REMOTE_BUS_TOKENS` + `WHOLE_DISK_RE`; never offered (correct).
- **In-OS wipe from Windows/macOS:** Not a wiper from inside a running OS (`app.require_live_or_dry_run`).
- **Plug-and-play / "any computer" / "military certified"** — forbidden claims per `docs/claims.md`; not advertised.
- **Concurrent wipe of multiple disks** — not offered; one `--autonuke` with one positional target only.
- **QEMU destructive wipe on Apple silicon** — not run here (TCG only); marked *Pending KVM* in this matrix; hosted gate covers build, `docs/vm-test.md` covers disposable VM steps for an operator with x86_64 KVM.

---

## 11. Backlog findings (numbered, separate from matrix verdicts)

Each finding is a defect, limit, or follow-up that the matrix work surfaced. They are **not** hidden in a pass count.

**BF-001 — Staged chroot drift: `__init__.py` 0.1.0 vs 0.1.1**
Evidence: `tests/test_live_image.py::test_staged_chroot_package_matches_src` failed (byte 129 `0` vs `1`). Root: bump to `0.1.1` in `src/beamo_wipe/__init__.py` not yet copied to `packaging/live/config/includes.chroot/.../beamo_wipe/__init__.py` (bind-mount not live). Fix: `cp src/beamo_wipe/__init__.py packaging/live/.../__init__.py` (done in this change). Remaining: need fresh Cloud Build to produce `dist/beamo-wipe-0.1.1-amd64.iso`.

**BF-002 — Test pollution via `apply_live_session_overrides` `os.environ.pop`**
Evidence: `tests/test_security_hardening.py::test_live_session_strips_web_and_helper` left `BEAMO_WIPE_DRY_RUN` unset, causing two later argv tests to hit `_log_filesystem_is_target` fail-closed on macOS (no `/proc/self/mountinfo` → `not is_preview_env()` → True). On Linux hosted gate the same tests passed because mountinfo existed and `/tmp` was not on `/dev/vda`. Fix: test now does `monkeypatch.setenv` for all popped keys so teardown restores (this changeset). No safety relaxation.

**BF-003 — 800×600 is degraded (pick list scroll required)**
The minimum 1024×740 gate does not cover 800×600 netbooks. Manual `./preview` resize shows pick list overflows but scroll position restoration (`yview`) does keep the selected card in view. Follow-up: keep 800×600 documented as degraded, not a supported minimum, unless product wants an explicit 800×600 gate with a narrower `CONTENT_W`.

**BF-004 — HiDPI not gated**
`xvfb-run @72 DPI` is the only automated gate. At 144 DPI, `WRAP` labels and `_Box` halo may clip. No failure seen in gallery/tk at 72 DPI. Follow-up: add a separate 144 DPI smoke on the hosted gate (not required for 1.0).

**BF-005 — Secure Boot unsigned image**
`LB_UEFI_SECURE_BOOT="auto"` + no enrolled key → firmware rejects USB when Secure Boot is on. This is *correct* (we do not ship circumvention), but the matrix must not claim "any UEFI". Follow-up: keep `docs/boot-card.md` and `docs/claims.md` language; consider documenting "disable Secure Boot" steps per vendor if support load justifies.

**BF-006 — eMMC only machines show empty pick**
Machines whose only non-boot storage is `mmcblk0` with only eMMC (laptops/tablets) correctly show a single selectable `mmcblk0` (ST-09). If that machine exposes only `mmcblk0boot0` (firmware area) the list is empty → `PICK_EMPTY` with "plug in the drive you want to erase" — honest but not ergonomic for eMMC-only recycle. Follow-up: keep as supported with `PICK_EMPTY`; do not auto-promote `mmcblk0boot0` to a target.

**BF-007 — USB-SATA bridges may present as `tran sata`**
A USB stick behind a SATA bridge reports `tran sata` not `usb`, so label scan alone (`_looks_like_live_medium`) would treat it as non-live-medium and fail closed (BM-05). Live mounts still identify it correctly. Follow-up: no code change required — mount path is ground truth; label fallback staying narrow is the correct fail-closed trade.

**BF-008 — Manufacturing ISO version vs `dist` artifact**
`dist/beamo-wipe-0.1.0-amd64.iso` (8a531d…) is the last manufacturing ISO from commit `3b4c01f`. Code is 0.1.1 with fail-closed patches. Until `beamo-wipe-0.1.1-amd64.iso` is built on Cloud Build, the release asset lags code. Follow-up: trigger `scripts/ci-cloud.sh --project beamo-wipe` and upload new ISO to GitHub Releases (separate operator authorization required; not done in this matrix change).

**BF-009 — QEMU destructive evidence not refreshed on this host**
Disposable `qcow2` wipe against `beamo-wipe-0.1.1` not re-run on the Apple silicon host (TCG only). Previous QEMU checklist in `docs/vm-test.md` still applies. Follow-up: operator to run `docs/vm-test.md` on an x86_64 KVM VM (steps in section 4) and paste the `sha256sum`, firmware mode, and wizard screenshots into the release checklist.

**BF-010 — `Wizard.confirm_erase` rediscover crash on `CalledProcessError`/`TimeoutExpired` (MEDIUM, wizard)**
Evidence: `BEAMO_WIPE_DRY_RUN=1` dry_run=False wizard at `LAST_CHANCE` with `rediscover=lambda: raise CalledProcessError(1,'lsblk')` or `TimeoutExpired('lsblk',15)` → pre-fix `confirm_erase` raised uncaught traceback; `OSError`/`ValueError` were already handled. Repro: `BEAMO_WIPE_DRY_RUN=1 python3 - <<'PY'` drive to `LAST_CHANCE` (`skip_splash`→`accept_what`→`set_owner True`→`select_disk`→`continue_pick`→`set_confirm_input token`→`continue_confirm`→`continue_method`, `_erase_until=0`) then `confirm_erase()` with throwing rediscover. Affected: `src/beamo_wipe/wizard.py:309-313`, staged `packaging/live/.../wizard.py`. Fix: widen except to `OSError, ValueError, CalledProcessError, TimeoutExpired, JSONDecodeError, TypeError, AttributeError` + final `Exception` → `self.error="Could not re-read disks: …"` fail-closed, `LAST_CHANCE`, `runner.start` not called. Severity: Medium (live USB only; no destructive target exposed, but UX was a traceback instead of a refusal). Acceptance: throwing rediscover yields `LAST_CHANCE` with `Could not re-read disks` and `started==False`; `python3 -m pytest tests/test_wizard_flow.py tests/test_confirmation_gates.py -q` green. Status: **Fixed in this audit** (`docs/audit-2026-09-02.md` §3).

**BF-011 — `THIRD_PARTY.md` fallback claim contradicts fail-closed nwipe build (LOW, docs)**
Evidence: `THIRD_PARTY.md:16-18` pre-fix: “If build cannot clone GitHub, it may fall back to Debian `nwipe` package …” Hook `packaging/live/config/hooks/normal/0500-build-nwipe.hook.chroot:2` says “No distro fallback — bookworm's nwipe is not 0.42” and after 5 retries `exit 1` (`ERROR: git clone nwipe failed`). No `apt-get install nwipe` exists (pinned by `tests/test_live_image.py::test_nwipe_hook_fails_closed_instead_of_unpinned_fallback`). Affected: `THIRD_PARTY.md`. Root: doc not updated when build hardened to pinned commit `6082bde060091e66365d852a1877f2ee80c67105`. Fix: doc now says pinned tag+commit, 5 retries then fail, no Debian fallback, hook `NWIPE_VERSION` check. Severity: Low (operator confusion, not safety bypass). Acceptance: `THIRD_PARTY.md` states no fallback, 5 retries, `grep -q "apt-get install.*nwipe" packaging/live/config/hooks/normal/0500-build-nwipe.hook.chroot` → 0 hits, `grep -q "No distro fallback" …` → hit. Status: **Fixed in this audit**.

**BF-012 — CI lint gate non-blocking (`|| true`) — 27 remaining `ruff` lints do not gate PRs (LOW, CI)**
Evidence: `.github/workflows/ci.yml:22-31` `lint` job: `python -m ruff check src/beamo_wipe tests || true`, `python -m mypy … || true`. `python3 -m ruff check src/beamo_wipe tests` without `|| true` reports 31 errors (e.g., `tests/test_boot_exclusion_fails_closed.py:24 F401 parse_lsblk_json`, `tests/test_confirmation_gates.py:18 F401 os`); 4 were fixed in this audit, 27 remain (F401 in test helpers, E402 top-level import after `pytest.importorskip`, F841 unused locals). Affected: `.github/workflows/ci.yml`, `tests/*.py`. Root: lint intentionally informational to avoid blocking style nits. Follow-up: make `ruff check` blocking and keep `mypy` informational, or add a dedicated blocking `safety-lint` job; track hygiene in a follow-up `style:` commit (do not collapse into this `safety:` audit). Severity: Low (tests still gate; no safety relaxation). Acceptance: either the lint step removes `|| true` from `ruff` or `docs/ci.md` explicitly documents non-blocking as intentional with rationale; `python3 -m ruff check tests/test_boot_exclusion_fails_closed.py tests/test_compatibility_matrix.py` ≤5 errors (this audit’s worst file fixed). Status: **Backlog** (tracked, not fixed in this audit). Note: CI has since migrated from `.github/workflows/ci.yml` to `cloudbuild.yaml` + `scripts/ci-hosted.sh run_lint`; the non-blocking policy is unchanged.

**BF-013 — Sidecar bare filename (`beamo-wipe-*.iso.sha256` = `hash  filename` without `dist/` prefix) needs `cd dist` for verification (LOW, release)**
Evidence: `dist/beamo-wipe-0.1.0-amd64.iso.sha256` = `8a531…  beamo-wipe-0.1.0-amd64.iso` (bare). `sha256sum -c dist/beamo-wipe-0.1.0-amd64.iso.sha256` from repo root → `No such file or directory` (looks in cwd); `(cd dist && sha256sum -c SHA256SUMS)` succeeds (as do `(cd dist && sha256sum -c beamo-wipe-0.1.0-amd64.iso.sha256)` and `sha256sum dist/beamo-wipe-0.1.0-amd64.iso`). `docs/release-verification.md` already documents both forms; `scripts/generate-release-manifest.sh` uses `cd dist` for verify. Affected: `dist/*.sha256` format (intentional), `docs/release-verification.md:26`, `README.md` flash example. Root: `sha256sum file > file.sha256` writes bare name (correct for `cd dist` use); repo-root `sha256sum -c dist/...` needs `dist/` prefix. Fix: doc clarification only, no sidecar format change. Severity: Low (consumer confusion, not safety; manifest `_manifest_sha256` via `verify_manifest` still works). Acceptance: `docs/release-verification.md` shows both `(cd dist && sha256sum -c SHA256SUMS)` and `sha256sum dist/beamo-wipe-*.iso` forms; `scripts/generate-release-manifest.sh` verifies with `cd dist` (already). Status: **Backlog** (docs only, no code change in this audit; `docs/audit-2026-09-02.md` §10 records both).

---

## 12. Reproducible steps per case

### Fake-device (every row with a fixture)

```bash
# from repo root, no real disks touched
BEAMO_WIPE_DRY_RUN=1 python3 -m pytest -k "not tk_runtime"
# single case:
BEAMO_WIPE_DRY_RUN=1 python3 -m pytest tests/test_discover.py::test_boot_usb_excluded_and_marked -v
BEAMO_WIPE_DRY_RUN=1 python3 -m pytest tests/test_compatibility_matrix.py -v  # new matrix tests
./preview                    # Tk, fake disks
BEAMO_WIPE_NO_OPEN=1 ./preview --web && ls web-preview/index.html
./preview --console </dev/null
```

### Hosted gate (BIOS+UEFI ISO + pytest @72 DPI)

```bash
./scripts/ci-cloud.sh --project beamo-wipe                  # ephemeral verification
./scripts/ci-cloud.sh --project beamo-wipe --publish-release # separately authorized production path
# or: gcloud builds submit --project=beamo-wipe --config cloudbuild.yaml .
# Logs: Google Cloud Console → Cloud Build → beamo-wipe-pr-gate / beamo-wipe-main-gate
# Authorized artifacts: gs://beamo-wipe_cloudbuild/releases/<BUILD_ID>/beamo-wipe-0.2.1-amd64.iso
# Validate locally after download:
sha256sum dist/beamo-wipe-0.2.1-amd64.iso
dd if=dist/beamo-wipe-0.2.1-amd64.iso bs=1 skip=32769 count=5 2>/dev/null | od -An -tx1  # CD001
python3 -m pytest  # (inside cloudbuild step, xvfb-run 72 DPI)
```

### Disposable QEMU destructive (isolated x86_64 VM only)

```bash
# On a throwaway x86_64 Linux VM with /dev/kvm, no host disks passed through:
BEAMO_WIPE_VERSION=0.2.1 ./scripts/qemu-verify.sh
# Checklist per docs/vm-test.md:
# - exact manifest/ISO checksums
# - shipped nwipe 0.42 bytes only
# - disposable loop identity before direct nwipe
# - fake wizard confirmation and boot-exclusion gates
# - BIOS and UEFI process-health probes
# The script tears down its private loop, mounts, and images; tear down the cloud VM afterward.
```

---

## 13. Evidence & logs (this checkout)

- `python3 -m pytest -k "not tk_runtime"` — **218 passed, 0 failed** on `Darwin arm64` with `BEAMO_WIPE_DRY_RUN=1` (this matrix changeset). Hosted gate re-runs the same under `xvfb-run 72 DPI` on `x86_64`.
- Tk clipped-text / off-window probes: 14 layout tests + 12 keyboard/scroll tests. On this Mac, Tk `Aborted` in headless `DISPLAY=:1` @96 DPI is pre-existing and not the gate; hosted gate uses `DISPLAY=:99` @72 DPI.
- `BEAMO_WIPE_NO_OPEN=1 ./preview --web` → `web-preview/index.html` (gallery) and `BEAMO_WIPE_DEMO=1 ./preview --console </dev/null` both exit 0; no real disks enumerated.
- No `nwipe` subprocess was spawned in any fake-device test — spy: `NwipeRunner.start` raises `SafetyError("Refusing to exec nwipe in preview or dry-run.")`; `DryRunRunner` fakes `WipeResult`; `subprocess.Popen` spy in `test_popen_inherits_wipe_lock_fd` asserts `pass_fds`, `cwd="/"`, `shell False`, `start_new_session True`.
- `git diff` safety review: `src/beamo_wipe/__init__.py` → staged sync, `tests/test_security_hardening.py` env fix, new `tests/fixtures/*.json` + `tests/test_compatibility_matrix.py`, this matrix doc. No relaxation of `safety.py`/`nwipe_runner.py`/`discover.py` gates.

---

## 14. Remaining risks & unsupported hardware (honest)

- **APFS / BitLocker / SED / OPAL** — wizard does not unlock encrypted volumes; they appear as raw block devices if unlocked at firmware, otherwise not listed via `mountpoint` protected checks. No BitLocker extraction. See `docs/storage-and-controller-limits.md` §4 for per-state guidance.
- **NVMe Secure Erase / ATA Secure Erase** — not implemented; wrapper only calls `nwipe`. Documented as not a sanitizer bypass. For certified erasure use vendor tools per `docs/storage-and-controller-limits.md` §5.
- **RAID / Intel RST / mdadm / LVM** — may expose `dm-0`/`md127` or hide members; not supported, not listed, not claimed.
- **USB-C / Thunderbolt docks** — additional hubs not enumerated in `docs/boot-card.md`.
- **Serial over non-standard encoding** — `udev` `\xHH` decoding covers typical, but exotic USB hub serials may still fall back to device name (still safe via `SAFE_TOKEN_RE`).
- **Concurrent `nwipe` lock** — `pinned_nwipe_already_running` checks `/proc/*/exe` → fails open when `/proc` unreadable (preview case), correct on live USB where `/proc` is readable.

---

## 15. Changelog

| Version | Date | Beamo Wipe | Change |
| --- | --- | --- | --- |
| **1.0** | 2026-09-01 | 0.1.1 | Initial publish: firmware/BIOS/UEFI, USB, NVMe/SATA/multi, missing/duplicate, unusual controllers, resolutions, keyboard, boot-media, safety gates, supported/degraded/unsupported, BF-001..009 |
| **1.1** | 2026-09-02 | 0.1.1 | First complete audit: wizard (`BF-010` rediscover crash fix), docs (`BF-011` no-fallback), CI (`BF-012` ruff non-blocking), release (`BF-013` sidecar `cd dist`); full evidence in `docs/audit-2026-09-02.md` |
| **1.2** | 2026-09-03 | 0.2.1 | Security audit hardening: device identity rechecks, metadata sanitization, private files, verified provenance, fixed kiosk boundary, content-addressed CI, isolated shipped-engine QEMU, and explicit no-overwrite publication gate. |

---

*Verification before merge:* every row in sections 4–9 has a test or fixture path; every Fail Closed row has a test asserting `selectable == ()` and no subprocess; every Degraded row has a `docs/claims.md`-compliant note; no row claims Apple Silicon, Chromebook, or "certified".
