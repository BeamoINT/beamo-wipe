# Notion Details append — #62 (paste this)

**Status: Done** — acceptance met on fake lsblk inventories. Coordinator: mark Done.

Continued with **Grok 4.6 high** via the T3-wired Grok CLI. Jack asked for this on Grok 4.6 high.

MCP Notion tools were not available in this session. Paste this block into Ref #62 Details.

---

### Baseline

- Repo: `beamo-wipe`
- Starting `main`: `4c26217877047abe244bd3ef9266a1ced1db5491` — `fix: gallery HTML-escape pin matches boot-card serial rendering`
- Branch: `feat/group-partitions-under-disks` (independent from current main; PRs #42, #43, #44 not merged)
- Implementation: `834312a1a623548100fd72cad61010000a062478` — `feat: nest partitions under physical disks in the picker (#62)`
- Evidence: `docs/evidence/group-partitions-62/`

On 4c26217 the happy-demo picker listed 6 Other detected devices as unrelated unsupported rows, including the boot USB partition and every NVMe/SATA/USB partition (`Unknown model | … | Connection unknown`). See `baseline-other-devices.txt`.

### What landed

Physical disks are primary cards. Partitions, encrypted/mapped volumes, and other technical children nest under a **known** physical parent. Loop and optical devices with no parent stay standalone Other detected devices. Missing or ambiguous parentage is not invented.

Eligibility is unchanged: nested rows are never selectable; `select_disk` on a partition/mapper/loop/optical path is a no-op; boot USB stays excluded; exclusion reasons are preserved.

Tk and gallery indent on the parent card. Curses/plain console indent inside the disk block (numbers stay on whole disks). GTK uses a separate focusable label, not a Select button.

### Confirmations

- Fake lsblk JSON and DryRunRunner only. No nwipe on a real disk. No ISO.
- Fail-closed boot identity still hides inventory and nested rows.
- Diagnostic identity (serial/model/size) stays on the parent; unlabeled children keep the existing system-name note.
- Local pytest: grouping 19 passed; full suite exit 0.

### Notion

Mark **Done**. No blocker.
