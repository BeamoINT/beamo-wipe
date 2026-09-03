# Continuous integration gates

Google Cloud Build (project `beamo-wipe`) is the project's CI. GitHub
Actions is not used — there are no workflows under `.github/workflows/`.

Neither gate ever wipes a host disk.

## Gate

| Gate | Runner | What it proves |
| --- | --- | --- |
| **Cloud Build** `cloudbuild.yaml` (`./scripts/ci-cloud.sh`, project `beamo-wipe`) | `E2_HIGHCPU_8` `diskSizeGb: 200` | `lint`, fake-disk pytest under Xvfb 72 DPI, preview verification, negative test, amd64 ISO build, and controlled QEMU verification — all with fake `lsblk` JSON or disposable images. Artifacts go to `gs://beamo-wipe_cloudbuild/releases/<BUILD_ID>/`. |

```bash
python3 -m pytest                          # fast checkout (fake lsblk, no nwipe)
./scripts/test-all.sh
xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest  # 72 DPI like the live USB
BEAMO_WIPE_NO_OPEN=1 ./preview --web && ./preview --console < /dev/null
./scripts/build-iso.sh                       # amd64 live image (prefer Cloud Build on this Mac)
./scripts/ci-cloud.sh                        # or: gcloud builds submit --project=beamo-wipe
```

## Phases (`scripts/ci-hosted.sh`)

| Phase | Step | What it runs |
| --- | --- | --- |
| `lint` | `lint` | `py_compile` + `ruff` + `mypy` (non-blocking best-effort) + stray-TODO warning |
| `tests` | `python-tests` | `xvfb-run … 72 DPI` with `BEAMO_WIPE_DRY_RUN=1`; destructive-boundary spies use fake runners, never real `nwipe` |
| `preview` | `preview` | `BEAMO_WIPE_NO_OPEN=1 ./preview --web` + `--console` + `--helper` (fake disks) |
| `negative` | `negative-test` | Deliberately breaks `assert_boot_excluded` fail-open, expects the e2e test to fail, reverts, proves clean passes. Runs after `python-tests` so the temporary patch cannot corrupt the parallel suite |
| `iso` | `iso-build` | `docker run --rm --privileged --platform linux/amd64` with no `--device` or host `/dev` bind, builds `dist/beamo-wipe-0.1.1-amd64.iso` on the container fs, checks `CD001` at 32769, size ≥80 MiB, `sha256sum`, manifest + sidecars |
| `qemu` | `qemu-verify` | `scripts/qemu-verify.sh` on the worker (TCG where KVM is absent) against a disposable `qcow2` + loop devices; evidence copied to `qemu-evidence/` artifacts. Runs after `iso-build` because it verifies the built ISO |

`./scripts/ci-hosted.sh all` runs every phase in dependency order. Skip flags: `SKIP_ISO=true` / `SKIP_QEMU=true` (cloudbuild substitutions `_SKIP_ISO` / `_SKIP_QEMU`).

## Triggers

`scripts/install-cloud-triggers.sh` creates (requires the Cloud Build GitHub App connected to `BeamoINT/beamo-wipe` first):

- `beamo-wipe-pr-gate` — PRs targeting `main`: lint, tests, preview, negative, ISO (QEMU skipped via `_SKIP_QEMU=true`).
- `beamo-wipe-main-gate` — pushes to `main`: the full gate including QEMU.

Branch protection on `main` should require these Cloud Build statuses.

## Billing

Cloud Build bills the `beamo-wipe` project (free tier covers 120 build-minutes/day; `E2_HIGHCPU_8` burns faster — watch the billing dashboard). The full gate is roughly half an hour of worker time, mostly ISO + QEMU. Prefer the PR gate's QEMU skip for iteration; `main` always runs everything.

## Failure triage

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `TclError: no display name and no $DISPLAY` | Runner not using `xvfb-run … 72 DPI` | Use `xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72"`; never use VNC `DISPLAY=:1` at 96 DPI. |
| `test_iso_build_uses_https_debian_mirrors` / `test_live_config_xinit… FileNotFoundError` | `lb config` not run | Skipped automatically when `packaging/live/config/{bootstrap,binary}` are absent; run `./scripts/build-iso.sh` to generate them and cover those tests. |
| `test_manifest_*` fail with `untraceable source state` | Build workspace has no `.git` | `.gcloudignore` must not exclude `.git/` (locked by `test_cloud_submit_uploads_git_metadata`). |
| `test_manifest_*` fail with `missing checksum: ISO not found` | Manufacturing ISO absent | Those tests skip without `dist/beamo-wipe-0.1.0-amd64.iso`; build it or fetch the release artifact. |
| `test_boot_exclusion … FAILED` while `negative-test` passed | Real safety regression | Do not mute: fix `src/beamo_wipe/safety.py` / `discover.py` / `wizard.py` gate; add reproduction fixture under `tests/fixtures/`. |
| `sha256sum` mismatch or ISO <80 MiB | Stale `packaging/live/config/includes.chroot` | `cp -R src/beamo_wipe …` is done by `scripts/build-iso.sh`; ensure `BEAMO_WIPE_VERSION` matches `src/beamo_wipe/__init__.py`. |
| `docker: permission denied` | User not in `docker` group on nested VM | Use `sudo docker` (see `.cursor/start.sh`); ensure `/etc/docker/daemon.json` has `fuse-overlayfs` on nested hosts. |

Local triage: reproduce with `BEAMO_WIPE_DRY_RUN=1 xvfb-run … python -m pytest -k "not test_iso_build and not test_live_config"` then `BEAMO_WIPE_NO_OPEN=1 ./preview --web`.

## Required checks

Branch protection on `main` should require the Cloud Build triggers (`beamo-wipe-pr-gate` on PRs, `beamo-wipe-main-gate` on pushes). See `scripts/install-cloud-triggers.sh`.
