# Beamo Wipe — AI agent guide

> This file is mirrored to `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `GROK.md`, and `.github/copilot-instructions.md`. Edit one copy, then run `~/dev/sync-ai-memory.sh --repo .` to re-sync the rest.

Durable notes live in `.ai/memory/` — start at `.ai/memory/MEMORY.md`.

## Project

Guided **nwipe** front-end plus a Debian live ISO. Beamo Wipe does not implement a wipe engine. It discovers disks, refuses to target the boot USB, walks a non-technical owner through confirms, then execs pinned **nwipe v0.42**.

Repo: `https://github.com/BeamoINT/beamo-wipe` (slug `beamo-wipe`). Branding may say Beamo Wipe; do not rename nwipe.

## Shared-checkout discipline

Other agents may be working here. Stage explicit paths only. Never `git add -A`. Never commit `*.iso`, USB images, or secrets.

## Canonical commands

```bash
python3 -m pytest
./scripts/test-all.sh
python3 -m beamo_wipe --demo
./scripts/build-iso.sh
```

The real gate is local pytest. GitHub Actions may be billing-blocked on this org; do not treat a red Actions badge as a product defect.

## Safety boundaries

- Erasure = the `nwipe` binary only. No ATA/NVMe sanitize engine, no custom overwrite loop.
- No password reset, SAM edits, BitLocker extraction, Secure Boot circumvention, or in-OS wipe of the running Windows disk.
- Boot USB must never be selectable. If it cannot be identified, list no disks.
- Confirm token + 5s delay + owner checkbox. No auto-start wipe on boot.
- Logs under `/tmp/beamo-wipe/`, never the target disk.
- `--autonuke` is allowed only with exactly one positional `/dev/…` target and `--exclude=` the boot device. Never `--force`.
- No Apple Silicon / Chromebook / “certified DoD” / “plug and play” claims. See `docs/claims.md`.

Any change to disk selection or nwipe flags is a `safety:` commit and needs a test.

## Layout

- `src/beamo_wipe/` — wizard, discover, safety, nwipe_runner
- `helper/index.html` — boot-menu helper (does not wipe)
- `packaging/live/` — live-build config, Dockerized by `scripts/build-iso.sh`
- `docs/claims.md` — Amazon copy
- `docs/ADVANCED.md` — pinned nwipe flags
