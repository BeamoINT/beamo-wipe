# Memory index

- [Product constraints](product-constraints.md) — nwipe wrapper only; 1-star reviews are boot UX and wrong-disk, not the TUI.
- [ISO builds on cloud](iso-builds-on-cloud.md) — hosted gate is Google Cloud Build (`./scripts/ci-cloud.sh`, project `beamo-wipe`); interactive QEMU wipe still uses a throwaway x86_64 KVM VM.
- [Visual verification on this Mac](visual-verification-on-this-mac.md) — `screencapture` is TCC-blocked; verify Tk via test_tk_runtime and pixels via headless Chrome on the web-preview deep links.
