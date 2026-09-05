# Advanced (nwipe methods)

This page is for technicians. The wizard happy path does not show flags.

Pinned engine: **nwipe v0.42**
https://github.com/martijnvanbrummelen/nwipe/releases/tag/v0.42

Beamo Wipe never implements its own overwrite. It only execs `nwipe`.

## Happy-path mapping

| Wizard choice | nwipe | Notes |
| --- | --- | --- |
| Everyday (default) | `--method=prng --rounds=1 --verify=last --noblank` | One random-data overwrite, then one separate read-back verification pass. |
| Three overwrites | `--method=dodshort --rounds=1 --verify=last --noblank` | Three overwrite passes: a pattern, its inverse, then random data; one separate read-back verification pass after the final overwrite. This is not a DoD certificate. |
| Quick zero | `--method=zero --rounds=1 --verify=off --noblank` | One zero overwrite. Verification is not performed; no read-back pass. |

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

At method selection, choose **Storage limits (L)** to read the full supported
limits offline, without leaving or advancing the erase confirmation flow.

Read-back checks only accessible storage against the final overwrite. It does not prove that inaccessible or remapped SSD storage was erased. Extra overwrites do not reach those areas. On SSDs the controller decides what remains. Overwrite methods are not a
formal certificate. Do not tell customers otherwise. For NVMe/SATA controller
behavior, hidden areas, encryption, RAID, damaged media, and when to use
vendor secure erase or physical destruction, see
`docs/storage-and-controller-limits.md` §3–§6.

## Logs

Before choosing a target, **Need a report?** explains the optional report flow.
It is also available at method selection and in Advanced, and as `REPORT` in
the plain console (`R` in the menu console). The unchecked **I want to save a
report** box records only a preference for this live session. It neither selects
media nor exports, creates evidence, or prevents shutdown. Refresh preserves
this preference but clears target selection and every erase confirmation.

Keep the report USB unplugged while selecting, confirming, and erasing. If
inserted early, remove only the intended report USB, leave the boot USB and
erase disk attached, and choose **Check disks again** before choosing and
confirming the target again. Do not guess which device to remove.

Only after the erase has stopped and the result screen offers **Save report to
USB**, insert exactly one separate removable FAT32 USB, then choose **Save
report to USB**. Leave the Beamo boot USB and selected erase disk connected.
The report USB must have one writable, unmounted FAT32 volume; exFAT, NTFS,
FAT12 and FAT16 are unsupported. Beamo Wipe never formats or repairs it.
The exporter rejects devices present in the final pre-erase inventory, including
a report USB inserted too early. Final target rediscovery and confirmation
remain mandatory; report intent does not authorize any disk operation.

Any unsaved report is lost when the live session shuts down or loses power.
Reports include disk identifiers; review them before sharing. The exporter
writes a unique directory and verifies it after a read-only remount. Only the
saved-and-safe-to-remove message confirms safe removal after final unmount.
Never remove report media while saving. On failure, follow the error and retry
while the session remains running; media is not automatically formatted.

When a wipe cannot start, use the separate [diagnostic report](startup-diagnostics.md)
flow: Prepare with report media disconnected, then insert only when prompted.
Diagnostics are not erase evidence and do not establish that an erase ran.
