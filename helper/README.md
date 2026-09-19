# Boot helper

`index.html` is the Windows/macOS helper. The ISO builder copies it to the USB
data partition as `START-HERE.html` and fills the identity markers from the
same `build-identity.json` written into the live image. The git copy is labeled
**not a manufactured USB image**.

It does **not** erase disks. It shows this image's build, typical boot-menu
keys, separate Windows 10 and Windows 11 Recovery Environment steps, a BitLocker
recovery-key warning before firmware changes, and an offline guided
chooser for USB missing, an ineffective boot-menu key, firmware refusal,
and launcher failure. A last card names **beamosupport.com** in text and
as a phone-scannable code so someone can open this page on another
computer with no network. All required steps stay in the file so the USB
works offline. The desktop launcher help uses the same four branches
for someone already in the application; kiosk recovery and the Intel Mac
Option key stay on this USB page because the launcher does not run on
macOS and kiosk recovery is post-boot.

The printed card can say “open START-HERE.html on that Windows PC.”
Do not promise every computer: Intel/AMD PCs that boot from USB only —
not Apple Silicon Macs, not Chromebooks (see `index.html`). The helper
describes this USB, not older sticks.
