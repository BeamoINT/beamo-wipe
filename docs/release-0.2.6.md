# Beamo Wipe 0.2.6

This release adds guarded Windows and Linux desktop entry points and a
Windows-readable FAT32 USB image, alongside the hybrid live ISO. Opening the
launcher performs readiness checks; an explicit action requests a restart only
when the original USB and one exact firmware entry can be identified. Otherwise,
it provides boot-menu guidance. No erase starts from the desktop.

The wizard, launcher, browser preview, and boot helper now share quieter
colors, smaller headings, flatter cards, and consistent actions. Disk names and
serials wrap fully, details are keyboard-accessible, and the picker keeps the
selected disk visible on smaller screens.

Safety and recovery fixes reject conflicting disk observations and unresolved
mounted ancestry, share one runner lock across approved log locations, reject
duplicate diagnostic JSON fields and hard-linked diagnostic logs, preserve
report export when optional logs fail, and stop console erasure if terminal
input becomes unavailable. A desktop inspection timeout now receives accurate
retry guidance. Final erase confirmation still requires an explicit action
after the countdown and rejects held/repeated Enter presses.

The accompanying regression suites and dated reports are committed with the
source. The UI validation build `da8f1338-7acb-4824-af55-9a3faf3217b4` passed
1,673 Linux tests, ISO/provenance, five virtual boot modes, and the shipped
wizard's disposable erase and report export. The tagged production build must
repeat all required gates before the publisher uploads artifacts.

Download the `.img` for the desktop-readable USB layout, or the `.iso` for
traditional ISO workflows, together with their SHA-256 sidecars. Image metadata
binds the USB image to the verified ISO. The GCS publisher writes
`RELEASE_COMPLETE.txt` last, after verifying all uploaded bytes. The GitHub
release exposes the matching image, ISO, provenance, and checksums.

Pinned nwipe 0.42 remains the only erase engine. Virtual tests include enrolled
Secure Boot firmware; physical Windows 10/11, USB/controller, firmware trust,
and novice usability coverage remain incomplete. The launchers are unsigned;
OS permission and reputation prompts may apply. SHA-256 detects corruption but
does not authenticate the publisher. Do not infer universal compatibility,
automatic execution on insertion, or coverage of inaccessible SSD areas.
