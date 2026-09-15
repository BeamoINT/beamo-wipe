# Optional authorized destructive results — PHY-DEST

Default: **do not run.** These rows stay **NOT TESTED** until the disk owner authorizes a `DISPOSABLE` target in writing for this session.

Development hosts are forbidden. QEMU `qcow2` wipes are Tier 2 and do not fill these cells ([`docs/qemu-verify.md`](../../../qemu-verify.md)).

A successful overwrite is **not** a certificate that SSD hidden or remapped areas were sanitized ([`docs/storage-and-controller-limits.md`](../../../storage-and-controller-limits.md)).

| ID | Case | Expected (physical) | Target model / serial / bus (fill) | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| PHY-DEST-01 | Everyday method on labeled `DISPOSABLE` disk | Owner box, token, 5 s delay, explicit Erase; boot USB excluded; report export optional; independent inspection afterward | | NOT TESTED | `logs/PHY-DEST-01-*` |
| PHY-DEST-02 | Extra method on labeled `DISPOSABLE` disk | Same gates; different method; do not reuse PHY-DEST-01 as a Pass for Extra | | NOT TESTED | `logs/PHY-DEST-02-*` |
| PHY-DEST-03 | Quick zero on labeled `DISPOSABLE` disk | Same gates; completion says verification was not performed | | NOT TESTED | `logs/PHY-DEST-03-*` |

Authorization record (required before any Pass):

| Field | Value |
| --- | --- |
| Owner name | |
| Authorization date (UTC) | |
| Written authorization stored at | |
| Disk labeled `DISPOSABLE` on the chassis? | yes / no |
| Valuable disks disconnected? | yes / no |

Notes:
