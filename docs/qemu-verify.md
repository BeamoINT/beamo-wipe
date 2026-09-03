# Controlled QEMU destructive-path verification

Run only on an isolated x86_64 Linux VM/runner with no host-disk passthrough and one newly created disposable virtual target. Never on the development Mac or a real user disk.

## Safety

- Script `scripts/qemu-verify.sh` aborts if `uname` is not `Linux x86_64`, if `/Users/HP` exists, or if `/tmp/beamo-wipe-target.qcow2` already exists.
- Only files under `/tmp` (`/tmp/beamo-wipe-target.qcow2`, `/tmp/beamo-wipe-target.raw`, `/tmp/beamo-wipe-qemu-evidence/`) are used. Host block devices are never passed via `--device` or host `/dev` bind; QEMU is invoked with `-drive file=/tmp/…qcow2,if=virtio,format=qcow2` only.
- Preflight `record_identity` checks `qemu-img info`, `lsblk` host, `findmnt`, and `losetup -j` to prove the loop is the disposable file, not a host disk. Any extra, ambiguous, changed, mounted, or host-backed device aborts.
- Disposable images are `rm -v` after evidence collection; `trap cleanup` removes loop devices.

## What is exercised

- **BIOS and UEFI boot** where OVMF is present (`-bios OVMF_CODE.fd` and default SeaBIOS), boot-medium exclusion (`sr0` rom not selectable), target `vda` virtio 10G visible.
- **Target selection** via `discover` payload `sdb` boot USB + `vda` virtio + `sr0` optical, wizard `PICK` → `CONFIRM` → `METHOD` → `LAST_CHANCE`.
- **Every confirmation gate** — owner checkbox, exact token (`confirm.token`), 5 s `COUNTDOWN_S` via `Clock`, `erase_enabled`, `confirm_erase` re-discovers and checks `assert_boot_excluded`/`assert_disk_identity`.
- **Exact nwipe boundary** — pinned `nwipe v0.42` at `/tmp/nwipe-pinned` (built from `martijnvanbrummelen/nwipe@v0.42` or host `nwipe`), invoked as `nwipe --autonuke --nogui --nowait --method=zero --verify=off --noblank --exclude=/dev/sdb --logfile=/tmp/beamo-wipe/nwipe-loop.log --PDFreportpath=noPDF /dev/loopN` with `timeout 20` and `pass_fds` checks via existing `tests/test_nwipe_runner.py`.
- **Progress/completion/cancellation/non-zero/log** — DryRunRunner progress, `evaluate_nwipe_completion` markers (`| Erased |` or last-pass 100%), `timeout 3` kill, bad device `/tmp/not-a-disk` expecting 75, log presence and `log_checksum_sha256` in `evidence.json` plus sidecar `.sha256`.

## How to run

In CI it runs as the `qemu-verify` step of `cloudbuild.yaml` (after `iso-build`, on the build worker — TCG where KVM is absent — against a disposable `qcow2`; evidence copied to `qemu-evidence/` artifacts). Pushes to `main` run it via the `beamo-wipe-main-gate` trigger; PRs skip it (`_SKIP_QEMU=true`).

Manually, on a throwaway x86_64 VM with `/dev/kvm` (e.g., GCE `n2-standard-4`):

```sh
BEAMO_WIPE_VERSION=0.2.0 ./scripts/qemu-verify.sh
# Evidence left in /tmp/beamo-wipe-qemu-evidence/ and /tmp/beamo-wipe/
# ISO checks in $EVIDENCE_DIR/iso-checks.txt, VM info, preflight, wizard-exercise, nwipe-boundary, qemu-bios/uefi, final
ls -R /tmp/beamo-wipe-qemu-evidence | head -n 50
```

Destroy: the script `rm -v /tmp/beamo-wipe-target.*` after `record_identity after-all`; the VM itself is ephemeral (`--rm` or terminate the GCE instance).

## Evidence captured

- `vm-info.txt` — `uname`, `lsb_release`, `qemu`/`nwipe` versions, git SHA
- `iso-checks.txt` — `ls -lh`, `sha256sum`, `CD001` at 32769, `file`, `isoinfo -d`, squashfs nwipe version
- `preflight-before.txt`, `create.txt`, `target-before-sha256.txt`, `identity-before-nwipe.txt`, `loop.txt`
- `wizard-exercise.txt` — Python wizard with fake `vda` (same as QEMU `disk10Gtest`), proves no boot selectable
- `nwipe-boundary.txt`, `nwipe-cancel.txt`, `nwipe-nonzero.txt`, `after-nwipe.txt`, `target-after-sha256.txt`
- `qemu-bios.txt`, `qemu-uefi.txt`, `qemu-summary.txt` (RUNNING/EXITED/SKIP)
- `final.txt`, `untested-physical.txt` (reported separately), `cleanup.txt`

All under `/tmp/beamo-wipe-qemu-evidence` (tmpfs, not target) plus sidecar `.sha256`. Never written to `vda` or `sda`.

## Untested physical-controller behavior (reported separately)

See `untested-physical.txt` in the artifact: real NVMe/SATA controllers beyond QEMU virtio, USB-SATA bridges, Secure Boot enrolled keys, Apple Silicon, RAID, SSD wear-leveling certificate. These require lab hardware and are not claimed in `docs/claims.md`.

## Failure triage

- `ABORT: QEMU verification must run on Linux` → ran on Mac.
- `ABORT: target already exists` → leftover from prior run; `rm /tmp/beamo-wipe-target.qcow2`.
- `PVD FAIL` → ISO not hybrid; rebuild via `scripts/build-iso.sh`.
- `Wizard exercise FAILED` → safety regression; check `src/beamo_wipe/safety.py`/`wizard.py`.
- `QEMU BIOS/UEFI timeout` on TCG-only (no KVM) is expected; evidence records `SKIP`/`TIMEOUT`.

See `docs/ci.md` for the overall gate (lint → test → negative-test → iso → qemu-verify).
