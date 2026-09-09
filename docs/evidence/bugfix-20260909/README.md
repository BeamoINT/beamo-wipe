# Bugfix 2026-09-09

Branch: `codex/bugfix-20260909` based on `8aedfdd` (Easy Use companion #10 / 0.2.7).
No physical disk was opened or erased. Validation used fake lsblk JSON, dry-run wizards, and Go unit tests only.

## Bugs proved, then fixed

### 1. Nested mounted RAID/multipath left a sibling disk selectable

Production `lsblk -J` nests the array under one member. The 0.2.7 fail-closed path only ran for **flat** `pkname` rows (`parent is None`), which `run_lsblk()` never produces.

Proof (before): tree-shaped RAID1 with `md0` nested under `sda`, boot `sdc` → `boot_identified True`, selectable `['/dev/sdb']`.

Fix: refuse the whole inventory when **any** flattened node is mounted `raid*` / `mpath` / `md`, nested or flat.

### 2. Leftover `BEAMO_WIPE` USB could be identified as boot while the live stick stayed selectable

Label fallback treated competing live media as USB/optical, or SATA/ATA with `rm`/`hotplug` or size ≤ 64e9 bytes. Holes:

- 64 GiB USB-SATA (68.7e9) with no rm/hotplug
- USB-NVMe enclosure (`tran=nvme`, rm/hotplug)
- padded `tran=" usb"` so the real stick did not look like USB

Proof (before): leftover labeled USB identified as boot; `/dev/sdb` or `/dev/nvme0n1` selectable.

Fix: strip TRAN like `classify_bus`; treat NVMe with rm/hotplug as competing; raise the size heuristic to 128e9 so 64 GiB enclosures compete. Unique labeled USB + 256 GB+ internal NVMe/SATA still identifies.

### 3. Truncated SIGUSR1 `100%, round 1 of 1` (no pass clause) counted as Finished

`_progress_is_final_pass` treated a missing pass counter as final. A short log tail after exit 0 became `ok=True` without `| Erased |`.

Proof (before): `evaluate_nwipe_completion(0, "/dev/vda: 100.00%, round 1 of 1\n…", "/dev/vda")` → `True, "finished"`.

Fix: missing pass counters are not final. `| Erased |` or a complete last-pass line remains completion. Adjacent busy-on-other-device cases now use a complete pass line.

### 4. Last-chance retry after a failed start kept Erase armed

Failed CHECKING returned to LAST_CHANCE with the previous 5 s countdown already complete.

Fix: restart the countdown whenever CHECKING returns with an error. Ownership can only be set on the Owner screen.

### 5. GTK last-chance Enter and Esc diverged from Tk

Enter could activate a default Erase button while focus was on the warning label. Esc did not cancel WORKING. Empty pick omitted `empty_detail`.

Fix: consume Return/KP_Enter on last chance (focused enabled control only); Esc cancels WORKING; show `empty_detail`; `set_can_default(False)` on buttons. Boot USB is not duplicated in Other devices.

### 6. Empty unattended installer files did not block desktop restart

`mediaFile` rejected size 0, so empty `autounattend.xml` was treated as absent.

Fix: unattended detection allows empty regular files (still no symlink follow).

### 7. Hosted pytest deselected whole live-image tests

`ci-hosted.sh` dropped `test_iso_build_uses_https_debian_mirrors` and `test_live_config_xinit_cannot_hijack_kiosk` whenever `lb config` artifacts were absent, including their **source** assertions on `inside-docker.sh` / `nox11autologin`.

Fix: those source assertions always run; only the generated `bootstrap`/`binary` reads skip themselves. Hosted pytest no longer deselects the tests.

## Adjacent cases that still pass

- Flat mounted RAID/mpath still fail closed
- Unique BEAMO_WIPE USB + large internal SATA/NVMe still identifies via label
- Complete `pass 1 of 1` / `| Erased |` still complete
- Busy skip, abort, geometry, and dodshort mid-pass 100% still not Finished
- Owner / token / countdown still required to start
- Desktop still never erases; unattended nonempty files still refused

## Verification

| Check | Result |
| --- | --- |
| `dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest` | exit 0 (1829 collected) |
| `cd desktop && go test ./...` | ok |
| `python3 -m compileall -q src/beamo_wipe` | ok |
| Hosted ruff security subset | not installed in this environment (`python3 -m ruff` missing) |
| ISO / QEMU | not run (unauthorized; no release) |

See `pytest.txt`, `pytest-summary.txt`, `go-test.txt`.

## Residual risk

- Unmounted RAID/LVM members remain selectable (only **mounted** multi-parent volumes fail closed). nwipe may still skip a busy member.
- USB-NVMe / USB-SATA larger than 128 GB with `rm=0` and `hotplug=0` can still lose to a leftover labeled USB if mounts and cmdline fail. Prefer fail-closed: if boot identity is uncertain, no disks are listed.
- GTK default-button behavior is covered by unit tests, not a live Orca session on hardware.
- Physical USB/controller/firmware compatibility is unverified.
- Cloud Build ISO/QEMU was not submitted.

No nwipe version bump. No release. No ISO published.
