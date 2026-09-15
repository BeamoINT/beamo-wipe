# Boot helper

`index.html` is the Windows/macOS helper. The ISO builder copies it to the USB
data partition as `START-HERE.html` and fills the identity markers from the
same `build-identity.json` written into the live image. The git copy is labeled
**not a manufactured USB image**.

It does **not** erase disks. It shows this image's build, typical boot-menu
keys, separate Windows 10 and Windows 11 Recovery Environment steps, and a
BitLocker recovery-key warning before firmware changes. All required steps
stay in the file so the USB works offline.

The printed card can say “open START-HERE.html on that Windows PC.”
Do not promise every computer: Intel/AMD PCs that boot from USB only —
not Apple Silicon Macs, not Chromebooks (see `index.html`). The helper
describes this USB, not older sticks.
