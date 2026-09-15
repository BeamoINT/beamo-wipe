# Port results — PHY-PORT

Plug the **same** manufactured USB into each port. Record whether firmware lists it and whether the wizard still identifies it as the boot USB (not selectable).

Keyboard hubs and docks are degraded or unsupported in product copy ([`docs/boot-card.md`](../../../boot-card.md), [`docs/compatibility-matrix.md`](../../../compatibility-matrix.md) §10). A Fail on a hub is not a Fail of a direct port.

Every Result below is **NOT TESTED**.

| ID | Variant | Expected (physical) | Port location (fill) | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| PHY-PORT-01 | USB-A on the PC (rear or side, direct) | Firmware lists the stick; wizard boots; stick is not a wipe target | | NOT TESTED | `photos/PHY-PORT-01-*` |
| PHY-PORT-02 | USB-A front-panel / header | Same as PHY-PORT-01, or Fail with the port labeled | | NOT TESTED | `photos/PHY-PORT-02-*` |
| PHY-PORT-03 | USB-C native (no adapter) | Same as PHY-PORT-01 | | NOT TESTED | `photos/PHY-PORT-03-*` |
| PHY-PORT-04 | USB-C via A-to-C or C-to-A adapter | Same as PHY-PORT-01; record adapter model | | NOT TESTED | `photos/PHY-PORT-04-*` |
| PHY-PORT-05 | Keyboard / monitor hub | May hide the stick. Try a direct port. Record hub model. Degraded; not an automatic launch path. | | NOT TESTED | `photos/PHY-PORT-05-*` |
| PHY-PORT-06 | USB-C / Thunderbolt dock | Not claimed. Record what firmware does. Excluded unless Jack asked to try this dock. | | NOT TESTED | `photos/PHY-PORT-06-*` |
| PHY-PORT-07 | Repeat PHY-PORT-01 after unplug/replug | Same media identity; restart refused if the stick changed mid-readiness (desktop path) or live session still identifies the USB | | NOT TESTED | `logs/PHY-PORT-07-*` |

Notes:
