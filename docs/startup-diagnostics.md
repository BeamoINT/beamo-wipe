# Diagnostic reports when a wipe cannot start

The native graphical, screen-reader, and console interfaces offer **Diagnostic
report** on a blocked or empty disk list and after a failed start. Application
startup exceptions retain that support screen. The console uses `DIAGNOSTIC`
in sequential prompts or `D` in keyboard screens.

This report is **not erase evidence**. It has no outcome, selected disk,
verification result, exit code, or claim that an operation ran. Finished-wipe
report eligibility and the Finished-screen export remain independent.

1. Leave the Beamo boot USB and every existing disk connected. Remove the
   intended report USB. Open Diagnostic report and choose **Prepare**.
2. Preparation must identify the boot USB again and obtain two stable scans.
   Every existing disk is protected. If this cannot be established, saving
   stays blocked; retry preparation after resolving discovery. Never override
   boot identification or enter a device path.
3. Insert exactly one separate, writable removable FAT32 USB. Choose **Save
   diagnostic report**. The console requires literal `SAVE` (or `PREPARE` for
   the preparation step). FAT12/16, exFAT, NTFS, mounted/read-only media,
   ambiguous layouts, multiple new drives and changed original drives fail
   closed with a specific message. No formatting is offered.
4. Wait for “Diagnostic report saved and verified. Report USB is safe to
   remove.” An error or timeout is not success: shut down before removing
   media. Back and Shutdown are blocked while export is active. To restart
   preparation, return Back, remove the report USB, and reopen Diagnostics.

Files are in `BEAMO-WIPE-REPORTS/report-<random>/`: `diagnostic.json`, its
SHA-256 sidecar, `README.txt`, and a content-only `COMPLETE` checksum manifest.
The existing isolated mount worker validates identity, paths, and mount flags;
writes files atomically into a unique directory; synchronizes; unmounts;
remounts read-only; compares exact bytes; and unmounts again before success.
Incomplete exports lack a valid COMPLETE manifest. COMPLETE alone never means
safe to remove. Verify the SHA-256 sidecar and every manifest entry before
using the report; SHA-256 detects corruption, not an authenticated signature.

The schema permits only application version, pinned engine identity (not an
observed invocation), exact installed application digest, recorded source
commit/source digest/build ID and dirty-state flag, a fixed error code,
discovery status and boot-identification status, UTC timestamp with explicitly
unverified calendar-time confidence, elapsed session time from the monotonic
clock, UI type, OS family, architecture, and bounded fixed-code events (at most
32; report at most 16 KiB). Missing build metadata is explicitly unavailable;
metadata that disagrees with installed application bytes is `source_mismatch`.
An offline computer clock is never assumed correct merely because it looks
plausible. Elapsed time is session time, never erase duration.

No environment dump, raw diagnostic/nwipe log, serial, WWN, model, UUID, target
path, mount contents, disk contents, hostname, username, address, or secrets
are collected. The protected device fingerprints used to select media remain
internal to the export controller/worker and are absent from exported files.
Never request a raw inventory/log as a substitute for this startup report.

If firmware, the kernel, Python imports, or both display and console fail
before these interfaces can run, the application cannot generate a report.
Record the visible fixed error message and the distributed build identity
manually. No report can be recovered after shutdown unless it was exported.

If you requested a report, an unsaved diagnostic requires the explicit
**Shut down without saving?** decision. **Keep session open** returns to the
diagnostic screen to save or retry. Only a verified diagnostic export for the
current startup/discovery status removes this extra decision. It never
qualifies as completed-wipe evidence. See [shutdown protection](report-shutdown.md).
