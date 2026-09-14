# Production qualification closeout — 2026-09-12

Status: **implementation and full hosted qualification complete; no release published**.
Author: Codex. Closeout branch: `feat/qemu-three-method-journeys`, based on
`feat/rendered-visible-coverage` / PR #26 at
`cd806f403d3fe8c105da5e4f53a5b1c7a93100b3`.

## Authoritative result

Qualified executable source: `535caef27c899e4d05c355bc6e6649688404713a`.
[Google Cloud Build 80ed909b](https://console.cloud.google.com/cloud-build/builds/80ed909b-7568-409a-8d85-bbce56daedd8?project=368895881889)
finished **SUCCESS** at 2026-09-12 20:41:29 UTC. Neither ISO nor QEMU was skipped.
The final closeout commit changes only this report after qualification.

| Check | Measured result |
| --- | --- |
| Hosted Python suite, isolated Xvfb at 72 DPI | **2,344 passed, 15 skipped**, 253.33 seconds |
| Local complete Python suite | **2,260 passed, 17 skipped**, 196.68 seconds |
| Hosted lint, previews, safety negative test | Passed |
| Desktop launcher gate | Passed: Linux tests, Windows cross-compilation, fuzzing and prescribed checks |
| amd64 live ISO | Passed; 563,085,312 bytes |
| Required measured gate receipts | All six passed: lint, tests, preview, negative, ISO, QEMU |
| Pinned nwipe v0.42 direct method boundaries | Everyday, Three overwrites and Quick zero, each twice |
| Full shipped BIOS wizard journeys | All three methods, each twice, on independent disposable fixtures |
| Guest target readback | Entire bounded target checked after every journey; Quick zero requires every byte zero |
| Report exports | All six passed clean FAT, method/count/wording, source/build identity, hashes and unmount checks |
| Firmware/media paths | BIOS ISO, UEFI ISO, BIOS USB, UEFI USB and enforced Secure Boot USB passed |
| Secure Boot state | Guest emitted `BEAMO_WIPE_SECURE_BOOT=1` with enrolled Microsoft firmware keys and SMM enforcement |
| Local Ruff, mypy, ShellCheck and diff checks | Passed; mypy covers 39 source files with the existing untyped-body scope |
| Resource teardown | QEMU gate passed with cleanup errors now blocking success |

The local skips are one missing Linux `gi` runtime, three Linux-kiosk fullscreen
cases, one isolated-X11 physical-key test, and twelve FAT32 fixtures requiring
dosfstools/mtools. The Linux kiosk cases execute in the hosted suite. Hosted
skips remain counted as skips; they are not fabricated passes.

## Artifact identity

These hashes came from strict post-QEMU manifest verification in the successful
build, after real gate execution and mounted-image package collection.

- ISO SHA-256: `c600982b589f8229ffddeb25c2f4d6ea70dc68d3cb728e6f143743cc640c9b90`.
- Final manifest SHA-256: `e03aff5491648f8bbe8bdb39c72be032ff815a2a3dc5ed58ca3674cf225e5b85`.
- Image package inventory SHA-256: `d8888ff6ce0b8fc72152e3677eb3f60749b72be33ca288d6c6ceb9e8277bbd0e`.

The built filename is `beamo-wipe-0.2.7-amd64.iso`; this qualification does not
create a new public version. Publication was explicitly disabled. The build
reported: "Release publication disabled; verified artifacts remain ephemeral."
The logs and identities are durable receipts, not a public artifact download.

## Completed implementation

- Finished inherited staged and unstaged startup, asynchronous discovery and
  refresh, long disk identity, review-screen overflow, and report UX work.
  Fixed actual Linux report-help clipping in both Tk and GTK.
- Scheduled the missing Tk startup completion poll; real event-loop tests cover
  successful and failed discovery. Pinned fullscreen geometry in both startup
  and wizard windows because the live startx session has no window manager.
  The old content-sized window reproduced as 800x680 on a 1024x768 display.
  The fixed picker settles without redraw loops and delivers key releases.
- Preserved confirmation tokens, owner confirmation, countdown and boot-disk
  exclusion. QEMU drives the shipped controls and real pinned nwipe, using only
  disposable image-backed targets with networking disabled.
- Corrected BIOS inline help to `TEXT HELP` / `ENDTEXT`; `MENU HELP` selects a
  help-file action. The ISO verifier checks the rendered boot menu and hotkeys.
- Completed both repetitions of all three method journeys. Target readback
  rejects conversion/I/O failure; host verification executes against actual
  production report bundles, including privacy copies, and rejects tampering.
- Connected CI to actual subprocess receipts, JUnit counts, retained-log hashes,
  source/build identities and package inventory from the mounted image.
  Build-only provenance can precede QEMU; strict final verification requires
  every measured gate. Duplicate, mismatched and tampered evidence is rejected.
- Completed inherited publisher/signature verification wiring and signing-key
  file-identity hardening. Tests use disposable keys. Production publication
  remains blocked without separately authorized release-key enrollment.
- Made cleanup fail qualification on detach/unmount failure while preserving
  attached backing files and original failure/signal status.

Additional focused proof includes 177 native Linux Tk/startup tests, real X11
key-release and autorepeat tests, and startup/fullscreen checks at 800x600 and
1600x1000 (five per display). The native ARM Linux container was a UI-only
reproduction using fake disks, not the amd64 ISO gate, and was removed.
A new Linux-only fullscreen test initially aborted macOS Tk; its platform
restriction is explicit and the complete local suite subsequently passed.

## Investigation receipts

These attempts were superseded by the successful build above. No failed or
cancelled attempt is represented as completed qualification.

| Source / build | Finding and correction |
| --- | --- |
| Initial local continuation | Expired Google authentication; user refreshed the authorized login |
| `b3d6fb9` / `abbfbd29-0d5c-4c0e-8504-92e69dadf64a` | Linux report-help clipping and a generated-helper staging assumption; corrected and regressed |
| `456f716` / `6608d97a-cd2f-4b22-8808-7607d8b542dc` | BIOS hotkey markup caused a verifier false negative; corrected while preserving missing-entry rejection |
| `bf16a0a` / `33b9e211-bde1-4367-ae2b-199a7c7a893b` | BIOS menu used help-file actions in boot entries; switched to inline help |
| `b717379` / `569fe476-922a-470d-9cdf-ac93e374bbea` | Tk startup never scheduled its worker-completion poll; reproduced success/failure stalls and fixed |
| `07e9fd3` / `bdee61c6-658b-41d7-80f6-7c5f21c23ee0` | First complete Everyday wipe/export worked; host verifier expected obsolete report schema; actual production-bundle regressions added |
| `73e039c` / `3e643a6a-2771-4fa7-9f88-29eb5357e9f7` | Cancelled immediately to include a separately reproduced cleanup failure; twelve teardown/exit-status cases pass |
| `620039d` / `14a359e6-fb3d-48d0-8c45-284a3b844fd6` | Both Everyday journeys passed; Three overwrites stopped before erasure with repeated picker redraws and missing release acknowledgement; bare-X11 fullscreen geometry regression reproduced the sizing fault |
| `535caef` / `80ed909b-7568-409a-8d85-bbce56daedd8` | Complete hosted gate passed, including every repeated method/export and firmware/media path |

[Syslinux menu semantics](https://kernel.googlesource.com/pub/scm/boot/syslinux/syslinux/+/ae853e99a7aed22cb28b387e1e3cb32dbf1ab8fa/doc/menu.txt)
support the BIOS help correction.

## Checkout, storage and scope

Qualification commits were made in the clean isolated clone
`/private/tmp/beamo-wipe-qualification-9lrqf315`. The shared checkout's inherited
index and working files were preserved, with all changed source files compared
against the qualification clone. Shared index SHA-256 remained
`f5d9ab8e46c1130123f136e2c90a969328c89de26753b0ceee9d33936ae97360`.
Only the closeout report differs from the exact qualified source after the gate.

Read-only storage reports ran before/after substantial work. The disposable
Linux test container was removed. No personal disks, unrelated files, dirty
worktrees or Docker volumes were removed. The qualification clone remains as
an intact handoff, and no ISO was built or downloaded on this Mac.

This completes software qualification under the repository's hosted gates.
It does not claim physical-hardware certification, native Windows 10/11
acceptance, macOS fullscreen acceptance, or a new production release. The
existing PR stack remains unmerged. Public release and production signing-key
enrollment remain outside the inherited authorization.

## Local supporting receipts

These temporary files may expire; the successful Cloud Build link and hashes
above are the durable qualification references.

- `/private/tmp/beamo-wipe-kiosk-closeout.log`, SHA-256 `7fabff43eab76945afc4ab5e6c7ac09008f65f6d9ee25333635cdb235391a48f`.
- `/private/tmp/beamo-wipe-kiosk-closeout.xml`, SHA-256 `f179eb02e96133577b218fc2dff3ab733f756e2a435962d8290041158a2f15d9`.
- `/private/tmp/beamo-wipe-qualified-build.json`, SHA-256 `5d49892e1ffcafd44b78e30b9e2064fd39f9ed81098a5e8bddff65393a1ef59a`.
- `/private/tmp/beamo-wipe-qualified-proof.json`, SHA-256 `c4cb3eaba11916dcf911e2103464b317b27e04d26e37ec28b88660b1402ae761`.
