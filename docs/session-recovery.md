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
