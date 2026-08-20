# Heavy x86_64 image builds: use GCP or AWS, not this Mac

This Mac is Apple silicon. Docker `linux/amd64` is QEMU user emulation, and
`qemu-system-x86_64` here is TCG (no KVM). Live-ISO builds and “boot the ISO
and wipe a throwaway disk” tests are too slow and too flaky to be the gate.

**For Beamo Wipe ISO builds, and any similar amd64 live image / nested-VM
work: use the Google Cloud or AWS CLIs (`gcloud`, `aws`) and run the build
and QEMU tests on an x86_64 Linux VM (or Cloud Build / CodeBuild).** Do not
spend a session waiting on local TCG.

## How

- Spin an **amd64** Debian/Ubuntu VM (GCE `n2-standard-4` / EC2 `t3.large` or
  similar; nested virtualization / KVM on if you will boot the ISO with QEMU).
- Clone `beamo-wipe`, install Docker, run `./scripts/build-iso.sh`, then the
  QEMU steps in `docs/vm-test.md` against a disposable 10G qcow2.
- Copy the ISO out (GCS/S3 or `gcloud compute scp` / `aws s3 cp`). Persist
  hashes and a URL, not duplicate archives on the laptop.
- **Tear the VM down** when the test is done. Do not leave compute running.
- `gcloud` on this machine may be pinned by `CLOUDSDK_*` env vars to
  `beamo-support-deployer`; unset those per command if you need the user
  account (see workspace `cloudflare-pages-sites.md`).

Local `python3 -m pytest` and `python3 -m beamo_wipe --demo` stay on the Mac.
The ISO/KVM path does not.
