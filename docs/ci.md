# Hosted continuous integration

GitHub Actions on this org is billing-blocked. The hosted gate is **Google
Cloud Build** in project `beamo-wipe`.

```bash
./scripts/ci-cloud.sh
# or
gcloud builds submit --project=beamo-wipe
```

`cloudbuild.yaml` runs two steps in parallel:

1. **python-tests** — `xvfb-run … python3 -m pytest` (fake lsblk, no real disks)
2. **iso-build** — `./scripts/build-iso.sh` in privileged Docker, then ISO 9660
   / size / SHA-256 checks

Neither step execs nwipe on a host disk. A successful ISO is copied to
`gs://beamo-wipe_cloudbuild/releases/<commit>/`. The manufacturing image
customers get is the GitHub Release asset, not that bucket. Pass
`_SKIP_ISO=true` only for a pytest-only debug build
(`./scripts/ci-cloud.sh --skip-iso`).

Intended GitHub App triggers in `beamo-wipe` (connect the repo once in
[Cloud Build GitHub](https://console.cloud.google.com/cloud-build/triggers;add=github?project=beamo-wipe),
then `./scripts/install-cloud-triggers.sh`):

- `beamo-wipe-pr-gate` — pull requests targeting `main`
- `beamo-wipe-main-gate` — pushes to `main`

Until that App connection exists, agents still run `./scripts/ci-cloud.sh`
after local pytest so every change is executed on Google Cloud.

Local `python3 -m pytest` / `./scripts/test-all.sh` stay the fast checkout
gate. ISO/QEMU work does **not** run on the Apple silicon Mac or the
Hostinger VPS; Cloud Build is the x86_64 place that always runs them.

QEMU interactive wipe (`docs/vm-test.md`) still needs a disposable KVM VM.
The hosted gate proves the ISO exists and is a bootable ISO 9660 image.
