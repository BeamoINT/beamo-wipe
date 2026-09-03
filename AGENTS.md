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
./scripts/ci-cloud.sh    # Google Cloud Build: pytest + amd64 ISO (project beamo-wipe)
./preview                # Tk window, fake disks, nothing erased
./preview --web          # browser click-through
./scripts/build-iso.sh   # amd64 live image (prefer Cloud Build, not this Mac)
```

Local pytest is the fast checkout gate. CI is Google Cloud Build in project `beamo-wipe` — GitHub Actions is not used (no workflows under `.github/workflows/`). The hosted gate is `cloudbuild.yaml` → `scripts/ci-hosted.sh` phases `lint`/`tests`/`preview`/`negative`/`iso`/`qemu` (secret-free; see `docs/ci.md`). Intended triggers: PRs targeting `main` (`beamo-wipe-pr-gate`, QEMU skipped) and pushes to `main` (`beamo-wipe-main-gate`, full gate). Agents must `./scripts/ci-cloud.sh` (or `gcloud builds submit --project=beamo-wipe`) after local pytest for ISO/x86 work — do not treat Hostinger or this Apple silicon Mac as the ISO gate.

**ISO build and QEMU wipe tests:** on the Apple silicon Mac, Docker `linux/amd64` and `qemu-system-x86_64` are TCG. Do not wait on local emulation. Cloud Build always builds the ISO on amd64. Interactive QEMU wipe (`docs/vm-test.md`) still uses a disposable x86_64 KVM VM via `gcloud`/`aws`, then tear the VM down. See `.ai/memory/iso-builds-on-cloud.md`.

## Cursor Cloud specific instructions

Cursor Cloud Agent VMs for this repo are **x86_64 Ubuntu**, not the Apple silicon Mac. Committed boot is `.cursor/environment.json` → `.cursor/install.sh` then `.cursor/start.sh` (dockerd + Xvfb `:99` at 72 DPI). `.cursor/check.sh` is the fast smoke.

Python gate on Cloud Agents: Tk layout tests scale with X DPI. The VNC desktop is `DISPLAY=:1` at 96 DPI and fails clipping tests. Use 72 DPI:

```bash
xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest
```

`.cursor/start.sh` launches Xvfb on `:99` at 72 DPI, so `DISPLAY=:99 python3 -m pytest` works. Do not replace `:1` (computer-use / VNC).

`packaging/live/config/{bootstrap,binary}` are gitignored live-build outputs. Two tests in `tests/test_live_image.py` fail until `lb config` has been run inside `./scripts/build-iso.sh`. That is expected on a fresh checkout.

ISO on Cloud Agents: Docker Engine is nested, so `/etc/docker/daemon.json` must use `fuse-overlayfs` (plain overlay fails). `/dev/kvm` is present. `./scripts/build-iso.sh` and KVM QEMU are native here. Prefer `sudo docker` unless this user is already in the `docker` group. `gcloud` and `aws` are installed for throwaway VMs you will tear down; they are not logged in unless secrets exist.

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
- `./preview` — local Tk / `--web` gallery (not shipped as a wipe tool)
- `helper/index.html` — boot-menu helper (does not wipe)
- `packaging/live/` — live-build config, Dockerized by `scripts/build-iso.sh`
- `docs/claims.md` — Amazon copy
- `docs/ADVANCED.md` — pinned nwipe flags
