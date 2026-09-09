# Continuous integration gates

Google Cloud Build (project `beamo-wipe`) is the project's CI. GitHub
Actions is not used — there are no workflows under `.github/workflows/`.

Neither gate ever wipes a host disk.

## Gate

| Gate | Runner | What it proves |
| --- | --- | --- |
| **Cloud Build** `cloudbuild.yaml` (`./scripts/ci-cloud.sh`, project `beamo-wipe`) | One vulnerability-scanned, content-addressed Debian base on `E2_HIGHCPU_8`, `diskSizeGb: 200`; current Debian Python, Docker CLI, and test packages installed over signed HTTPS metadata | `lint`, fake-disk pytest under Xvfb 72 DPI, preview verification, negative test, amd64 ISO build, and controlled QEMU verification. Outputs remain ephemeral unless an operator explicitly invokes `--publish-release`; the standard-library publisher is post-QEMU, no-overwrite, byte-verified, and completion-marked. |

```bash
python3 -m pytest                          # fast checkout (fake lsblk, no nwipe)
./scripts/test-all.sh
dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest  # 72 DPI like the live USB
BEAMO_WIPE_NO_OPEN=1 ./preview --web && ./preview --console < /dev/null
./scripts/build-iso.sh                       # amd64 live image (prefer Cloud Build on this Mac)
./scripts/ci-cloud.sh                        # or: gcloud builds submit --project=beamo-wipe
```

## Phases (`scripts/ci-hosted.sh`)

| Phase | Step | What it runs |
| --- | --- | --- |
| `lint` | `lint` | Blocking compile, ShellCheck, and Ruff security rules; full Ruff and mypy remain advisory reports |
| `tests` | `python-tests` | `xvfb-run … 72 DPI` with `BEAMO_WIPE_DRY_RUN=1`; destructive-boundary spies use fake runners, never real `nwipe` |
| `preview` | `preview` | `BEAMO_WIPE_NO_OPEN=1 ./preview --web` + `--console` + `--helper` (fake disks) |
| `negative` | `negative-test` | Waits for every source-reading gate, deliberately breaks `assert_boot_excluded`, expects the e2e test to fail, and restores from a private `mktemp` backup even on signals |
| `iso` | `iso-build` | Waits for the restored negative-test workspace, then performs a privileged linux/amd64 build with no host `/dev` bind, content-addressed Debian build image, strict versioned output, PVD/size checks, manifest + sidecars |
| `qemu` | `qemu-verify` | Exact verified ISO, read-only image inspection, Debian fixed-vulnerability scan, shipped nwipe on a proved disposable loop, and mandatory BIOS+UEFI probes; no host binary/image fallback |

`./scripts/ci-hosted.sh all` runs every verification phase in dependency order. Skip flags: `SKIP_ISO=true` / `SKIP_QEMU=true` (cloudbuild substitutions `_SKIP_ISO` / `_SKIP_QEMU`). `_PUBLISH_RELEASE` defaults to `false`; `./scripts/ci-cloud.sh --publish-release` is the explicit production path and refuses either skip. The publisher step explicitly maps Cloud Build's immutable `$BUILD_ID` substitution into its process environment; the publisher rejects a missing or malformed identifier before any upload.

## Triggers

`scripts/install-cloud-triggers.sh` creates (requires the Cloud Build GitHub App connected to `BeamoINT/beamo-wipe` first):

- `beamo-wipe-pr-gate` — PRs targeting `main`: lint, tests, preview, negative, ISO (QEMU skipped via `_SKIP_QEMU=true`).
- `beamo-wipe-main-gate` — pushes to `main`: the full gate including QEMU.

The installer pins the production project's existing, constrained build service
account explicitly; Cloud Build must not fall back to a legacy or implicit
identity. Re-running the installer reconciles both triggers instead of silently
accepting stale event, repository, substitution, or service-account settings.
For a different project, set `BEAMO_WIPE_CLOUD_BUILD_SERVICE_ACCOUNT` to a
fully qualified service-account resource in that same project.

Branch protection on `main` should require these Cloud Build statuses.

## Billing

Cloud Build bills the `beamo-wipe` project (free tier covers 120 build-minutes/day; `E2_HIGHCPU_8` burns faster — watch the billing dashboard). The full gate is roughly half an hour of worker time, mostly ISO + QEMU. Prefer the PR gate's QEMU skip for iteration; `main` always runs everything.

## Failure triage

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `TclError: no display name and no $DISPLAY` | Runner not using `xvfb-run … 72 DPI` | Use `dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72"`; never use VNC `DISPLAY=:1` at 96 DPI. |
| `test_iso_build_uses_https_debian_mirrors` / `test_live_config_xinit… FileNotFoundError` | `lb config` not run | Skipped automatically when `packaging/live/config/{bootstrap,binary}` are absent; run `./scripts/build-iso.sh` to generate them and cover those tests. |
| `test_manifest_*` fail with `untraceable source state` | Build workspace has no `.git` | `.gcloudignore` must not exclude `.git/` (locked by `test_cloud_submit_uploads_git_metadata`). |
| `test_manifest_*` fail with `missing checksum: ISO not found` | Manufacturing ISO absent | Those tests skip without `dist/beamo-wipe-0.1.0-amd64.iso`; build it or fetch the release artifact. |
| `test_boot_exclusion … FAILED` while `negative-test` passed | Real safety regression | Do not mute: fix `src/beamo_wipe/safety.py` / `discover.py` / `wizard.py` gate; add reproduction fixture under `tests/fixtures/`. |
| `sha256sum` mismatch or ISO <80 MiB | Stale `packaging/live/config/includes.chroot` | `cp -R src/beamo_wipe …` is done by `scripts/build-iso.sh`; ensure `BEAMO_WIPE_VERSION` matches `src/beamo_wipe/__init__.py`. |
| `docker: permission denied` | User not in `docker` group on nested VM | Use `sudo docker` (see `.cursor/start.sh`); ensure `/etc/docker/daemon.json` has `fuse-overlayfs` on nested hosts. |

Local triage: reproduce with `BEAMO_WIPE_DRY_RUN=1 xvfb-run … python -m pytest -k "not test_iso_build and not test_live_config"` then `BEAMO_WIPE_NO_OPEN=1 ./preview --web`.

## Required checks

Branch protection on `main` should require the Cloud Build triggers (`beamo-wipe-pr-gate` on PRs, `beamo-wipe-main-gate` on pushes). See `scripts/install-cloud-triggers.sh`.


## Desktop and regular-file packaging checks

Use the repository-pinned Go 1.26.5 for shipped builds. From `desktop/`,
`go test -race ./...` and `go vet ./...` run the local launcher gate.
`GOOS=windows GOARCH=amd64 go test -c -o /tmp/beamo-desktop-windows.test.exe`
compiles the Windows suite; run that executable on an isolated x64 Windows
worker to test the actual Win32 and Windows PowerShell paths. Cross-compilation
is not native execution. The Windows fixtures include Unicode identities and
512-byte/4096-byte sector layouts.

The Linux utility integration test enumerates disks only when
`BEAMO_DESKTOP_NATIVE_INVENTORY_TEST=1`; `scripts/ci-desktop.sh` opts in on its
isolated hosted runner. Leave it unset on developer machines. All other local
launcher tests use fixture data and fake firmware. No test requests a host
restart.

The hosted Python phase installs `dosfstools` and `mtools`. With those tools on PATH, `tests/test_usb_image_readback.py` builds
64 MiB regular-file FAT32 fixtures, embeds them at the image's 1 MiB partition
offset, and checks manifest/launcher readback and failure cases. No mount,
loop device, or physical device is used. This does not replace ISO provenance,
Syslinux/GRUB boot, or the full 2 GiB image gate. The image builder writes its
checksum and ISO-binding sidecars only after successful final-image readback.
