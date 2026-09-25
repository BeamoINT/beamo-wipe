# Beamo Wipe 0.2.10

This release incorporates the comprehensive safety and reliability audit in
`docs/bug-audit-2026-09-24.md`. It tightens boot USB exclusion, target identity
checks, owner authorization, nwipe result interpretation, report integrity,
desktop USB creation, ISO packaging, and release evidence checks. The audit
includes regression tests for the corrected paths.

The erasure engine remains pinned to nwipe 0.42. Beamo Wipe does not provide a
new erase method or claim coverage beyond the host-visible storage that nwipe
can access. The signed release manifest records the exact source commit,
artifact hashes, and hosted gate receipts. Consult
`docs/storage-and-controller-limits.md` before using the image on physical
hardware.
