# Advanced (nwipe methods)

This page is for technicians. The wizard happy path does not show flags.

Pinned engine: **nwipe v0.42**
https://github.com/martijnvanbrummelen/nwipe/releases/tag/v0.42

Beamo Wipe never implements its own overwrite. It only execs `nwipe`.

## Happy-path mapping

| Wizard choice | nwipe | Notes |
| --- | --- | --- |
| Everyday (default) | `--method=prng --rounds=1 --verify=last --noblank` | One PRNG overwrite, verify the last pass. Recommended default for HDDs in this project. |
| Extra thorough | `--method=dodshort --rounds=1 --verify=last --noblank` | nwipe’s 3-pass short DoD *method*. This is not a DoD certificate. |
| Quick zero | `--method=zero --rounds=1 --verify=off --noblank` | Fastest. Weaker on some SSDs. |

Always passed:

- `--autonuke --nogui --nowait` with **exactly one** `/dev/…` target
- `--exclude=` the live boot device
- `--PDFreportpath=noPDF`
- `--logfile=` under `/tmp/beamo-wipe/` (tmpfs — never the target disk)
- never `--force`

The engine binary lives at `/usr/lib/beamo-wipe/nwipe` (pinned v0.42). It is
not on PATH; a stub at `/usr/local/bin/nwipe` refuses direct invocation so
the wizard gates cannot be skipped from another console.

`--autonuke` with a device list wipes only those devices. The runner still
refuses to build argv unless the target is last and the boot device is
excluded. autonuke with no device is forbidden.

## SSD note

On SSDs the controller decides what remains. Overwrite methods are not a
formal certificate. Do not tell customers otherwise. For NVMe/SATA controller
behavior, hidden areas, encryption, RAID, damaged media, and when to use
vendor secure erase or physical destruction, see
`docs/storage-and-controller-limits.md` §3–§6.

## Logs

Export a log only to a **second** USB that is not the target and not the
Beamo boot stick. Advanced screen shows the log path.
