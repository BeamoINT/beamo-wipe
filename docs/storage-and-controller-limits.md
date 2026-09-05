# Storage, controller, and certification limits — Beamo Wipe 0.2.2 (nwipe 0.42)

> **Version 1.0 — 2026-09-02 | Owner: Accountable senior engineer (this checkout) | Next review 2026-12-02**
> Pinned engine: `nwipe v0.42` commit `6082bde060091e66365d852a1877f2ee80c67105` at `/usr/lib/beamo-wipe/nwipe`
> Wrapper `0.2.2` GPL-3.0-or-later; nwipe GPL-2.0. See `THIRD_PARTY.md`.

Beamo Wipe is a guided `nwipe` front-end. It does not implement a wipe engine, a sanitizer, or a certificate. This page separates **verified behavior** (code, pinned build, tests) from **recommendations** and **unknowns** (hardware-dependent), and gives honest guidance for SSDs, hidden areas, encryption, RAID, damaged drives, and when to use vendor tools or physical destruction instead.

It uses the same language as the wizard UI (`src/beamo_wipe/copy.py`), packaging (`docs/ADVANCED.md`), README, helper (`helper/index.html`), and result evidence (`src/beamo_wipe/evidence.py`). Tests pin that sync.

---

## 1. Safety boundary (applies everywhere in this doc)

- Never run `nwipe` against a real disk from the dev machine. `./preview` and `pytest` use fake `lsblk` JSON only (`tests/fixtures/*.json`, `src/beamo_wipe/demo_*.json`), `BEAMO_WIPE_DRY_RUN=1`, `DryRunRunner`.
- ISO/QEMU only on isolated x86_64 with disposable `qcow2` (`qemu-img create -f qcow2 /tmp/beamo-wipe-target.qcow2 10G`), no host-disk passthrough, VM torn down after.
- Fail closed on any missing/conflicting/stale/changed boot or target identity, state, or evidence → no selectable targets, `SafetyError`, no `nwipe` invoked. See `docs/boot-exclusion-signals.md`.
- Invariants never relaxed: boot exclusion, exact `/dev/` whole-disk binding (`/dev/sda` not `sda1`, `/dev/nvme0n1` not `n1p1`, rejects `sr0`/`nbd*`), ownership checkbox, type-to-confirm (`SAFE_TOKEN_RE`, trimmed casefold), 5 s delay (`COUNTDOWN_S=5.0`), no-auto-start, pinned nwipe, logs under `/tmp/beamo-wipe/` never on target (`FORBIDDEN_LOG_ROOTS`, `_log_filesystem_is_target`).

---

## 2. Verified behavior (reproducible)

All rows are asserted by code, the pinned build, or a fake-disk test. No physical destructives on the dev host.

| Topic | Verified statement | Source / evidence | How to repro |
|---|---|---|---|
| Engine identity | Only `nwipe v0.42` at `/usr/lib/beamo-wipe/nwipe` is ever exec'd. Checked as root-owned ELF `7F 45 4C 46`, not writable by group/other, no symlink, `nwipe -V` prints `nwipe version 0.42` line (not substring), `--force` never passed. Stub `/usr/local/bin/nwipe` refuses direct use. | `src/beamo_wipe/__init__.py: NWIPE_PINNED_*`, `packaging/live/config/hooks/normal/0500-build-nwipe.hook.chroot` (tag+commit, `GIT_CONFIG_NOSYSTEM=1`), `src/beamo_wipe/nwipe_runner.py: assert_nwipe_binary_safe()`, `resolve_nwipe_binary()`, `test_nwipe_runner.py`, `test_security_hardening.py` | `cat /usr/share/doc/beamo-wipe/NWIPE_VERSION` on live USB; `502-patched negative test` in `docs/ci.md` |
| How to invoke | Always `nwipe --autonuke --nogui --nowait --method=<prng\|dodshort\|zero> --verify=<last\|off> --rounds=1 --exclude=<boot> --logfile=/tmp/beamo-wipe/... --PDFreportpath=noPDF --noblank <target>` with exactly one `/dev/` target last, exactly one `--exclude` of the boot device, target size re-checked via `block_rdev` + `assert_size_unchanged` before `Popen`, `pass_fds` lock, `cwd="/"`, `shell=False`, `start_new_session True`. | `src/beamo_wipe/methods.py`, `src/beamo_wipe/nwipe_runner.py: build_nwipe_argv()`, `validate_argv()`, `docs/ADVANCED.md` | `python -m pytest tests/test_nwipe_runner.py -k validate` |
| What overwrite does | `nwipe` writes sequentially through the block device (`write(2)` on the opened `/dev/` node). For `prng`: one PRNG pass; `dodshort`: three passes: a pattern, its inverse, then random data (nwipe's DoD short); `zero`: one zero pass. `verify=last` reads back the last pass; `verify=off` skips verification; `noblank` skips final blank. No ATA/NVMe sanitize command is issued. | nwipe 0.42 `src/nwipe.c` + `src/method.c` (upstream), `src/beamo_wipe/nwipe_runner.py` comment `--method=prng --rounds=1 --verify=last --noblank` etc., `docs/ADVANCED.md` mapping | `nwipe --help` on live image (shows methods), `grep verify src/beamo_wipe/methods.py` |
| HDD best case | Overwriting and read-back verification cover the exposed block-device storage. Hidden or remapped sectors may remain. The evidence outcome `verified` requires `verify=last`, exit 0, and positive target-completion evidence, with no failure markers or interruption. | `src/beamo_wipe/nwipe_runner.py: evaluate_nwipe_completion()`, `src/beamo_wipe/evidence.py: OUTCOME_VERIFIED` | `tests/test_nwipe_runner.py`, `tests/test_evidence.py` |
| Storage warning surfaces | Method selection in Tk, GTK, console, and the browser gallery shows device-type guidance from the canonical storage notice. Evidence `warnings[]` uses the same notice. SSD, HDD, and unknown fixtures retain their classification; offline full limits are reachable from method selection. | `src/beamo_wipe/storage_limits.py: notice()`, `src/beamo_wipe/evidence.py: _warnings_for()`, `tests/test_storage_limits_ui.py`, `tests/test_tk_runtime.py` | `python3 -m pytest tests/test_storage_limits_ui.py tests/test_tk_runtime.py` |
| Evidence truthfulness | JSON under `/tmp/beamo-wipe/result-*.json` with `schema_version=1`, `beamo_wipe_version`, `nwipe_version/commit`, `device` (realpath+serial+wwn+vendor), `method`, `boot_device`, `timestamps`, `nwipe.argv_redacted`, `exit_evidence`, `verification{requested,verified}`, `warnings`, `outcome` in `{started,running,completed,verified,failed,interrupted}` (never `certified`/`sanitized`), `failure_reason`, `log_checksum_sha256`, `provenance{evidence_file,written_at_wall}` + atomic `.sha256` sidecar, `O_NOFOLLOW` `0o600`, `assert_log_not_on_target`. `verify_evidence_checksum()` checks sidecar. | `src/beamo_wipe/evidence.py`, `tests/test_evidence.py` | `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest tests/test_evidence.py -v` |
| No sanitization claim | No output, UI string, evidence field, or doc claims "certified," "sanitized," "DoD/NIST/NSA certified," "guaranteed unrecoverable," or "Blancco replacement." Forbidden phrases are pinned by tests. | `docs/claims.md` (forbidden list), `tests/test_ui_system.py: test_no_forbidden_claims_in_any_surface`, `tests/test_copy.py` | `grep -r certified docs src --include="*.md" --include="*.py"` |

### Terminology that is pinned

- **Overwrite** = nwipe's sequential `write()` pass(es) to the exposed block device. Not "sanitize," not "secure erase," not "purge."
- **Verified** (`evidence.outcome == "verified"`) = `method.verify == "last"` **and** exit 0 **and** positive completion evidence for the selected target, with no failure markers or interruption. Read-back checks exposed storage; it does not prove that hidden copies were erased. `zero --verify=off` can only be `completed`, never `verified`.
- **Completed** = exit 0 **and** positive completion evidence for the selected target, with no failure markers or interruption, and `verify=off` requested. Verification was not performed. Exit 0 alone is insufficient for either success outcome.
- **Failed / Interrupted** = any busy (`IN USE`), aborted (`Nwipe was aborted by the user`), open failure, `No sane device geometry`, `>>> FAILURE! <<<` / `|-FAILED-|` / `UABORTED` / `INSANITY`, non-zero exit, or cancelled — never upgraded to success. See `src/beamo_wipe/nwipe_runner.py: evaluate_nwipe_completion()`.

---

## 3. Overwrite limits — why overwrite alone is not a certificate

> Host overwrites do not establish coverage of these areas. A successful completion can coexist with data remaining outside the exposed storage. Exact behavior depends on the device and controller.

| Limit | What happens | Scope for Beamo Wipe | Recommendation |
|---|---|---|---|
| **Wear leveling & out-of-place writes (SSD, eMMC, UFS, SD)** | Flash controllers can move logical writes between physical pages and keep old copies outside host access. | Overwriting reaches only exposed storage. An unknown classification stays unknown; NVMe transport alone is not proof of SSD media. Method selection shows the canonical notice. | Additional overwrite passes do not fix inaccessible flash coverage. Consult exact-model vendor guidance if more assurance is required. |
| **Remapped / grown defects (HDD and SSD)** | Remapped physical storage may be outside host access and may retain old data. | Neither additional overwrite passes nor successful read-back establish coverage of those areas. | Save available evidence and ask support about the required assurance. |
| **Over-provisioning & OP area** | Reserved flash may be unavailable through host logical addresses. | Beamo cannot establish coverage of those areas. | Vendor support and validation vary; use a qualified destruction service if required assurance cannot be established. |
| **TRIM / discard / deallocate** | If `discard` was issued to LBAs, the controller may return stale, zero, or indeterminate bytes; subsequent reads are not evidence of overwrite durability. Not piped through `nwipe`'s path. | Not issued by Beamo Wipe (`libata` discard is not in `build_nwipe_argv`). Treat as unknown if the live layer issued discards elsewhere. | Do not rely on "read-back zero" after trim as sanitization proof. |
| **NVMe vs SATA controller** | A logical overwrite is different from controller-specific erase operations. | Beamo issues no controller secure-erase or sanitize commands. Disposable QEMU disks do not model physical flash behavior. | Consult the drive maker for the exact model and firmware; do not assume command support or coverage. |
| **eMMC / UFS / SD controller** | Main storage and controller-managed or reserved areas can have different exposure. | Only an eligible whole-disk target is offered. Boot partitions and other ineligible nodes cannot be selected; reported excluded nodes are informational. | Do not claim coverage of unexposed areas. Use model-specific guidance or qualified destruction. |
| **HPA / DCO (HDD)** | Host Protected Area / Device Configuration Overlay can restrict host-visible capacity. | Hidden areas are outside the overwrite guarantee. Beamo does not expand capacity or change these settings. | Do not bypass protection or alter geometry to force a wipe. Ask support to assess the required assurance. |
| **NVMe namespaces & hidden namespaces** | Only exposed namespaces can be discovered. | An erase targets exactly one selected whole-disk path; it does not prove coverage of other or hidden namespaces. | Ask the manufacturer to establish supported coverage for the exact controller. |
| **RAID / RST / mdadm / LVM / dm-crypt** | A controller or mapped volume can hide physical members and caches. | Supported whole-disk and transport rules remain unchanged. An exposed virtual disk does not prove every physical member was erased. | Consult a qualified storage provider. Beamo does not reconfigure arrays or bypass exclusions. |
| **Damaged / pending sectors** | Unreadable or unwritable storage can cause an incomplete erase or verification failure. | The evidence validator preserves reported errors. Inability to open a device and unusable geometry have distinct canonical explanations. | Save available evidence and contact support; do not force access or automatically retry. |
| **Damaged + verify=off** | A reported write failure never becomes successful completion, even when verification was intentionally skipped. | Quick zero: 1 overwrite pass: zeros. Verification is not performed. No read-back pass. Validated successful completion is completed without verification; failed writes remain failed. | Save available evidence and contact support. Do not automatically retry an erase. |

All of the rows above end the same way: **overwrite is not a certificate.** Evidence only records `outcome` + `verification{requested,verified}` + `log_checksum_sha256`. It never writes `certificate`, `sanitized`, or `compliant`.

---

## 4. Encryption states — what the wizard does and does not touch

| State | How it appears | Wizard behavior | Supported? | Guidance |
|---|---|---|---|---|
| **No encryption, FS accessible** | Normal `lsblk` `FSTYPE` fat32/ntfs/ext4, no LUKS layer | Normal pick → overwrite → evidence as usual. | **Supported** | Standard flow. |
| **BitLocker / SED / OPAL / ATA Security locked** | A device may expose a node yet refuse an operation. | All eligibility, ownership, confirmation and final preflight checks still apply. Open or geometry failures remain separate outcomes. Beamo does not unlock devices or extract keys. | **Degraded (fail-closed)** | Consult support and model-specific guidance; no password reset, SAM edits or Secure Boot circumvention. |
| **LUKS / dm-crypt** | `/dev/mapper/*` or LUKS on raw member | Filtered via `HIDDEN_NAME_RE` / `is_wipeable_disk` (mapper not whole-disk) and `REMOTE_BUS_TOKENS` never offered. Raw member below LUKS is offered as `sda` whole-disk overwrite (which will overwrite the LUKS container, as for any HDD). | **Raw-member only** | Document: we overwrite the whole device, not the mapped name. Only exposed storage is overwritten; this does not prove key destruction or coverage of hidden encrypted copies. |
| **APFS / FileVault / T2** | May expose APFS container partition on `sda2`; T2 internal not enumerated or shows behind bridge. | Apple Silicon not supported at all (claims). T2 internal not supported. APFS partition not a wipe target (whole-disk only, not `sda2`). | **Unsupported** | Do not claim APFS/FileVault handling. Direct to destruction for T2 boards. |

Supporting tests: `tests/test_nwipe_runner.py` open/geometry/busy mocks, `docs/compatibility-matrix.md` ST-11 / Unsupported rows, `docs/boot-exclusion-signals.md` `disk_identity` tuple.

Never claim: BitLocker recovery, OPAL unlock, or "sanitize an encrypted SSD by overwriting the ciphertext."

---

## 5. When vendor secure erase or physical destruction is the right answer

Use this decision table in support. Do not down-sell from it to make a sale.

| Customer need | What to do | Evidence you can give |
|---|---|---|
| **HDD, healthy, no reallocated sectors, no HPA/DCO, no RAID, recycling/resale with no cert required** | **Beamo Wipe** Everyday `prng --verify=last` is the project default. `Done → outcome verified` + JSON log. | `outcome verified` + `log_checksum_sha256` + `| Erased |` row. Plain owner hand-off. Tell customer it is overwrite, not a lab cert. |
| **HDD with reallocated/pending sectors, or damaged/UNC errors, or unknown HPA/DCO, or customer asks for certificate** | **Do not claim overwrite.** Save available evidence and seek a qualified assessment or **physical destruction**; do not automatically retry. | If attempted and failed, show `failed` + `No sane device geometry` / `could not open` + log. |
| **Any SSD/NVMe/eMMC/UFS/SD requiring assurance beyond exposed storage** | Consult exact-model manufacturer guidance and independently validate its supported coverage. If the required assurance cannot be established, use a qualified physical destruction service. Extra Beamo overwrite passes do not fix these limitations. | A vendor process has its own evidence and limits. Beamo does not perform or certify it. |
| **RAID / RST / SED-l Locked / OPAL-locked / T2** | **Not supported** — do not treat an exposed virtual device as proof about physical members. Consult a qualified provider about the exact hardware and required assurance. | Beamo does not reconfigure arrays, unlock devices or certify a vendor process. |
| **Hidden areas / namespaces** | If HPA/DCO or hidden NVMe namespace is known or suspected, **vendor guidance** must establish the supported coverage or **destroy**. | Vendor sanitize log; not Beamo overwrite. |
| **Regulated / lab-certificate required (government, healthcare, finance)** | **Destruction** or a certified facility. Beamo is explicitly **not a lab certificate** and never a Blancco replacement. | Beamo JSON is owner-operated evidence (who/when/what), not third-party certification. Point to destruction receipt. |

How to say it on the phone (plain language, from `src/beamo_wipe/copy.py`):

> "This USB does a write-over pass with nwipe. On a regular hard disk that's usually what people want. On an SSD the drive decides where writes land, so leftover copies can remain in its spare area. We don't call that certified. If more assurance is required, consult the drive maker about supported coverage for the exact model, or use a qualified destruction service."

The canonical storage notice is prominent at method selection and is also included in evidence warnings. Full supported limits are available from the same screen.

---

## 6. Ownership, result messaging, and fail-closed guidance — no bypass

- **Ownership is a gate, not a hint.** `Owner checkbox` must be checked before Pick; `assert_ready_to_wipe` raises `Owner checkbox` if not. README and wrapper `NOTICE` say: "You run it as the owner … or with written permission." Support must not encourage a friend to "just check it." If ownership is uncertain, do not proceed.
- **Result wording is fixed.** `outcomes.py` maps validated evidence to the same explanation in native views, console, reports and recovery. Successful read-back says “Erase completed; verification passed”. Successful Quick zero says “Erase completed; verification was not performed”. Confirmed user cancellation says “Stopped by you”. Failures, interruption, missing evidence and unknown states stay distinct; none becomes success from exit 0 alone. See the exact outcome table in `docs/runbook.md`.
- **Fail-closed help, not bypass.** When boot identity is uncertain or a disk disappears between pick and Last chance, the wizard shows: `We cannot tell which disk is this USB. Unplug extra USB sticks and start again.` or `Could not check the disks again. Erase did not start.` plus `Selected disk is not in the safe list.` / `identity` message. Guidance is: unplug hubs, try direct port, allow USB boot in firmware, disable fast boot — **not** "pass `--force`" (never built) and **not** "pick sda1." nwipe is never called with `--force`.
- **Packaging says it plainly.**
  - `helper/index.html` banner: "This page does not erase anything. Restart the computer and press the key for your PC."
  - `README.md` top: "No warranty. Owner-operated sanitization before recycle or resale. Not a lab certificate."
  - `NOTICE`: "This is owner-operated disk erasure before recycle or resale. It is not a lab certificate, not a Blancco replacement, and not a claim that every SSD controller will make data unrecoverable."

Back-office policy: a support ticket that asks to bypass ownership, EDID, or the 5 s delay must be closed with the fail-closed copy plus a link to this doc. No script or flag is offered.

---

## 7. Honest supported / degraded / unsupported — summarized

| Bucket | What we handle | Reference |
|---|---|---|
| **Supported** | Legacy BIOS + UEFI (Secure Boot disabled) via `syslinux`+`grub-efi`, USB-A/C when firmware lists the stick, NVMe/SATA HDD/SSD/virtio/eMMC main device, same-size disambiguation via `confirm_spec`, 5 s delay, proof-of-attempt JSON. | `docs/compatibility-matrix.md` FW/ST rows |
| **Degraded (works but not a certificate)** | Any SSD/NVMe/eMMC overwrite as above, damaged reallocated media, PICK_EMPTY only-eMMC, hub-boot, 800×600/HiDPI. Documented as overwrite, not sanitization. | This doc §3 |
| **Unsupported / out of scope** | Apple Silicon, Chromebooks, RAID controllers (hardware), Apple T2 internal, `nbd/iscsi/fc/nvmeof`, BitLocker/OPAL/Sed locked without prior unlock, HPA/DCO hidden LBAs, hidden NVMe namespaces, Windows in-OS wipe from inside the running OS. Correctly listed-with-no-targets or fails closed. | `docs/compatibility-matrix.md` Unsupported, `docs/claims.md` forbidden list |

---

## 8. Consistent language — use this table

Any surface (wizard, gallery, README, helper, evidence, dist `README.txt`, Amazon listing via `docs/claims.md`, support reply) **must** use the left column and **must not** use the right.

| Say | Do not say |
|---|---|
| "overwrite," "write-over pass," "Everyday / Three overwrites / Quick zero" with nwipe names in Advanced | "sanitize," "purge," "secure erase" (unless naming a vendor tool), "certified," "DoD 5220.22-M / NIST 800-88 certified," "NSA," "military grade," "guaranteed unrecoverable," "impossible to recover," "plug and play," "any laptop / any computer / any Mac," "Apple Silicon supported," "Blancco replacement," "we invented the wipe" |
| "SSD results depend on the drive's controller. Not a formal certificate." | "SSD is fully erased / sanitized" |
| "Overwriting reaches only storage the device exposes. It cannot guarantee coverage of inaccessible, remapped, over-provisioned (spare), or controller-managed flash areas. Additional overwrite passes do not fix these limitations." (method selection and report warning) | "SSD overwrite is certified" |
| "Overwrite is not a lab certificate. Do not tell customers otherwise." (ADVANCED) | "This SSD is now certified" |
| "HDD overwrite via nwipe. SSD results depend on the drive's controller. Not a Blancco-style certificate." (claims) | "Works with any SSD guarantee" |
| `evidence.outcome` in `{completed, verified, failed, interrupted}` + `verification.verified` boolean | Any `certificate`, `sanitized`, `compliant` field |
| "Owner-operated erasure before recycle or resale. No warranty." | "We take ownership liability" |

Pinned by: `tests/test_copy.py: FORBIDDEN`, `tests/test_ui_system.py: test_no_forbidden_claims_in_any_surface`, and the new `tests/test_storage_limits.py` below.

---

## 9. Source and evidence table — what was checked, when, by whom

| Source | What it proves | Last checked | Owner |
|---|---|---|---|
| `nwipe` upstream 0.42 release + tag `v0.42` + commit `6082bde060091e66365d852a1877f2ee80c67105` (`git rev-parse HEAD` in hook) | Engine identity + method list | 2026-09-02 (pinned; re-checked by Cloud Build hook on every ISO) | Accountable senior engineer (this checkout), then Cloud Build `pkg live` log |
| nwipe `--help` + `src/method.c` + `src/nwipe.c` (PRNG/dodshort/zero, `--verify`, `--noblank`, SIGUSR1) | The three wizard choices mean exactly `--method=prng|dodshort|zero --verify=last|off --rounds=1 --noblank` | 2026-09-02 via code inspection + `docs/ADVANCED.md` mapping (no physical destructive run) | Same |
| `src/beamo_wipe/methods.py` + `src/beamo_wipe/nwipe_runner.py` `build_nwipe_argv()` + `validate_argv()` + `evaluate_nwipe_completion()` | Flags that ship + failure/verified logic | 2026-09-02 via `tests/test_nwipe_runner.py` (40 tests, fake logs) | Same |
| Debian `live-build` hooks + `beamo.list.chroot` + `inside-docker.sh` (tag+SHA pin, ELF/PATH check, stub) | Build locks in wrapper + boots | 2026-09-02 via `scripts/build-iso.sh` dry inspection (no build on this Mac) | Same |
| `src/beamo_wipe/evidence.py` `build_evidence()` / `OUTCOME_*` / `verification{requested,verified}` / sidecar | Result JSON never mints `certificate`; `verified` requires last-pass 100% or `| Erased |` | 2026-09-02 via `tests/test_evidence.py` (20 tests, fake results) | Same |
| This doc §3 rows on wear leveling, OP, TRIM, HPA/DCO, namespaces, RAID | Controller limits are **recommendations** based on published vendor specs + nwipe upstream notes on overwrite not being a sanitize. Not reproduced on a real NVMe/SD controller in this checkout. | 2026-09-02 (literature, not lab destruction) | Same; lab reproduction would need x86_64 KVM + real NVMe/SAS per `docs/vm-test.md` optional hardware lab (owner disks only) |
| `docs/compatibility-matrix.md` ST/FW/BM tables + `tests/fixtures/*.json` | Firmware/boot-media/multi-disk/support bars | 2026-09-01 via `tests/test_compatibility_matrix.py` (23 tests) + Cloud Build pytest @72 DPI | Same |
| `docs/accessibility-lowres-matrix.md` | Keyboard-only / focus / low-res proof for retiring hardware | 2026-09-02 via `tests/test_accessibility_lowres.py` + `tests/test_tk_runtime.py` @72 DPI | Same |

Review cadence: every release and whenever the pinned nwipe commit, Debian base, or method mapping changes. Update pin, `docs/ADVANCED.md`, this table date, and `tests/test_storage_limits.py` in the same commit; CI (`tests/test_ui_system.py` + `tests/test_copy.py` + new `tests/test_storage_limits.py`) must still pass before push.

---

## 10. Reproducible checks (no real wipe)

```bash
# Language pins
python3 -m pytest tests/test_copy.py tests/test_ui_system.py tests/test_storage_limits.py -v
grep -r "certified\|sanitize.*nwipe\|Blancco replacement" src docs --include="*.py" --include="*.md" | grep -v "Not a\|Forbidden\|Do not tell" ; echo ok:$?
grep -rn "SSD_FOOTER" src/beamo_wipe --include="*.py" | head -5
BEAMO_WIPE_NO_OPEN=1 ./preview --web && grep -c "Not a formal certificate" web-preview/index.html

# Verified-behavior unit gates (fakes only)
python3 -m pytest tests/test_nwipe_runner.py tests/test_evidence.py tests/test_safety.py -v
python3 -m pytest -q -k "not tk_runtime"  # fast gate

# Preview on this machine (fake disks)
./preview --web      # never wipes; open full storage limits from method selection
```

Physically proving wear-leveling / OP retention requires a sacrificial SSD + vendor tools + firmware-level reads and is not run on the dev Mac. That row is cited as a published controller property, not as an observed failure on a given Samsung/Micron/WD sample in this checkout.

---

*Verification before merge: every SSD/encryption/RAID row above has a recommendation, every claim has a source row, no file in `src/ docs/ helper/` contains a forbidden badge term outside its "forbidden" list, and the three preview paths still use fake disks only.*


<!-- BEGIN CANONICAL OFFLINE LIMITS -->
## Offline supported storage limits

What this tool supports
Beamo Wipe uses pinned nwipe v0.42 to overwrite a selected whole disk exposed to the operating system. It does not issue controller secure-erase or sanitize commands. It does not support Apple Silicon Macs, Chromebooks, or erasing the running Windows disk.

SSD and flash storage
Overwriting reaches only storage the device exposes. It cannot guarantee coverage of inaccessible, remapped, over-provisioned (spare), or controller-managed flash areas. Additional overwrite passes do not fix these limitations.

Read-back verification
Read-back verification checks exposed storage against the final overwrite. It does not prove that hidden copies were erased.

Hard disks, hidden areas, and damaged media
Hidden HPA/DCO areas, remapped or unreadable sectors, and unexposed NVMe namespaces are outside the overwrite guarantee. A drive can report completion while hidden data remains. Read or write errors, missing completion evidence, and interruption must not be treated as success.

Unknown devices and controllers
A missing device type stays unknown. A USB bridge or RAID controller may hide the media type, physical members, caches, or capacity. An exposed virtual disk does not establish coverage of every physical member. Do not use a displayed SSD or HDD label as proof that hidden areas are absent.

Encryption and locked devices
Beamo Wipe does not unlock BitLocker, OPAL, ATA security, or other locked devices; extract keys; reset passwords; or bypass Secure Boot. Overwriting an exposed encrypted device is not proof of key destruction or coverage of hidden encrypted copies. Mapped volumes and partitions are not whole-disk targets.

When to use a different process
If you need coverage beyond exposed storage, consult the drive maker's guidance for the exact model and firmware. Vendor secure erase support and validation vary; this USB does not perform or certify that process. For required assurance that cannot be established, use a qualified destruction service. Beamo reports are not a formal certificate.

Ownership and safety
Erase only disks you own or have written permission to erase. Confirm the device identity and keep backups. Destructive-action warnings, boot exclusion, the confirmation token, and the five-second delay still apply. If identity is uncertain, stop; do not bypass the safety gates.
<!-- END CANONICAL OFFLINE LIMITS -->

Pinned upstream references: [nwipe v0.42 SSD limitations](https://github.com/martijnvanbrummelen/nwipe/blob/6082bde060091e66365d852a1877f2ee80c67105/README.md#ssd-considerations-and-limitations) and [SSD guide](https://github.com/martijnvanbrummelen/nwipe/blob/6082bde060091e66365d852a1877f2ee80c67105/ssd-guide.md). Rechecked 2026-09-05; vendor support is model-specific and is not a Beamo capability.
