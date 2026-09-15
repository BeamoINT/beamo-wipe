# Backlog #62 — group partitions under their physical disks

Base: `main` at `4c26217877047abe244bd3ef9266a1ced1db5491`.
Branch: `feat/group-partitions-under-disks`. Independent from current main; PRs #42, #43, #44 were not merged.

All execution uses demo/fake lsblk JSON and DryRunRunner. No real disk, no nwipe, no ISO.

## Baseline (measured on 4c26217 before the change)

`PYTHONPATH=src python3` against `discovery_for_scenario("happy")` and
`tests/fixtures/lsblk_adversarial_partitioned.json`:

- Eligible whole disks are primary picker cards (`/dev/nvme0n1`, `/dev/sda`, `/dev/sdd` on the happy demo).
- Every partition, loop device, and similar node is a **sibling** in Other detected devices, presented as an unrelated unsupported device.
- Happy-demo Other detected devices (6 rows): `/dev/loop0`, `/dev/sdb1` (boot USB partition), `/dev/nvme0n1p1`, `/dev/nvme0n1p2`, `/dev/sda1`, `/dev/sdd1`.
- Partition identity is `Unknown model | … | Connection unknown | Serial: Serial not reported` (or a volume label with no parent serial/model/size).
- The boot USB partition (`/dev/sdb1`, label `BEAMO_WIPE`) appears as an unsupported device, not under the protected boot card.
- Adversarial partitioned fixture: EFI/DATA/`BEAMO_WIPE` partitions listed as separate unsupported devices beside their SATA/NVMe/eMMC parents.

See `baseline-other-devices.txt`.

## Acceptance (measurable)

1. **SATA / NVMe / USB / USB-SATA-bridge** partitioned disks: the whole disk is the primary card; its partitions are nested under that parent; they are not Other detected devices siblings.
2. **Mapper / loop / optical**: mapper/crypt nest under the known physical parent; loop and optical with no parent remain honest standalone Other detected devices.
3. **Missing parent data**: a partition or mapper with no tree parent and no pkname chain stays a standalone row with diagnostic identity; no invented parent.
4. **Many partitions**: all partitions of one disk remain listed under that disk (no silent truncation).
5. **Diagnostic detail**: parent serial, model, and size stay on the parent; nested rows keep kind, size, volume label (or system-name diagnostic when unlabeled), and exclusion reasons.
6. **Eligibility preserved**: nested rows are never selectable; `select_disk` on a partition/mapper/loop/optical path does not select; boot USB remains excluded; `unsupported device` / mount / read-only / zero-capacity reasons are not dropped.
7. **Tk, console, GTK, gallery** share the inventory grouping. Intentional differences: Tk/gallery indent nested rows on the disk card; curses/plain console indent text under the disk block; GTK exposes nested text as a separate read-only label (not a Select button).

## Implementation

Display-only. `safety.py` still owns eligibility. `discover.nesting_parent_path`
records a known physical parent from the lsblk tree or a unique pkname chain.
It never infers `sda1` → `sda` from the kernel name. Ambiguous, cyclic, or
missing parentage leaves `parent_path` empty so the row stays visible.

`inventory.other_devices` omits children of a known listed parent. Those
children render on the parent card (Tk, gallery, curses/plain console, GTK
read-only label). Loop and optical devices with no parent remain Other
detected devices. An ineligible whole disk (mounted, etc.) stays a root row
with children indented in `full_text`.

### Intentional UI differences

| Surface | Nesting |
| --- | --- |
| Tk | Muted wrapping text on the parent card (`_beamo_nested`). Click still selects the parent disk, never the child. |
| Gallery | Same card indent via `.nested` / `.nested-item`. Pickable cards still bind to the parent path. |
| Curses / plain console | Indented lines inside the disk block. Numbers stay on whole disks only. |
| GTK | Focusable label after the Select button; not a Select action. Boot nested lines are in `protected_boot_text`. |

## Validation

Fake disks only. Commands in `commands.txt`. Results:

- Grouping regressions: `tests/test_group_partitions.py` — **19 passed**
- Affected suites (Tk/console/GTK/gallery/discover/wizard): `affected-suites.txt` — exit 0
- Full local pytest (`dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest`): `full-pytest.txt` — **exit 0**, 0 failures (progress log ~3138 passed, 28 skipped; 3227 collected)

No nwipe, no ISO, no QEMU, no physical hardware.

## Out of scope

ISO build, QEMU, physical hardware, Notion live update (MCP unavailable; handoff in `NOTION-HANDOFF.md`).
