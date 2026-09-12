# Live-session power receipts — 2026-09-10

Author: accountable senior engineer (this checkout).
Status: source-config and fake-device evidence. No physical lid or firmware
power-button hold was executed on this date.

## What this receipt covers

| Check | Environment | Result | Limit |
| --- | --- | --- | --- |
| logind drop-in keys (lid, idle, sleep keys, short power press) | Source files + pytest | Present as shipped | Does not prove firmware obeys logind |
| `AllowSuspend=no` and related sleep.conf keys | Source files + pytest | Present as shipped | `systemctl suspend` not executed on hardware |
| Masked `suspend.target` / `hibernate.target` / `hybrid-sleep.target` / `sleep.target` / `suspend-then-hibernate.target` | Image hook text + pytest | Hook writes `/dev/null` masks | Mask is image-build time; not a QEMU lid event |
| Xorg `BlankTime` 10, DPMS times 0 | Source `10-beamo.conf` + pytest | Display blanking is configured separately from OS sleep | Blanking interval not timed on a panel |
| Launcher `xset s 600 s blank` and `xset dpms 0 0 0` | Source launcher + pytest | Wake path is requested when `DISPLAY` is set | Not a hardware key-unblank measurement |
| Sleep inhibit argv (`sleep:idle`, not shutdown) | Unit tests with a fake process | Started only on live real-engine start; stopped on lock release | D-Bus/logind not exercised in pytest |
| Wizard shutdown blocked on Working / Checking / Stopping | Existing wizard tests + this policy | Shut down is not offered during erase | Does not block a firmware power cut |
| QEMU squashfs policy grep | `scripts/qemu-verify.sh` when the hosted ISO gate runs | Inspects files in the read-only squashfs | QEMU guests have no lid switch |
| Physical lid close while idle | Not run | No result | Do not claim lid close never sleeps |
| Physical lid close during erase | Not run | No result | Do not claim firmware cannot freeze I/O |
| Held power button during erase | Not run | No result | Firmware may cut power; reports are lost |
| Battery vs AC detection | Not implemented | No result | The UI reminds; it does not read ACPI |

## Isolation

No host disk was passed to QEMU. Local pytest used fake devices only.
This Apple silicon Mac is not the ISO or QEMU gate.

## Honest remainder

Some laptops sleep from embedded-controller firmware even when logind ignores
the lid. That case needs a dated hardware receipt on a named machine. Until
then, the product statement is: this USB asks Linux not to sleep; keep wall
power connected; a power cut stops the erase.
