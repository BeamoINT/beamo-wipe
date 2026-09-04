# Controlled QEMU destructive-path verification

Run `scripts/qemu-verify.sh` only on an isolated x86_64 Linux worker with no host-disk passthrough. It aborts on macOS, non-x86_64 hosts, a missing exact-version ISO/manifest, unverifiable checksums, or any uncertain loop identity.

## Isolation and inputs

- Every run gets a mode-0700 `mktemp` directory under `/tmp`; no predictable target, mount, PID, or evidence path is reused.
- The script accepts only `dist/beamo-wipe-<version>-amd64.iso` and its matching manifest/sidecars. There is no wildcard ISO, distro `nwipe`, host `nwipe`, or apt fallback.
- QEMU receives only the read-only ISO and a newly created qcow2 file. It receives no `/dev` bind, `--device`, network interface, or host block disk.
- The direct engine boundary uses a newly created 256 MiB raw file. `losetup -j`, `lsblk TYPE=loop`, and `findmnt` re-prove both target and read-only ISO loop devices immediately before invocation.
- The worker installs `hdparm` because exact nwipe v0.42 exits before device processing when it is absent. The Beamo application does not invoke `hdparm`, and no destructive hdparm option is used by this gate.
- The cleanup trap kills only PIDs obtained from the current background QEMU commands, detaches only validated `/dev/loopN` values, unmounts the private mounts, and removes disposable images. Evidence remains in the path recorded by `qemu-evidence/PATH` for the CI collector.

## Required checks

The gate fails unless all of these pass:

1. ISO and manifest sidecars, manifest-to-actual-ISO hash/size/path binding, ISO9660 PVD, and El Torito catalog.
2. Read-only mount of the ISO and squashfs, exact `nwipe version 0.42`, root ownership, and no group/other-writable kiosk/engine assets.
3. No unnecessary admin tools (`nano`, `less`, `iproute2`, `dmidecode`, PCI/USB utilities, `eject`) or compiler/VCS in the installed package database. `hdparm` remains only because pinned nwipe v0.42 uses its read-only HPA/DCO queries.
4. `debsecan --suite bookworm --only-fixed` reports no installed package with a fixed Debian vulnerability.
5. Fake-disk owner, confirmation, countdown, boot-exclusion, rediscovery, and process-boundary tests.
6. The binary copied byte-for-byte from the ISO completes a quick zero on the disposable loop with a target success marker, and rejects a non-block target.
7. Both SeaBIOS and OVMF QEMU processes remain healthy through the boot observation window. Early exit or missing OVMF is a failure, never `SKIP` or a tolerated timeout.

```sh
BEAMO_WIPE_VERSION=0.2.1 ./scripts/qemu-verify.sh
evidence_dir=$(cat qemu-evidence/PATH)
find "$evidence_dir" -maxdepth 1 -type f -print
```

The run does not validate physical SATA/NVMe firmware behavior, USB bridges, Secure Boot, RAID, SSD spare-area erasure, or a human click-through of every graphical screen. Those require separately authorized lab hardware and are not claimed.
