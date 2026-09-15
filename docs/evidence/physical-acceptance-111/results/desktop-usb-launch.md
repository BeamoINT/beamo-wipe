# Desktop USB launch results — PHY-DESK

Canonical case text: [`docs/desktop-hardware-acceptance.md`](../../../desktop-hardware-acceptance.md). That checklist is still entirely **NOT TESTED**. This sheet is the same work with evidence drop-paths.

GCP Debian 12 / Windows Server 2025 launcher checks ([`docs/gcp-desktop-validation-2026-09-07.md`](../../../gcp-desktop-validation-2026-09-07.md)) are VMs. They do not fill these cells.

Use the manufactured `.img` so Windows can see the launchers. The ISO alone is not that layout.

Every Result below is **NOT TESTED**.

| ID | Case | Expected | Host OS (fill) | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| PHY-DESK-01 | Insert USB in a running OS | Files are visible; insertion does not run the app or erase anything | | NOT TESTED | `photos/PHY-DESK-01-*` |
| PHY-DESK-02 | Open the platform launcher | Offline browser UI opens; UAC or Linux permission prompts are understandable | | NOT TESTED | `photos/PHY-DESK-02-*` |
| PHY-DESK-03 | Standard-user permission declined | No restart or erasure; app explains the failure | | NOT TESTED | `photos/PHY-DESK-03-*` |
| PHY-DESK-04 | Linux `noexec` or desktop blocks execution | Restriction documented; do not bypass OS policy | | NOT TESTED | `logs/PHY-DESK-04-*` |
| PHY-DESK-05 | Exact existing USB EFI entry | Readiness identifies the USB; explicit restart enters that USB’s Beamo welcome screen | | NOT TESTED | `photos/PHY-DESK-05-*` |
| PHY-DESK-06 | No exact entry / generic USB / legacy BIOS desktop | Readiness gives boot-menu guidance; it does not guess a boot target | | NOT TESTED | `photos/PHY-DESK-06-*` |
| PHY-DESK-07 | Another one-time boot request already pending | Direct restart refused without replacing that request | | NOT TESTED | `logs/PHY-DESK-07-*` |
| PHY-DESK-08 | Remove or replace USB after readiness | Restart refused after rechecking identity | | NOT TESTED | `logs/PHY-DESK-08-*` |
| PHY-DESK-09 | Leave idle, refresh, then Close | Refresh keeps the session while active; Close removes controls and the server exits | | NOT TESTED | `logs/PHY-DESK-09-*` |
| PHY-DESK-10 | Cancel restart or an application vetoes it | No forced app closure or erasure; record whether firmware kept BootNext | | NOT TESTED | `logs/PHY-DESK-10-*` |
| PHY-DESK-11 | Ordinary firmware boot-menu selection | USB reaches the welcome screen without the desktop launcher | | NOT TESTED | `photos/PHY-DESK-11-*` |
| PHY-DESK-12 | Supported Secure Boot configuration on this desktop | USB reaches welcome with Secure Boot still enabled; record actual trust state | | NOT TESTED | `photos/PHY-DESK-12-*` |
| PHY-DESK-13 | Repeat on advertised ports/controllers | Same media and identity remain usable; record Failures by port | | NOT TESTED | `logs/PHY-DESK-13-*` |
| PHY-DESK-14 | Booted welcome with several attached disks | No erase starts; boot USB absent from selectable targets | | NOT TESTED | `photos/PHY-DESK-14-*` |
| PHY-DESK-15 | Unknown boot-media identity | No disks become selectable | | NOT TESTED | `logs/PHY-DESK-15-*` |
| PHY-DESK-16 | Exit before final erase confirmation | No target writes occur | | NOT TESTED | `logs/PHY-DESK-16-*` |

Windows 10 x64, Windows 11 x64, and each Linux desktop you want to advertise need **separate** copies of this sheet or extra rows with the OS named in Host OS. Do not count a safe refusal as proof of direct-restart support.

Notes:
