# Continuous integration gates

Beamo Wipe has two gates that must both pass. Neither ever wipes a host disk.

## Gates

| Gate | Runner | What it proves |
| --- | --- | --- |
| **GitHub Actions** `CI` (`.github/workflows/ci.yml`) | `ubuntu-latest` (x86_64) | Format/lint, fake-disk pytest under Xvfb 72 DPI, preview verification, destructive-boundary spies, negative test, and — on PRs and pushes — an amd64 ISO build in privileged Docker on a disposable container fs. |
| **Google Cloud Build** `cloudbuild.yaml` (`./scripts/ci-cloud.sh`, project `beamo-wipe`) | `E2_HIGHCPU_8` `diskSizeGb: 200` | Same pytest + ISO on native x86_64 with KVM (see `scripts/ci-hosted.sh`). Artifacts go to `gs://beamo-wipe_cloudbuild/releases/<BUILD_ID>/`. |

GitHub is **not** billing-blocked for this repo: `CI` runs on every `pull_request` and `push` to `main` plus `workflow_dispatch`. It is the required PR gate. Cloud Build remains the manufacturing ISO gate and the x86_64 QEMU host.

```bash
python3 -m pytest                          # fast checkout (fake lsblk, no nwipe)
./scripts/test-all.sh
xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest  # 72 DPI like the live USB
BEAMO_WIPE_NO_OPEN=1 ./preview --web && ./preview --console < /dev/null
./scripts/build-iso.sh                       # amd64 live image (prefer Cloud Build on this Mac)
./scripts/ci-cloud.sh                        # or: gcloud builds submit --project=beamo-wipe
```

## What GitHub CI runs (and why it failed before)

Previous `ci.yml` ran `python -m pytest` with no display. All `tests/test_tk_runtime.py` failed with `TclError: no display name and no $DISPLAY`, and two `tests/test_live_image.py` failed because `packaging/live/config/{bootstrap,binary}` only exist after `lb config` inside the ISO build. Root causes, not flakes.

Current `ci.yml` fixes both:

- **lint** — `py_compile` + `ruff` + `mypy` (non-blocking best-effort); pinned `actions/checkout@11d5960…` and `actions/setup-python@a26af69…`, `actions/upload-artifact@ea165f8…`, `permissions: contents: read`, `concurrency: ci-${{ github.ref }}`.
- **test** — `sudo apt-get install xvfb xauth python3-tk`, `xvfb-run … 72 DPI` with `BEAMO_WIPE_DRY_RUN=1` + `PYTHONPATH=src`; skips the two live-image tests when `bootstrap`/`binary` are absent (`-k "not test_iso_build…"`) exactly as `.cursor/check.sh` does; second pass runs destructive-boundary spies (`-k test_nwipe…`); then `preview --web` + `preview --console` under `BEAMO_WIPE_DRY_RUN=1`.
- **negative-test** — deliberately comments out the `boot_device_in_selectable` raise in `src/beamo_wipe/safety.py`, runs `pytest -k test_boot_exclusion`, expects failure, reverts, then proves the clean tree passes. This proves the gate blocks a bypass.
- **iso** — on `push`/`pull_request`, `docker run --rm --privileged --platform linux/amd64` with no `--device` or host `/dev` bind, builds `dist/beamo-wipe-0.1.1-amd64.iso` on the container fs (not a macOS bind mount), then checks `CD001` at 32769, size ≥80 MiB, `sha256sum`, and uploads with `retention-days: 14` via `actions/upload-artifact`.

No job mounts host block devices or invokes real `nwipe`. Every Python step exports `BEAMO_WIPE_DRY_RUN=1` and uses fake `lsblk` JSON. ISO verification uses an explicitly created disposable container filesystem and no host-disk passthrough. For interactive destructive verification, see `docs/vm-test.md` (throwaway `qcow2` + `-enable-kvm`, then tear down).

## Security posture

- **Least privilege** — `permissions: contents: read`, `persist-credentials: false`, no `write` tokens, no secrets in logs (GitHub redacts `GITHUB_TOKEN`; Cloud Build is secret-free, `CLOUD_LOGGING_ONLY`).
- **Pinned actions** — SHAs, not mutable tags.
- **Artifact retention** — `retention-days: 14`, `SHA256SUMS` alongside ISO, sidecar `.sha256` for evidence files (`src/beamo_wipe/evidence.py`).
- **Cancellation** — `concurrency: ci-${{ github.ref }}` `cancel-in-progress: true`.

## Failure triage

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `TclError: no display name and no $DISPLAY` | Runner not using `xvfb-run … 72 DPI` | Use `xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72"`; never use VNC `DISPLAY=:1` at 96 DPI. |
| `test_iso_build_uses_https_debian_mirrors` / `test_live_config_xinit… FileNotFoundError` | `lb config` not run | These two tests are skipped when `packaging/live/config/{bootstrap,binary}` are absent; run `./scripts/build-iso.sh` to generate them. |
| `test_boot_exclusion … FAILED` while `negative-test` job passed | Real safety regression | Do not mute: fix `src/beamo_wipe/safety.py` / `discover.py` / `wizard.py` gate; add reproduction fixture under `tests/fixtures/`. |
| `sha256sum` mismatch or ISO <80 MiB | Stale `packaging/live/config/includes.chroot` | `cp -R src/beamo_wipe …` is done by `scripts/build-iso.sh`; ensure `BEAMO_WIPE_VERSION` matches `src/beamo_wipe/__init__.py`. |
| `docker: permission denied` | User not in `docker` group on nested VM | Use `sudo docker` (see `.cursor/start.sh`); ensure `/etc/docker/daemon.json` has `fuse-overlayfs` on nested hosts. |

Local triage: reproduce with `BEAMO_WIPE_DRY_RUN=1 xvfb-run … python -m pytest -k "not test_iso_build and not test_live_config"` then `BEAMO_WIPE_NO_OPEN=1 ./preview --web`.

## Required checks

Branch protection on `main` should require the GitHub `CI` workflow (`lint`, `test`, `negative-test`, and `iso` when present) and — once the Cloud Build GitHub App is connected — the `beamo-wipe-pr-gate` Cloud Build trigger. See `scripts/install-cloud-triggers.sh`.
