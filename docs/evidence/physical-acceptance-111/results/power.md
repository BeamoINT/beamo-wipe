# Power results — PHY-PWR

Policy: [`docs/live-session-power.md`](../../../live-session-power.md). Source receipts: [`docs/evidence/live-session-power-20260910.md`](../../live-session-power-20260910.md) (lid and held power button **Not run**) and [`docs/evidence/laptop-power-20260914.md`](../../laptop-power-20260914.md) (physical acceptance **pending**).

logind is asked to ignore lid and short power press. **Firmware may still sleep or cut power.** Do not claim lid close never sleeps.

Power readings are advisory. They must not start, cancel, or authorize an erase.

Desktop without a battery: Excluded on battery-only rows, still run AC and button rows.

Every Result below is **NOT TESTED**.

| ID | Variant | Expected (physical) | Machine power setup (fill) | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| PHY-PWR-01 | Wall power connected | On-screen reminder can show AC when sysfs reports it; erase path not blocked by a reading | | NOT TESTED | `photos/PHY-PWR-01-*` |
| PHY-PWR-02 | Battery only (charger unplugged) | Warning/reminder still shown; readings unknown stay unknown; **do not** start a long erase on battery if you care about completion | | NOT TESTED | `photos/PHY-PWR-02-*` |
| PHY-PWR-03 | Charge reported at or below 20% | Low-battery warning, including on AC | | NOT TESTED | `photos/PHY-PWR-03-*` |
| PHY-PWR-04 | No battery sysfs (typical desktop) | “No system battery reported” does **not** certify that none exists | | NOT TESTED | `photos/PHY-PWR-04-*` |
| PHY-PWR-05 | Lid close while idle (laptop) | logind should ignore; if the PC still sleeps, record Fail against “firmware obeys logind” and keep the product statement: keep the lid open | | NOT TESTED | `logs/PHY-PWR-05-*` |
| PHY-PWR-06 | Lid close during a non-destructive wizard session | Same as PHY-PWR-05. Do not start an erase to test this unless PHY-DEST is authorized. | | NOT TESTED | `logs/PHY-PWR-06-*` |
| PHY-PWR-07 | Short power-button press | Ignored at logind; use Shut down in the wizard. Firmware may still show its own menu — record it. | | NOT TESTED | `logs/PHY-PWR-07-*` |
| PHY-PWR-08 | Held power button | Firmware may cut power. Unsaved reports are lost. Record duration and what happened. | | NOT TESTED | `logs/PHY-PWR-08-*` |
| PHY-PWR-09 | Idle display blanking vs sleep | Panel may blank after ~10 min; OS sleep should not start from idle policy | | NOT TESTED | `logs/PHY-PWR-09-*` |
| PHY-PWR-10 | Readings never authorize | Change AC/battery while on What/Pick (non-destructive). Disk selection and owner checkbox stay unchanged. | | NOT TESTED | `logs/PHY-PWR-10-*` |
| PHY-PWR-11 | Unknown / stalled reading | After ~10 s without a sample, UI may show unknown; UI stays usable | | NOT TESTED | `logs/PHY-PWR-11-*` |
| PHY-PWR-12 | Pull the cord (lab PC only) | Session stops; no report unless already exported. Do not do this during an authorized erase unless you intend a Fail of completion. | | NOT TESTED | `logs/PHY-PWR-12-*` |

Notes:
