# Controlled QEMU destructive-path verification

Run `scripts/qemu-verify.sh` only on an isolated x86_64 Linux worker with no host-disk passthrough. It aborts on macOS, non-x86_64 hosts, a missing exact-version ISO/manifest, unverifiable checksums, or any uncertain loop identity.

## Isolation and inputs

- Every run gets a mode-0700 `mktemp` directory under `/tmp`; no predictable target, mount, PID, or evidence path is reused.
- The report-export check creates its own disposable FAT32 raw image inside the
  isolated x86_64 worker. The BIOS guest boots the exact ISO, QMP drives the
  shipped Tk wizard through owner approval, target selection, confirmation,
  quick-zero, and Done, and only then hotplugs that image as USB storage. The
  gate waits for the shipped `BEAMO_WIPE_REPORT_SAVED` serial marker, so the
  real `Wizard -> export_to_new_usb -> private worker` path must finish.
- After QEMU exits, the host reattaches the report image read-only, requires a
  clean FAT32 filesystem, mounts it read-only, and independently checks the
  completion manifest, every listed SHA-256, the result sidecar, the terminal
  successful outcome, and final unmount. The on-media manifest is required to
  describe content only and to set `safe_to_remove` false; only the live
  `BEAMO_WIPE_REPORT_SAVED` marker proves the worker verified and unmounted the
  USB. A separate killed private-namespace helper must leave no host-namespace
  mount behind.
- The script accepts only `dist/beamo-wipe-<version>-amd64.iso` and its matching manifest/sidecars. There is no wildcard ISO, distro `nwipe`, host `nwipe`, or apt fallback.
- QEMU initially receives only the read-only ISO and a newly created qcow2
  target. The report is a newly created raw file hotplugged through QMP as USB
  storage after Done. QEMU receives no `/dev` bind, host block disk, or network
  interface.
- The direct engine boundary uses a newly created 256 MiB raw file. Every host
  loop is re-proved by exact backing file, `lsblk TYPE=loop`, read-only state,
  and `findmnt` before use and detachment.
- The worker installs `hdparm` because exact nwipe v0.42 exits before device processing when it is absent. The Beamo application does not invoke `hdparm`, and no destructive hdparm option is used by this gate.
- Signal handlers stop after one idempotent cleanup and exit nonzero. Cleanup
  kills only PIDs obtained from the current background QEMU commands, detaches
  only loops still proven to have the expected backing/type/read-only state,
  unmounts private mounts, and removes disposable images. Evidence remains in
  the path recorded by `qemu-evidence/PATH` for the CI collector.

## Required checks

The gate fails unless all of these pass:

1. ISO and manifest sidecars, manifest-to-actual-ISO hash/size/path binding, ISO9660 PVD, and El Torito catalog.
2. Read-only mount of the ISO and squashfs, exact `nwipe version 0.42`, root ownership, and no group/other-writable kiosk/engine assets.
3. No unnecessary admin tools (`nano`, `less`, `iproute2`, `dmidecode`, PCI/USB utilities, `eject`) or compiler/VCS in the installed package database. `hdparm` remains only because pinned nwipe v0.42 uses its read-only HPA/DCO queries.
4. `debsecan --suite bookworm --only-fixed` reports no installed package with a fixed Debian vulnerability.
5. Fake-disk owner, confirmation, countdown, boot-exclusion, rediscovery, and process-boundary tests.
6. The binary copied byte-for-byte from the ISO completes a quick zero on the disposable loop with a target success marker, and rejects a non-block target.
7. SeaBIOS reaches every expected shipped Tk marker, runs a real quick-zero on
   the file-backed target, hotplugs the FAT32 report file, and reaches the
   shipped report-saved marker. After the guest stops, `qemu-io` proves the
   deliberately nonzero 1 MiB prefill became zero. Missing/error markers,
   unchanged target bytes, or early exit fail.
8. OVMF reaches the shipped Tk `WHAT` marker. Missing OVMF, an early exit, or a
   timeout is a failure, never `SKIP` or a tolerated timeout.

```sh
BEAMO_WIPE_VERSION=0.2.1 ./scripts/qemu-verify.sh
evidence_dir=$(cat qemu-evidence/PATH)
find "$evidence_dir" -maxdepth 1 -type f -print
```

The run does not validate physical SATA/NVMe firmware behavior, USB bridges, Secure Boot, RAID, SSD spare-area erasure, or a human click-through of every graphical screen. Those require separately authorized lab hardware and are not claimed.
