# Desktop USB hardware acceptance

Use this checklist before claiming a manufactured USB supports a configuration.
The automated results are in [the validation report](desktop-validation-2026-09-06.md).
They do not fill in this checklist. No physical configuration has been accepted
by that report.

## Record the configuration

- Tester and date:
- PC manufacturer/model, CPU architecture, firmware version:
- OS edition/version and desktop environment (Linux):
- Secure Boot state and relevant firmware trust/revocation updates:
- USB model/capacity, connection/port, manufactured image SHA-256:
- Source commit and launcher version:
- Account type (standard/admin), execution policy, permission prompt result:
- Result: PASS / FAIL / NOT TESTED, evidence location, observed limitation:

Use the new `.img` and verify its published checksum and ISO binding. The old
ISO alone does not provide the new Windows-readable desktop layout. Only use a
spare USB whose contents may be replaced. Ordinary opening, readiness checks,
and a restart do not require erasing another disk. Any erase test needs a
separately identified disposable target and the owner's explicit authorization.

## Non-destructive acceptance

Run the applicable cases separately on Windows 10 x64, Windows 11 x64, and each
Linux distribution/desktop to be advertised. Record unsupported or refused
cases as such; do not count a safe refusal as proof of direct-restart support.

| Case | Expected result | Result / evidence |
| --- | --- | --- |
| Insert USB in a running OS | Files are visible; insertion itself does not execute the application or erase anything | NOT TESTED |
| Open the platform launcher | The offline browser UI opens; required UAC or Linux execution/permission prompts are understandable | NOT TESTED |
| Standard-user permission declined | No restart or erasure; the app explains the failure or permission requirement | NOT TESTED |
| Linux filesystem mounted `noexec` or desktop blocks execution | The restriction is documented; do not bypass OS policy or advertise seamless launch on this configuration | NOT TESTED |
| Exact existing USB EFI entry | Readiness identifies the USB; explicit restart enters that USB's Beamo Wipe welcome screen | NOT TESTED |
| No exact entry / generic USB entry / legacy BIOS desktop | Readiness gives boot-menu guidance; it does not guess a boot target | NOT TESTED |
| Another one-time boot request is already pending | Direct restart is refused without replacing that request | NOT TESTED |
| Remove or replace USB after readiness | Restart is refused after rechecking identity; no unrelated boot entry is chosen | NOT TESTED |
| Leave application idle, refresh, then Close | Refresh retains the current session while active; Close removes controls and the server exits | NOT TESTED |
| Cancel restart or an application vetoes it | No forced application closure or erasure; record whether firmware retains the requested one-time USB boot | NOT TESTED |
| Ordinary firmware boot-menu selection | USB reaches the welcome screen without the desktop launcher | NOT TESTED |
| Supported Secure Boot configuration | USB reaches the welcome screen with Secure Boot still enabled; record actual trust state | NOT TESTED |
| Repeat using advertised ports/controllers | The same media and identity remain usable; record failures by port/controller | NOT TESTED |
| Booted welcome screen with several attached disks | No erase starts; the boot USB is absent from selectable targets | NOT TESTED |
| Unknown boot-media identity | No disks become selectable | NOT TESTED |
| Exit before final erase confirmation | No target writes occur | NOT TESTED |

A restart may close unsaved work through normal OS prompts. Save work before
an intentional restart test. A Windows application veto can leave the already
requested one-time boot entry for the next restart; this does not authorize an
erase. Do not create or edit firmware entries on a customer's PC merely to make
the exact-entry test pass. A seeded virtual entry is a separate integration test.

## Optional authorized destructive acceptance

Use only the disposable target recorded by model, capacity and serial. Keep
valuable disks disconnected where practical. Check owner consent, target
identity, the exact confirmation token, the five-second delay, and the final
explicit erase action. Verify completion/report export and independently inspect
the disposable disk afterward. Preserve the receipt and checksum. A successful
overwrite is not evidence that SSD hidden or remapped areas were sanitized.

## Release decision

List configurations that passed, those that require manual boot, and those that
failed or remain untested. Resolve release-blocking failures before advertising
support. Keep Windows signing/reputation, Linux launch restrictions, firmware
coverage, and novice usability as separate observations. Do not convert the
results into claims of automatic launch, universal plug-and-play, Apple Silicon
support, or guaranteed data sanitization for every storage device.
