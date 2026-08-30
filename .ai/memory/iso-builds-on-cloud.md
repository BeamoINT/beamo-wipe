# Heavy x86_64 image builds: use GCP or AWS, not this Mac

On the Apple silicon Mac, Docker `linux/amd64` is QEMU user emulation, and
`qemu-system-x86_64` is TCG (no KVM). Live-ISO builds and “boot the ISO
and wipe a throwaway disk” tests are too slow and too flaky to be the gate.

Cursor Cloud Agent VMs are x86_64 Ubuntu with `/dev/kvm`. There, local
`./scripts/build-iso.sh` and KVM QEMU are native. Nested Docker needs
`fuse-overlayfs`.

**For Beamo Wipe ISO builds, and any similar amd64 live image / nested-VM
work: use Google Cloud Build (`./scripts/ci-cloud.sh`, project `beamo-wipe`)
or a throwaway x86_64 VM.** Do not spend a session waiting on local TCG.

## How

- **Default:** `./scripts/ci-cloud.sh` (or `gcloud builds submit --project=beamo-wipe`).
  Cloud Build runs pytest under Xvfb and `./scripts/build-iso.sh` on amd64.
  GitHub Actions is not the gate. See `docs/ci.md`.
- Interactive QEMU wipe (`docs/vm-test.md`): spin an **amd64** Debian/Ubuntu
  VM (GCE `n2-standard-4` / EC2 `t3.large` or similar; nested virt / KVM on),
  boot the ISO against a disposable 10G qcow2, then **tear the VM down**.
- Persist hashes and a Cloud Build log URL, not duplicate ISOs on the laptop.
- `gcloud` on this machine may be pinned by `CLOUDSDK_*` env vars to
  `beamo-support-deployer`; `scripts/ci-cloud.sh` unsets those.

Local `python3 -m pytest` and `./preview` stay on the Mac.
The ISO/KVM path does not.
