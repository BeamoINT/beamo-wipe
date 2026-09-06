# Desktop entry and ordinary USB boot

Status: implementation in progress, 2026-09-06. No new platform claim is established by this design.

## Customer flow

Insert the USB, open Start Beamo Wipe, let the automatic read-only check finish,
and explicitly request a restart. The live wizard remains the only erase engine
entry. It asks for ownership, exact target confirmation, and the existing delay.
A restart request never authorizes an erase after boot.
Ordinary BIOS/UEFI boot remains independent of the desktop launcher.

The first delivery keeps both system and separate-drive erasure offline. The
current nwipe-only boundary has no native Windows implementation. Installed
Linux erasure needs a separate running-system ancestry and exclusive-access
model; it must never be enabled by removing the live-session gate.

## Visual direction

Use Beamo's navy #0A1B34, yellow #FDED02, white #FFFFFF, ink #17243B,
muted #536176, and error #B3261E. Use the installed system sans-serif, large
left-aligned text, one main action per step, and visible keyboard focus.
No decorative dashboard, algorithm menu, or device-path selector. The browser
is only a local presentation surface; no internet or account is required.

    Beamo Wipe                         Close
    Ready for a guided restart
    Save your work. You choose and confirm the disk after restarting.
    [ Restart into Beamo Wipe ]

## Restart boundary

- The launcher has no erase, format, mount-write, or engine invocation API.
- Direct restart is offered only for an exact active UEFI boot option whose
  hard-drive partition identity belongs to the USB holding the launcher.
  A label such as USB or Beamo is never sufficient identity.
- Require the shipped media layout, USB transport, stable OS identity, no
  existing BootNext request, and bounded valid EFI load-option data.
- Re-read the media and boot option in the elevated helper. Compare with the
  inspected plan before changing anything. Do not accept a target device path
  or an arbitrary command from the browser or command line.
- Write only BootNext, verify readback, and request a normal reboot without
  forcing applications closed. Restore only our unchanged BootNext value if
  reboot fails. Do not modify permanent boot order or Secure Boot settings.
- Unsupported firmware, missing/ambiguous entry, missing privileges, changed
  devices, and unsupported architecture receive a clear manual boot path.
- No automatic launch, restart, or erase on insertion. No automatic erase on
  boot. Preview cannot invoke platform mutation APIs.

## Local UI boundary

Bind an ephemeral IPv4 loopback port. Require the exact Host and Origin plus
a random per-process token for API calls. The opening fragment is removed from
the address bar; tab-scoped session storage retains only this token so refresh
works, and Close clears it. Serve only embedded assets, prohibit
framing and external content, reject other methods and malformed bodies, and
never place device identifiers in browser responses. Require an explicit restart
button after the check. Repeated requests cannot start concurrent helpers. Close and
idle timeout end the process; it is not an installed background service.

## Required evidence

Unit tests must exercise ambiguous/malformed EFI paths, device changes,
pending boot requests, read/write failure and rollback, browser request
authorization, repeated actions, and preview separation. Compile both shipped
executables. Exercise real Windows and Linux UI/runtime behavior in isolated
environments. Run existing Python, hosted ISO, BIOS and UEFI gates; add a
Secure Boot gate using enrolled firmware before advertising it. Test the
launcher from the flashed-media layout, not only extracted files. Physical
machines and novice usability remain distinct evidence requirements.

## Packaging and remaining compatibility boundaries

The ISO remains the ordinary optical/hybrid boot artifact. A separate `.img`
uses one active FAT32 MBR partition, so Windows can expose the application
files. Its BIOS loader is Syslinux; its EFI files come from the signed Debian
ISO. The image builder accepts no physical-device or output-path argument:
it creates regular files only, verifies the source ISO provenance, and reads
both launchers back through FAT32. The hosted gate boots this actual image.

Opening files is explicit. Windows may show publisher/reputation warnings;
the current Windows executable has no Authenticode signature. Linux desktop
file execution/trust rules vary, and a noexec mount cannot run this ELF directly.
No automatic insertion launch or universal double-click claim is justified.
An exact existing USB Boot#### entry is required for direct restart; firmware
that exposes only a generic USB path receives manual boot instructions.
Windows applications can veto a requested restart after ExitWindowsEx returns;
then BootNext may remain for the next restart. This never authorizes erasure.

Native Windows Server runtime tests cover the actual Win32 read-only API and
PowerShell inventory parser with simulated disks. They do not establish
Windows 10/11 Explorer, SmartScreen, UAC, USB mounting, or firmware handoff
behavior. Linux unit tests and OVMF boot tests do not replace novice or physical
hardware acceptance testing. Keep these limits in the release evidence.
