# Live ISO packaging

Debian bookworm + live-build, run inside Docker, so the first process the
user sees is the Beamo Wipe wizard (startx → Tk, or console fallback).

Why Debian, not Alpine: old laptop storage/USB stacks and hybrid
BIOS+UEFI are the actual 1-star problem. A tiny Alpine image that fails
to boot on the PC in front of someone is a worse product.

Build from the repo root:

```bash
./scripts/build-iso.sh
```

Artifacts stay in `dist/` and are gitignored.
