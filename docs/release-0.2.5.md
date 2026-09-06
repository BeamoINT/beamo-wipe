# Beamo Wipe 0.2.5

This maintenance release includes the three bug-fixing passes recorded in [pass one](audit-2026-09-06.md), [pass two](audit-2026-09-06-pass2.md), and [pass three](audit-2026-09-06-pass3.md).

- Keep cancellation available when runner status polling fails, clear recovered status warnings, and avoid retrying an invalid lock close.
- Preserve report retry and guarded shutdown after evidence-read or worker-construction failures, and label recovered diagnostic reports accurately.
- Close storage handles on error paths, avoid retrying failed closes, and preserve valid recovery journals and report preferences across short reads while retaining validation limits.

The three passes add 29 regression cases. Their final verification completed with 1,398 local tests and 1,570 hosted Linux tests passing, plus the full ISO and disposable BIOS/UEFI QEMU gate. The versioned production build must repeat the full hosted gate before the publisher saves its artifacts.

The release uses pinned nwipe 0.42. Existing confirmation, boot-media exclusion, device support, and storage-method limits remain in force. The ISO is unsigned; checksums detect corruption but do not authenticate the publisher. Physical-hardware and Secure Boot coverage is not established by the virtual tests.

Production artifacts are stored under the unique Cloud Build ID in `gs://beamo-wipe_cloudbuild/releases/`. `RELEASE_COMPLETE.txt` is written only after every declared artifact has been uploaded and its bytes verified. The GitHub release for `v0.2.5` provides the ISO, manifest, checksum sidecars, and `SHA256SUMS` after independent verification.
