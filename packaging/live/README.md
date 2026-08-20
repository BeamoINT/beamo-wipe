# Live ISO packaging

Debian bookworm + live-build, run inside Docker, so the first process the
user sees is the Beamo Wipe wizard (startx → Tk, or console fallback).

Why Debian, not Alpine: old laptop storage/USB stacks and hybrid
BIOS+UEFI are the actual 1-star problem. A tiny Alpine image that fails
to boot on the PC in front of someone is a worse product.

The chroot is built on the **container filesystem**, not a macOS bind
mount. Docker Desktop bind-mounts are `nodev`, and debootstrap needs
`mknod`. The ISO is copied to `dist/` at the end.

Build from the repo root:

```bash
./scripts/build-iso.sh
```

Artifacts stay in `dist/` and are gitignored.
