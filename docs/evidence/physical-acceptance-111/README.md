# Physical computer and USB acceptance — #111

**Status (2026-09-15):** prep only. Physical matrix execution has **not** started.

| Gate | Marker |
| --- | --- |
| This agent / development machine | **BLOCKED** — no dedicated Beamo Wipe lab hardware is attached |
| Every matrix row below | **NOT TESTED** |
| Notion card #111 | **In progress** (must not be marked Done) |
| Manufactured-image identity for a lab stick | **not recorded** — fill [BUILD-IDENTITY.md](BUILD-IDENTITY.md) at lab time |
| QEMU / USB-lab / GCP desktop VM / `./preview` | **not a substitute** for this matrix |

Do not copy a Pass from `docs/compatibility-matrix.md`, `docs/qemu-verify.md`, `docs/usb-simulation-lab-2026-09-07.md`, `docs/gcp-desktop-validation-2026-09-07.md`, or any `docs/evidence/usb-lab-*` receipt into a cell here. Those are Tier 1 or Tier 2. This page is the Tier 3 operator matrix defined in [`docs/evidence-tiers.md`](../../evidence-tiers.md).

No hardware model, firmware string, screenshot, or pass mark in this folder is a lab result. Empty fields are empty on purpose.

## 1. What “done” means (measurable)

#111 is complete only when **all** of the following are true. Until then the card stays In progress.

1. **Build identity is complete** on [BUILD-IDENTITY.md](BUILD-IDENTITY.md): wrapper version, source commit (dirty state), `nwipe` version and commit, ISO filename and SHA-256, USB `.img` filename and SHA-256 (if used), manifest filename and SHA-256, media serial if known, flash date, operator, UTC date.
2. **Dedicated safe hardware** was used: spare x64 PC, no valuable disks (disconnected where practical), spare USB whose contents may be replaced, manufactured image only. This development machine is not that hardware.
3. **Named-machine receipts** exist for every firmware class you intend to advertise:
   - Legacy BIOS boot to the wizard
   - UEFI with Secure Boot off (or firmware that does not enforce it) boot to the wizard
   - UEFI with Secure Boot on and no enrolled Beamo key: firmware **refuses** the USB (expected; not a product bug)
   - At least one vendor boot-menu key path from [`docs/boot-card.md`](../../boot-card.md)
4. **Representative coverage** is recorded (Pass, Fail, or Excluded with a reason — never an invented Pass) for:
   - Monitors: the built-in panel, and one external display if the PC has a video output
   - Ports: a direct USB-A port, and a USB-C port or USB-C adapter
   - USB controllers: one USB 2 host path and one USB 3 host path when the PC has both
   - Keyboard: the keys needed to reach the wizard and move through the first screens
   - Touchpad: pointer works, **or** Excluded because the machine has no touchpad
   - Audio: UEFI beep and/or spoken startup on hardware that has a speaker, **or** Fail with the diagnostic log (`pulseaudio_failed` / `orca_failed`), **or** Excluded if there is no speaker
   - Power: wall power connected; on a laptop, lid closed while idle, short power-button press, and the on-screen power reminder. Held power-button and lid-during-erase are recorded even when firmware cuts power.
5. **Every executed cell** points at a photo and/or log under `photos/` or `logs/` named with the row ID. Unexecuted cells stay **NOT TESTED**.
6. **No virtual result is marked Pass.** QEMU, the USB simulation lab, GCP desktop VMs, Xvfb, and `./preview` may be cited only in the gap inventory as “already known, not this matrix.”
7. **Optional erase** (section 10 of the procedure) ran only on a disk labeled `DISPOSABLE`, with owner authorization, after the boot USB was confirmed absent from the pick list. A successful overwrite is not a sanitization certificate.

A single machine can cover several rows. One Pass on a Dell BIOS laptop does not transfer to an HP UEFI desktop.

## 2. Result markers

Use exactly these words in the Result column.

| Marker | Meaning |
| --- | --- |
| **Pass** | On the named machine, with the recorded image, the expected result happened. Evidence path is filled. |
| **Fail** | The expected result did not happen. Evidence path and what you saw are filled. |
| **Excluded** | This machine cannot run the row (no touchpad, no battery, no USB-C, Apple Silicon, and so on). Reason is filled. |
| **NOT TESTED** | Nobody has run this row yet. Default for every row in this folder. |
| **BLOCKED** | Cannot run until a named dependency exists (hardware, manufactured image, owner authorization). |

Never upgrade **NOT TESTED** to **Pass** without a named machine, recorded image SHA-256, and evidence file. A safe refusal (for example Secure Boot rejecting an unenrolled image) is a **Pass** only when the row’s expected result is that refusal.

## 3. Related documents (what they actually prove)

| Document | Proves | Does **not** prove |
| --- | --- | --- |
| [`docs/compatibility-matrix.md`](../../compatibility-matrix.md) | Which combinations we *intend* to support; fixture/QEMU rows | Physical boot, ports, panels, speakers, lids |
| [`docs/desktop-hardware-acceptance.md`](../../desktop-hardware-acceptance.md) | Desktop-launcher checklist shape | Any physical desktop; every case is still NOT TESTED |
| [`docs/evidence-tiers.md`](../../evidence-tiers.md) | Tier 1/2/3 definitions; every Tier 3 claim is UNVERIFIED | A physical receipt |
| [`docs/usb-simulation-lab-2026-09-07.md`](../../usb-simulation-lab-2026-09-07.md) and [`usb-lab-20260907/`](../usb-lab-20260907/) | QEMU EHCI/xHCI/BOT/UAS against a hardware *model* | Electrical USB, flash, vendor firmware, physical ports |
| [`docs/evidence/laptop-power-20260914.md`](../laptop-power-20260914.md) | Source merge of power *guidance*; physical pending | Battery, lid, or power-button on a real laptop |
| [`docs/evidence/live-session-power-20260910.md`](../live-session-power-20260910.md) | logind/Xorg policy in source + pytest | Firmware lid or held power button |
| [`docs/qemu-verify.md`](../../qemu-verify.md) | Isolated ISO boot + disposable `qcow2` wipe | SATA/NVMe firmware, USB bridges, real Secure Boot |
| [`docs/gcp-desktop-validation-2026-09-07.md`](../../gcp-desktop-validation-2026-09-07.md) | Debian 12 and Windows *Server* VM launchers | Windows 10/11 PCs, physical USB controllers |
| [`docs/screen-reader.md`](../../screen-reader.md) | GTK/Orca/AT-SPI in CI; QEMU speech *entry* | Physical speaker, sound card, or braille |
| [`packaging/live/`](../../../packaging/live/) | What the live image is supposed to contain | A flashed stick |

## 4. Honest gap inventory

### Already on file (not #111 acceptance)

- Desktop USB checklist: [`docs/desktop-hardware-acceptance.md`](../../desktop-hardware-acceptance.md) — every case **NOT TESTED**.
- Compatibility firmware rows FW-01…FW-06: [`docs/compatibility-matrix.md`](../../compatibility-matrix.md) §4 — QEMU/fixture “Supported”; physical boot-menu keys are Tier 3 UNVERIFIED by nature ([`docs/evidence-tiers.md`](../../evidence-tiers.md) §4).
- USB simulation lab (2026-09-07): [`docs/usb-simulation-lab-2026-09-07.md`](../../usb-simulation-lab-2026-09-07.md), receipts under [`docs/evidence/usb-lab-20260907/`](../usb-lab-20260907/). The lab’s own line: “Physical USB acceptance: Not established.” Gate note: [`usb-lab-20260907/linux/boot-gate/untested-physical.txt`](../usb-lab-20260907/linux/boot-gate/untested-physical.txt) (“No physical hardware was tested by this gate”).
- Earlier QEMU USB notes: [`docs/vm-usb-simulation-2026-09-06.md`](../../vm-usb-simulation-2026-09-06.md).
- Cross-platform verify: [`docs/evidence/cross-platform-verify-20260908/README.md`](../cross-platform-verify-20260908/README.md) — “Every configuration in `docs/desktop-hardware-acceptance.md` remains NOT TESTED”.
- Laptop power source work: [`docs/evidence/laptop-power-20260914.md`](../laptop-power-20260914.md) — “Physical acceptance: pending.” Local 13-case procedure mentioned there lived under `dist/task-57-baseline/` and was **not** committed.
- Live-session power policy receipts: [`docs/evidence/live-session-power-20260910.md`](../live-session-power-20260910.md) — lid close, held power button, and battery vs AC are **Not run**.
- Display layout: Xvfb 72 DPI in CI (`DISP-01`/`DISP-02`); not a panel.
- Audio: PulseAudio + Orca + espeak-ng are *packaged* (`packaging/live/config/package-lists/beamo.list.chroot`); QEMU selects the speech boot entry. No physical speaker receipt.
- Input: `xserver-xorg-input-libinput` and `AllowMouseOpenFail` in `packaging/live/config/includes.chroot/etc/X11/xorg.conf.d/10-beamo.conf`. No physical keyboard or touchpad receipt.
- This checkout’s `dist/` still holds a **0.1.0** ISO under `dist/quarantine-ui-20260908/`. It is not a 0.2.9 manufactured image and must not be treated as the lab stick.

### Still missing (blocks #111 Done)

- Any named physical PC (vendor, model, firmware mode, firmware version).
- Any manufactured-image SHA-256 recorded against a flashed spare USB used on that PC.
- Physical results for firmware, monitors, ports, USB controllers, keyboards, touchpads, audio, and power — all rows in `results/` are **NOT TESTED**.
- Physical Secure Boot *trust store* behavior (revocation, enrolled vs unsigned).
- Physical USB connector/flash/power quality (the USB lab cannot supply this).
- Physical Orca/speaker output and mute/HDMI-audio routing.
- Physical lid, short power-button, held power-button, and real battery readings.
- Any Tier 3 destructive receipt on a `DISPOSABLE` disk.

## 5. How to run on dedicated safe hardware

Operator-facing steps. Technical IDs stay in the worksheets.

### 5.1 Before you touch a computer

1. Use a **spare** x64 PC. Not a customer machine. Not this development host. Not a VM.
2. **Disconnect or remove disks you care about.** If an erase test is in scope, leave only the disk labeled `DISPOSABLE` plus the Beamo USB. Record model, capacity, and serial of every disk that stays connected.
3. Use a **spare USB** whose contents may be replaced. Flash only a manufactured image Jack has authorized for this lab session. Do not invent an ISO; do not use `dist/quarantine-ui-20260908/` unless Jack explicitly identifies it as the session image.
4. Record identity **before** the first boot: fill [BUILD-IDENTITY.md](BUILD-IDENTITY.md). Verify checksums (`cd dist && sha256sum -c …` as in [`docs/release-verification.md`](../../release-verification.md)).
5. If the PC might boot Windows again, confirm you can reach the BitLocker recovery key **before** changing firmware, boot order, or Secure Boot ([`docs/boot-card.md`](../../boot-card.md)).
6. Never run `nwipe` against a disk from a development shell. Never pass a host disk into QEMU as a stand-in for this matrix.

### 5.2 Flash and first look (does not erase a PC disk)

1. Write the authorized `.img` (desktop-readable) or ISO to the spare USB with a tool Jack specifies. Record the writer, host OS, and USB port used to flash.
2. On a running Windows 10/11 x64 or Linux desktop you are willing to restart: insert the USB. Confirm files are visible. Insertion must not start an erase. Follow [`docs/desktop-hardware-acceptance.md`](../../desktop-hardware-acceptance.md) and [results/desktop-usb-launch.md](results/desktop-usb-launch.md).
3. Ordinary opening, readiness, and a restart do **not** require erasing another disk.

### 5.3 Firmware boot (does not erase a PC disk)

1. Plug the USB into a **direct** USB-A or USB-C port on the PC, not a keyboard hub if you can avoid it.
2. Open the firmware boot menu (Dell F12, HP F9/Esc, Lenovo F12, and the rest on the boot card).
3. Expected when Secure Boot is off or not enforcing: the Beamo menu appears; picking the ordinary guide opens the wizard and erases nothing.
4. Expected when Secure Boot is on and no Beamo key is enrolled: firmware rejects the USB or does not list it. Record the exact message. Do not ship a circumvention. Do not disable Secure Boot on a customer PC merely to make a row pass; on lab hardware you may toggle it to cover both rows.
5. Photograph the firmware menu, the Beamo menu, and the first wizard screen. Save under `photos/PHY-FW-…`.
6. On the pick-disk screen, confirm the Beamo USB is **not** selectable. If the USB cannot be identified, **no** disks may be selectable. Stop and record Fail. Do not continue toward erase.

### 5.4 Monitors, ports, USB, keyboard, touchpad, audio, power

Work the matching sheet. One reboot per port or controller is expected. For each cell: write the real vendor/model/firmware, the result marker, and the evidence filename.

Power rows: keep wall power connected and the lid open unless the row says to close it. Power readings on screen are advisory; they must not change disk selection or start an erase. A held power button may cut power; that is firmware, not a Beamo bug — record it.

Audio rows: the BIOS menu has no beep; the UEFI menu plays two short beeps only if the machine has a speaker. Preview mode starts no host audio.

### 5.5 Optional authorized erase (destructive)

Skip this entire section unless the owner of the disposable disk has authorized it in writing for this session.

1. Target is labeled `DISPOSABLE`. Record model, capacity, serial, bus.
2. Boot USB is identified and not selectable.
3. Owner checkbox, type-to-confirm token, five-second delay, explicit Erase.
4. Export the report if requested; keep wall power; do not close the lid.
5. After shutdown, independently inspect the disposable disk. Preserve the receipt and checksums.
6. A successful overwrite does **not** prove SSD hidden or remapped areas were erased. See [`docs/storage-and-controller-limits.md`](../../storage-and-controller-limits.md).

### 5.6 After the session

1. Leave unexecuted rows **NOT TESTED**.
2. Do not mark Notion Done.
3. Commit only markdown, logs you intend to keep, and photos that contain no secrets and no customer data. Never commit ISOs, USB images, or secrets. Stage explicit paths; never `git add -A`.

## 6. Matrix index

Fill the sheets, not this index. Every Result here is **NOT TESTED**.

| Sheet | IDs | Covers |
| --- | --- | --- |
| [results/firmware.md](results/firmware.md) | PHY-FW-01…12 | BIOS, UEFI, Secure Boot on/off, CSM, vendor boot-menu keys, Fast Boot |
| [results/monitors.md](results/monitors.md) | PHY-MON-01…08 | Built-in panels, external outputs, dual display, blanking, HiDPI, 800×600 |
| [results/ports.md](results/ports.md) | PHY-PORT-01…07 | USB-A, USB-C, adapter, front/rear, hub, dock |
| [results/usb-controllers.md](results/usb-controllers.md) | PHY-USB-01…06 | USB 2, USB 3, UAS vs BOT as the OS reports it, bridges |
| [results/keyboards.md](results/keyboards.md) | PHY-KB-01…07 | Internal/USB keyboard, layout, held Enter, boot-menu key, speech hotkey |
| [results/touchpads.md](results/touchpads.md) | PHY-TP-01…04 | Built-in pad, no-pointer start, USB mouse |
| [results/audio.md](results/audio.md) | PHY-AUD-01…06 | UEFI beep, BIOS silence, Orca/PulseAudio, HDMI/headphone, failure log |
| [results/power.md](results/power.md) | PHY-PWR-01…12 | AC, battery, lid, short/held power button, blanking vs sleep, advisory UI |
| [results/desktop-usb-launch.md](results/desktop-usb-launch.md) | PHY-DESK-01…16 | Running-OS insert, launchers, UAC/polkit, restart, Secure Boot desktop path |
| [results/optional-destructive.md](results/optional-destructive.md) | PHY-DEST-01…03 | Authorized `DISPOSABLE` wipe only |

Templates: [BUILD-IDENTITY.md](BUILD-IDENTITY.md), [photos/README.md](photos/README.md), [logs/README.md](logs/README.md).

## 7. Fail-closed disk safety (do not relax)

- Erase engine is pinned `nwipe` v0.42 only. No ATA/NVMe sanitize from Beamo.
- Boot USB must never be selectable. If identity is uncertain, list no disks.
- Confirm token, five-second delay, owner checkbox. No auto-start wipe on boot.
- Logs under `/tmp/beamo-wipe/`, never on the target.
- Never `--force`. Never more than one positional `/dev/…` target.
- No Apple Silicon, Chromebook, plug-and-play, or certificate claims.

This folder records lab observations. It does not change those rules.
