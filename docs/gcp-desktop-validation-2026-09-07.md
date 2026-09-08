# Google Cloud desktop validation — 2026-09-07

The additional Windows and Linux desktop checks passed within the scope below.
No application source changes were needed. This does **not** establish universal
plug-and-play, Windows 10/11 acceptance, or physical USB compatibility.

The user explicitly approved transferring source, executables, test scripts,
and disposable VM-only login credentials after the
[initial approval-blocked attempt](desktop-vm-attempt-2026-09-07.md).
The requested preference to use temporary Google Cloud VMs for future Beamo
Wipe validation has been recorded in local memory.

## Exact configuration

Source commit: `f7b6490036d62281e2133da642557cee6710f081`, branch
`codex/desktop-entry`. Go 1.26.5 built both production executables and the
Windows test executable. Transferred binary hashes matched the local builds.
The transferred test archive SHA-256 was
`050f66035d2b69750be4d7ba1fbe30ee236198e3dfa73f82e19c4c96d787323e`.

Two temporary `n2-standard-4` VMs ran in project `beamo-wipe`, zone
`us-central1-a`, with private addresses, 60 GB auto-delete disks, no service
accounts, and three-hour automatic deletion limits:

| VM | Official image | Tested desktop |
| --- | --- | --- |
| `beamo-desktop-lab-0907b-linux` | `debian-12-bookworm-v20260902` | Debian 12 x64, Xfce, Chromium 152.0.7977.82 |
| `beamo-desktop-lab-0907b-windows` | `windows-server-2025-dc-v20260814` | Windows Server 2025 Datacenter x64, build 26100, Explorer and Edge |

Windows was controlled through a private RDP connection from the Linux VM.
Linux Xvfb provided the display; the final permission test used a real PAM login
session and the graphical polkit agent. These are controlled VM desktop tests,
not novice usability sessions. Windows Server is not Windows 10/11. Google's
[Windows Desktop licensing requirements](https://docs.cloud.google.com/compute/docs/instances/windows/ms-licensing-faq)
were not established for a Windows 10/11 VM in this task.

## Executed results

| Case | Result and evidence |
| --- | --- |
| Native Linux Go suite and race detector | PASS: 18 top-level passing cases, including the fuzz seed runner. Native vet completed successfully. |
| Native Windows Go suite | PASS: 16 top-level passing cases, including real Win32 read-only checks and the PowerShell inventory fixtures. These fixtures do not emulate a physical Windows USB controller. |
| Linux normal-user file launch | Double-clicking the executable in Thunar opened the actual browser UI. The copied application correctly refused direct restart and displayed boot-menu help. |
| Linux refresh, recheck, Close | Refresh and recheck worked; Close displayed completion and the launcher process exited. |
| Linux graphical permission cancellation | Actual polkit dialog appeared. Cancel returned exit 126, with “Request dismissed”; boot identity remained unchanged. |
| Linux graphical permission acceptance | The actual polkit log proves the helper ran as root. It then refused the invalid plan with “USB or boot settings changed,” exit 1. Boot identity remained unchanged. This was an explicit production-helper invocation, not the entire graphical USB-to-live flow. |
| Linux `noexec` FAT mount | A newly created 64 MiB FAT image blocked execution with “Permission denied.” HTML instructions remained readable. Whole-image SHA-256 was unchanged before/after the attempt; the mount was removed. No physical block device was targeted. |
| Windows administrator UAC cancellation | The real UAC dialog showed Unknown Publisher. Declining produced the app's explanation. After acknowledgement, zero launcher processes remained and boot time was unchanged. |
| Windows administrator UAC acceptance | Accepting UAC opened Edge and the actual app. The copied application correctly displayed the boot-menu fallback. |
| Windows administrator browser lifecycle | Refresh and recheck worked. Close removed the elevated launcher and its listening socket, with no reboot. |
| Windows standard-user UAC cancellation | `labguest` was verified not to belong to Administrators. Declining the credential prompt produced the explanation; after acknowledgement no launcher remained and there was no reboot. |
| Windows standard-user Explorer launch | Double-clicking the executable in Explorer requested an administrator's password. Using the disposable administrator credentials opened the app in the standard user's browser session. |
| Windows account boundary | Process-owner evidence confirmed the launcher was `labadmin`, while Explorer and all observed Edge processes remained `labguest`, in the same session 3. |
| Windows standard-user browser lifecycle | Refresh and recheck worked. Close stopped the elevated process and listener; boot time remained unchanged. |
| Windows read-only CLI output | Explicit stdout capture returned valid JSON with `ready:false` and copied-media guidance. No CLI exit-code claim is made: optional PowerShell collection/wait attempts did not complete before interruption. Native suite and graphical acceptance are independently evidenced. |

The [machine-readable receipt](evidence/gcp-desktop-20260907.json) contains exact
identities, checksums, process owners, cancellation/Close results, and cleanup
verification. Native logs: [Linux](evidence/gcp-desktop-20260907-linux-tests.txt)
and [Windows](evidence/gcp-desktop-20260907-windows-tests.txt).

## Visible behavior and remaining friction

The inspected interfaces were readable and usable in the tested desktops.
Screenshots preserve the [Linux launcher](evidence/gcp-desktop-20260907-linux.png),
[real polkit prompt](evidence/gcp-desktop-20260907-polkit.png),
[standard-user UAC prompt](evidence/gcp-desktop-20260907-windows-uac.png),
[Windows launcher](evidence/gcp-desktop-20260907-windows.png), and
[Windows Close result](evidence/gcp-desktop-20260907-windows-closed.png).

The Windows executable remains unsigned and UAC reports an unknown publisher.
Declining UAC shows a generic failure explanation rather than a dedicated
cancellation screen. Fresh Edge profiles required browser-owned onboarding;
tests continued without account sign-in, automatic imports, or optional
personalization. These steps are real friction, so “flawless” or automatic
plug-and-play claims would still be inaccurate.

The cloud desktop launchers were copied to ordinary filesystems. They properly
refused to claim these were original USB media. Google Cloud virtual disks are
not removable USB devices. Actual boot-image, USB-controller emulation,
BIOS/UEFI/Secure Boot, disk exclusion, wipe, and report-export evidence remains
in the [earlier VM report](vm-usb-simulation-2026-09-06.md) and
[passing full hosted gate](quality-review-2026-09-07.md). Runtime/test paths in
this source revision are byte-identical to the previously gated `fd39d5c`
revision. Those tests were not rerun during this desktop-only extension.

Still pending: Windows 10/11 Explorer/UAC/SmartScreen acceptance, additional
Linux distribution and desktop combinations, graphical restart from real USB
media, manufactured USB ports/controllers, physical firmware trust stores,
and novice testing. Insertion does not automatically run an application.
Erasure remains offline after an explicit reboot and separate wipe confirmation.

## Harness corrections, not product fixes

Early attempts exposed test-environment issues: a missing Go cache setting,
a Linux session without PAM/polkit registration, a missing terminal package,
PowerShell argument quoting, and a missing display name in a diagnostic
firewall rule. Those were corrected in the disposable harness before results
were counted. The RDP client was upgraded to Debian's official FreeRDP 3
backport and given an explicit local-account domain. Windows session logs
showed successful login but no Explorer process; starting Explorer at limited
user privilege made the desktop usable. Neither UAC nor the secure desktop was
disabled. Incomplete collection attempts were replaced by direct archive/file
retrieval. No setup attempt was counted as an application pass.

## Teardown and release boundary

Cleanup completed after the evidence was downloaded. Independent checks at
`2026-09-07T04:17:18.827017+00:00` confirmed no owned VMs, disks, firewall rules,
routers, subnet, or VPC remained. Cloud NAT was deleted with its router. The one temporary `labadmin` project SSH
metadata entry added by the test connection was removed with the metadata
fingerprint guard; unrelated entries were preserved. Disposable passwords and
password-bearing startup metadata are removed locally after cloud teardown.

No release, publication, deployment, or remote Git push was performed.
