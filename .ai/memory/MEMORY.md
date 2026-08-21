# Memory index

- [Product constraints](product-constraints.md) — nwipe wrapper only; 1-star reviews are boot UX and wrong-disk, not the TUI.
- [ISO builds on cloud](iso-builds-on-cloud.md) — amd64 live-ISO build and QEMU wipe tests go through `gcloud`/`aws` on an x86_64 VM, not this Apple silicon Mac.
- [Visual verification on this Mac](visual-verification-on-this-mac.md) — `screencapture` is TCC-blocked; verify Tk via test_tk_runtime and pixels via headless Chrome on the web-preview deep links.
