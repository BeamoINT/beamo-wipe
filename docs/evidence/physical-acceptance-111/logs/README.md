# Logs for physical acceptance #111

Drop text logs here. Prefer wizard diagnostics, firmware messages copied verbatim, `dmesg` excerpts from the **live USB session** (not from this development host), and PulseAudio/Orca failure markers.

Name files with the matrix ID:

```
PHY-AUD-04-pulseaudio_failed-20260915T130000Z.txt
PHY-DEST-01-report-export-notes-20260915T140000Z.txt
```

Do not copy QEMU serial logs from `docs/evidence/usb-lab-20260907/` into a Pass cell.

This folder is empty of lab logs as of 2026-09-15. That is expected.

Never store target-disk contents here. Live-session logs belong under `/tmp/beamo-wipe/` on the USB session; copy only what you need.
