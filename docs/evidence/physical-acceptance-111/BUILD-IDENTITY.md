# Build identity — physical acceptance session

Fill this **before** the first physical boot. Empty fields mean the session is not qualified.

Do not paste values from QEMU, Cloud Build, or an old USB-lab receipt unless you re-measured the stick in your hand.

## Session

| Field | Value |
| --- | --- |
| Operator | |
| Date (UTC) | |
| Lab / location | |
| Notion / backlog | #111 |
| Dedicated spare x64 PC (not a VM, not a development host)? | yes / no |
| Valuable disks disconnected or removed? | yes / no |
| Spare USB whose contents may be replaced? | yes / no |
| Manufactured image authorized by Jack for this session? | yes / no |
| QEMU/VM used as a substitute for any Pass cell? | **must be no** |
| `nwipe` run from a development shell against a real disk? | **must be no** |

## Image

| Field | Value |
| --- | --- |
| Wrapper version (`beamo_wipe.__version__`) | |
| Source commit (full SHA) | |
| Working tree dirty? | yes / no |
| `nwipe` version | 0.42 (pinned) |
| `nwipe` commit | `6082bde060091e66365d852a1877f2ee80c67105` |
| ISO filename | |
| ISO SHA-256 | |
| ISO byte size | |
| USB image filename (`.img`, if used) | |
| USB image SHA-256 | |
| Manifest filename | |
| Manifest SHA-256 | |
| How checksums were verified | |
| Flash tool and host OS | |
| Flash date (UTC) | |
| USB stick manufacturer / model / capacity | |
| USB stick serial (if known) | |
| Partition label observed | `BEAMO_WIPE` expected |

## First machine (copy this block per PC)

| Field | Value |
| --- | --- |
| PC manufacturer / model | |
| CPU architecture (must be x64 for support) | |
| Firmware vendor / version | |
| Firmware mode this session (BIOS / UEFI / CSM) | |
| Secure Boot state | on / off / not present |
| Relevant trust / revocation notes | |
| Built-in panel resolution (if laptop) | |
| External display (if any) | |
| Ports used (USB-A / USB-C / adapter / hub) | |
| Disks left connected (model, serial, bus, DISPOSABLE?) | |
| Result of this machine overall | NOT TESTED |

Attach photos and logs using the row IDs from `results/`.
