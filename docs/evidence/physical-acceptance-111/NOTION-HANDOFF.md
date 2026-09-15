# Notion Details append — #111 (paste this; do not mark Done)

**Status: keep In progress. Do not mark Done.**

Physical computer and USB acceptance is still incomplete. This update is prep only.

---

Continued with **Grok 4.6 high** via the T3-wired Grok CLI after Codex GPT-6 Astra (low) hit a usage limit immediately (retry after 2026-09-21 03:14 UTC). Astra is no longer blocking this prep. Nothing was committed by Astra.

### Baseline

- Repo: `beamo-wipe`
- Starting `main`: `9210aa3` — `Merge verified laptop power guidance into current main`
- Branch: `feat/physical-acceptance-111` (independent from current main; no other feature branches merged)
- Implementation commit: `5ebcb8c3504ed15ab7c7fab4ed81532401dc3db0` — `docs: physical acceptance matrix scaffolding (#111)`

### What landed

Executable physical matrix + empty result sheets + honesty pins:

- `docs/evidence/physical-acceptance-111/README.md` — measurable “done” criteria, how to run on dedicated safe hardware, gap inventory, fail-closed disk-safety reminder
- `docs/evidence/physical-acceptance-111/BUILD-IDENTITY.md` — image SHA, version/tag, build date, media serial fields
- Empty sheets (every cell **NOT TESTED**): firmware, monitors, ports, USB controllers, keyboards, touchpads, audio, power, desktop USB launch, optional destructive
- Photo/log drop folders (empty of lab artifacts)
- Cross-links from `docs/desktop-hardware-acceptance.md`, `docs/compatibility-matrix.md`, `docs/evidence-tiers.md`, `docs/live-session-power.md`
- `tests/test_physical_acceptance_111.py` — rows stay NOT TESTED; USB-lab and laptop-power are cited as gaps, not passes

### Gap list (summary)

**Exists, does not complete #111:** desktop hardware checklist (all NOT TESTED); compatibility-matrix FW/DISP/KB rows (QEMU/fixture); USB simulation lab 2026-09-07 (explicitly “Physical USB acceptance: Not established”; `docs/evidence/usb-lab-20260907/linux/boot-gate/untested-physical.txt`); laptop-power 2026-09-14 (“Physical acceptance: pending”); live-session power 2026-09-10 (lid / held power button Not run); GCP desktop VM launchers; QEMU verify.

**Missing:** any named physical PC; any manufactured-image SHA for a flashed spare USB used on that PC; any physical Pass for firmware, monitors, ports, USB controllers, keyboards, touchpads, audio, or power; any Tier 3 destructive receipt.

### What Jack still must do

1. Authorize a **manufactured image** for the lab session (ISO + USB `.img` + checksums). This checkout’s `dist/` 0.1.0 quarantine ISO is not that identity.
2. Use **dedicated safe hardware**: spare x64 PC, no valuable disks, spare USB whose contents may be replaced. Not a VM. Not a development host. Never substitute QEMU/USB-lab for a Pass cell.
3. Fill `BUILD-IDENTITY.md` first, then work `results/*.md`. Drop photos/logs next to the row IDs. Leave unrun rows **NOT TESTED**.
4. Optional erase only on a chassis-labeled `DISPOSABLE` disk with written owner authorization. Never `nwipe` a real disk from a development shell.
5. Keep this card **In progress** until those receipts exist. No ISO release from this work.

### Confirmations

- No fabricated physical results, hardware models, firmware strings, screenshots, or pass marks.
- No QEMU/VM result was copied into a Pass cell.
- Notion remains **In progress** (not Done).
- Fail-closed disk-safety language is unchanged.

Coordinator: paste this block into page `3d50a633-535c-8154-9aa0-e1e06d26acdf` Details. MCP Notion tools were not available in the Grok CLI session.
