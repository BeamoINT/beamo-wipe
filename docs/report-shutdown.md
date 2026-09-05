# Requested reports and shutdown

**I want to save a report** records an optional preference. It never chooses
media, saves automatically, creates erase evidence, or authorizes an erase.
The live session's memory and temporary files are lost on shutdown or power
loss. The application cannot stop loss of power or a hardware power button.

When a report was requested and no verified export of the current report has
completed, **Shut down** opens **Shut down without saving?**. **Keep session
open** returns to the previous screen without changing intent or evidence.
**Shut down without saving** explicitly authorizes losing the unsaved report.
Repeated shutdown/window-close events cannot confirm that decision. No report
requested, or a current verified export, means normal one-step shutdown.

In Tk, Enter and Escape keep the session open. Tab focuses either action;
Space activates the focused button. The screen-reader view announces the
question and exposes both actions as native keyboard-accessible buttons,
with Keep first. The plain console requires the exact phrase `SHUT DOWN
WITHOUT SAVING`; anything else returns. In the menu console, Enter/Escape
keep the session open; D opens the same literal-phrase confirmation.
EOF/input loss is never a discard confirmation. Console failure returns to
the supervisor without authorizing poweroff; Ctrl-C cannot confirm discard.

| State | Shutdown behavior |
| --- | --- |
| No report requested | Normal shutdown, except while an operation is busy |
| Requested; no report available, evidence write failed, or export not attempted | Explicit loss decision; no claim that an erase ran or evidence exists |
| Missing, unsupported, removed, partial, or failed report media/export | Explicit loss decision; return and follow the precise export error to retry |
| Export in progress | Wait; no queued poweroff or discard decision |
| Retry succeeds | Normal shutdown after the next explicit shutdown action |
| Exact current report verified after read-only remount and final unmount | Normal shutdown, including after safe removal of that USB |
| Old receipt for a different report | Explicit loss decision |
| Local JSON/checksum, recovered evidence, manual copy or privacy-reduced sharing copy | Does not count as a verified constrained USB export |
| Startup diagnostic exported and verified for the current startup/discovery status | Normal shutdown; diagnostics remain separate from erase evidence |
| Later erase starts or startup status changes | Earlier diagnostic receipt cannot satisfy the new report |

Only the constrained FAT32 exporter can acknowledge saved status: exact report
hash, valid session directory, successful checksum/readback verification, and
final unmount. A screenshot, button history, COMPLETE file alone, or a modified
sharing copy is insufficient. The legacy manual-copy API does not acknowledge
this state. No new sharing-copy exporter is provided. A valid original export
remains saved if the user separately creates a reduced copy for sharing.

For kiosk process/graphical fallback within the same live session, a protected
file under `/tmp/beamo-wipe/` stores only the wanted/not-wanted preference. It
is not a report, receipt, or erase authorization. Restart never resumes erasure
or restores confirmations. Export receipts are held in memory: after process
restart previous export success cannot be confirmed, so requested reports get
a conservative loss decision. Corrupt or unsafe preference files also keep the
warning enabled. A failed preference write is reported in help; memory still
protects the current process, but recovery of the latest choice cannot be
promised if temporary storage fails. This state does not survive shutdown.

Keep report media disconnected during target selection, confirmation, and
wiping. Follow [Advanced](ADVANCED.md#logs) for insertion after the erase stops,
or [Diagnostic report](startup-diagnostics.md) for Prepare-before-insertion.
Returning from the shutdown decision never bypasses final rediscovery,
confirmation, the ownership checkbox, or the five-second delay.
