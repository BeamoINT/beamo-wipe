# Boot helper

`index.html` is the Windows/macOS helper. Copy it to the USB data partition
as `START-HERE.html`.

It does **not** erase disks. It shows typical boot-menu keys, separate
Windows 10 and Windows 11 Recovery Environment steps, and a BitLocker
recovery-key warning before firmware changes. A last card names
**beamosupport.com** in text and as a phone-scannable code so someone
can open this page on another computer with no network. All required
steps stay in the file so the USB works offline.

An `.exe` is optional and not required for v0.1.0. The printed card can say
“open START-HERE.html on that Windows PC.”
Do not promise every computer: Intel/AMD PCs that boot from USB only —
not Apple Silicon Macs, not Chromebooks (see `index.html`).
