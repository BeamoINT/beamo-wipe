# Same-boot interface recovery

Recovery displays evidence; it never starts, attaches to, signals, or resumes
nwipe. Owner consent, typed confirmation, countdown, progress percentages,
PIDs, runnable requests, and export receipts are never restored. A recovered
session cannot start another erase. Save available evidence before shutdown.

Temporary evidence does **not** survive shutdown or power loss. The systemd
kiosk has `PrivateTmp=yes`: graphical fallback and the supervisor's interface
loop share its private `/tmp`, but stopping/restarting the service can destroy
that namespace even within the same boot. Recovery promises only evidence
still present after an interface crash, not persistence across service teardown.
Nothing is written to the erase target or the boot USB.

## Initialization, ownership and storage

The live entry point claims `interface.lock` before discovery and writes a
preflight journal. Preview/dry-run does not enable production recovery.
`/tmp/beamo-wipe` must already be private (0700) or be newly created that way.
Recovery refuses unsafe existing permissions rather than repairing them. Files
must be regular, owned by the process UID, 0600, single-linked, and opened without
following symlinks. Reads are bounded. Journal I/O uses a pinned directory fd.
Updates use an exclusive random temporary file, full writes, file fsync, atomic
replacement, and directory fsync. The envelope includes a content checksum;
that detects corruption, while ownership and permissions provide the trust
boundary. It does not authenticate files against a privileged attacker.

Schema 1 binds the journal to Linux's current boot UUID, the exact installed
application source digest (including the pinned engine constants), a random
session identifier and a monotonic session start. Unknown/old schemas, a build
change, boot mismatch, duplicate fields, partial or contradictory state, and a
missing journal alongside legacy run artifacts have no automatic migration.
They are rejected. Neither mtime nor wall-clock plausibility establishes trust.

The armed checkpoint is committed after final device validation and before
`runner.start`. It retains disk identities needed for the protected export
baseline, selected target and boot identities, method, log location and kernel
device numbers. Mount paths, confirmation state and progress are omitted.
The existing runner independently repeats its checks and holds `wipe.lock`,
passing that descriptor to nwipe. The child retains ownership if the UI dies.

A restarted interface does not poll the old process. It tries only the existing
wipe lock. While held by another process, the UI says the erase may still be
running and blocks new erasure, export and application-requested shutdown.
Once free, recovery retains that lock through result inspection and export.
Lock errors remain blocked; a free lock is never completion evidence.

## Crash boundaries

| Boundary | Saved state and restart behavior |
| --- | --- |
| Discovery / confirmation / final rediscovery | Preflight; previous result unavailable, no consent restored; constrained diagnostics only |
| Before armed checkpoint finishes | Old preflight remains; runner startup cannot proceed after checkpoint failure |
| After armed checkpoint, before/during runner startup | Indeterminate; no inference that the erase either started or never started |
| Writing / verification | Wait for runner lock; then indeterminate with unknown/null exit, no percentage inference |
| Engine exit / result parsing / final evidence JSON or checksum save | Armed until the complete evidence pair and terminal pointer are committed; orphaned evidence files are not searched for a success |
| Terminal journal replacement | Old armed record or new complete record; success only after independent validation of the visible record |
| After terminal commit | Read pinned evidence bytes and sidecar, validate device/method/build/schema/times/provenance, and independently validate the exact saved log suffix for success |
| USB selection / mount / copying / verification / unmount / receipt delivery | No saved receipt is persisted; recovery requires another explicit, constrained verified export |

A missing, changed, contradictory or unsafe terminal proof yields an
indeterminate result. Recovery does not turn a missing checksum into success.
A valid saved interruption remains an interruption. Unknown exit status remains
JSON `null`; it is not represented as a fabricated signal or exit code.

## Export and privacy

With a validated armed baseline, the Done screen offers an indeterminate report
or the proved terminal report through the existing new-USB-only FAT32 exporter.
The original disk baseline and target/boot kernel identities remain protected;
current discovery does not replace them with whatever happened to be attached
at restart. If context itself is rejected, only the existing Prepare-before-
insertion diagnostic export is offered, with no disk identifiers or raw logs.
If a safe boot/media baseline cannot be established, export remains blocked.

Recovered indeterminate reports include no mutable raw log and explicitly show
unconfirmed completion. The boot UUID, journal session ID and stored journal
are not exported. Recovered local evidence does not count as a saved report:
only exact bytes verified after read-only remount and final unmount can satisfy
the report/shutdown guard. An interrupted export's partial files or completion
marker alone cannot do so. See [report shutdown](report-shutdown.md) and
[Advanced export](ADVANCED.md#logs).

## Validation

`tests/test_session_recovery.py` uses fake inventories and runners, private
ordinary files and a separate fake lock-holder process. It includes abrupt
`os._exit` subprocess crashes at discovery, confirmation, writing, verification,
final evidence save and export; atomic-write faults; missing/changed log and
sidecar; corrupt/foreign/schema-mismatched state; links, modes and owner checks;
concurrent interface/runner ownership; explicit export failure/retry; startup
fallback; unknown exit preservation; and report privacy.

Tk and GTK tests check recovery wording and result actions. The prescribed
local Python gates and hosted lint, fake-device tests, preview, negative safety,
amd64 ISO and isolated QEMU gates still apply. No physical host disks are used
for recovery tests. No release is authorized by these checks.

## Evidence-save failure and retry

The engine's result and evidence persistence are independent. Started evidence
is attempted after engine startup; terminal evidence is attempted once after a
proved stop, exit, or cancellation. There is no periodic progress checkpoint
and no inference of completion from a percentage. A failure to record evidence
leaves the Working screen, progress, cancellation and runner ownership intact.
Tk, GTK and both console views show a separate, nonmodal warning. Engine startup
still fails closed if the earlier armed recovery checkpoint cannot be committed.

After the operation stops, **Retry evidence save** offers at most three explicit
attempts per interface instance (plain console: `RETRY`; menu console: `E`).
Clicks during a save are ignored, rather than queued. Graphical retries run in a
worker; export and application-requested shutdown are blocked until it finishes.
No retry calls the runner, rebuilds a runnable request, rereads mutable logs,
changes a verdict, or refreshes the original inventory. Inputs, interruption
flags and operation timestamps are retained from the first terminal observation.
A changed target, method, discovery, request or result invalidates the retry.

Success requires atomic JSON and checksum publication, private-file readback,
exact equality with the captured report (apart from writer provenance), checksum
verification and, for an original live run, the terminal recovery checkpoint.
Readback failures are no longer suppressed. A final recovery-checkpoint failure
retains the verified local filename; retry revalidates it before finalizing,
without generating another report. Other failed attempts may leave orphaned
private files; they are never searched for a successful outcome or exported.
The retry limit bounds new files. No automated cleanup or evidence-file permission repair runs.

The UI distinguishes unwritable/read-only storage, exhausted space/quota,
invalid evidence, recognized I/O errors, and unconfirmed finalization using fixed
messages. It never displays raw exception text, paths or disk identifiers from
an exception. An I/O error does not promise that a later retry will succeed.
After exhaustion or an invalidated snapshot, keep the session open and contact
support. Unknown evidence remains unconfirmed, even if the engine reported
completion. A saved local report is distinct from a verified USB export.

An indeterminate recovery result is established before its evidence-save attempt.
Failure therefore reaches Done with the same bounded retry controls; timer ticks
do not continually retry writes. Recovery retains a null exit status and empty
log, and cannot change into a successful erase through a save retry. Corrupt or
foreign recovery context still blocks this path. There is no schema migration.
Temporary evidence and retry state do not survive shutdown, power loss, or loss
of the kiosk's private temporary filesystem.
