# UI improvement — 8 September 2026

Source baseline: `fcb58ae` (Beamo Wipe 0.2.6). Feature branch:
`codex/ui-improvement-20260908`.

## Changes

- Eight numbered, read-only steps explain where the owner is in the flow.
  The opening screen previews the choice, confirmation, and review sequence.
- Disk rows explicitly label serial numbers. The picker reports the number
  of available disks and whether one is selected; details remain accessible.
- A consistent highlighted selected-disk card appears during confirmation,
  final review, progress, and results. Long names and serials wrap in full.
- Final review places disk identity, the irreversible-action warning, and
  the chosen method beside the countdown. Back retains initial focus.
- Tighter method cards keep the Advanced control fully visible at 1024×740.
  New runtime tests check canvas button bounds, which older label-only
  clipping checks missed.
- A separate progress card groups percentage, phase, elapsed time, estimated
  time remaining, and the chosen method. Cancel remains accessible.
- The GTK screen-reader view uses stronger headings, highlighted identity,
  a visible preview banner, and a separated action area. Native controls,
  accessible names, focus behavior, and announcements are preserved.
- The browser gallery mirrors these layouts, adds an associated token label,
  announces match feedback, and exposes selection state to assistive tools.
  Final review stacks into one column on narrow screens.

Disk discovery, target eligibility, boot exclusion, token validation,
ownership, countdown timing, nwipe arguments, and execution code are unchanged.
No real disk was erased. No ISO or production release was published.

## Verification

Final local command:

```sh
BEAMO_ISOLATED_X11_TEST=1 dbus-run-session -- \
  xvfb-run -a -s '-screen 0 1600x1000x24 -dpi 72' \
  ./scripts/test-all.sh -rs
```

Result: **1681 passed, 12 skipped in 84.48 seconds**. All skips require the
original 0.1.0 manufacturing ISO. The run includes actual Tk and GTK runtime
checks, Orca result announcements, physical X11 keyboard events on an isolated
display, safety regressions, and six new UI regression cases.

Additional checks passed:

- `./preview` real Tk startup smoke on an isolated display; `./preview --web`,
  `./preview --console`, and `./preview --helper` entry points.
- Full browser click-through: ownership gate, no initial disk selection,
  protected boot USB inventory, incorrect/correct token, method, five-second
  countdown, explicit simulated erase, and explicit preview-only result.
- Latest generated browser screens at 1024 px: pick, confirm, method, final
  review, progress, result, empty, and blocked; correct current-step labels,
  no horizontal overflow, and no browser console errors.
- Browser pick, confirm, method, review, progress, and result at 390 px:
  no horizontal overflow; review uses a single column.
- ShellCheck for the repository's hosted shell-script set; generated
  JavaScript syntax; Python compilation; pinned Ruff 0.9.2 blocking security
  rules across source/tests and full Ruff on edited Python files.
- Pinned mypy 2.1.0: no issues in 28 source files.
- Hosted negative-check mutation reproduced in a disposable source copy:
  the broken guard failed its test; the restored guard passed. The working
  checkout's safety code was never mutated.
- `git diff --check`.

## Environment and artifact repairs

Installed the missing Orca and PulseAudio dependencies. One Debian download
returned HTTP 502; its HTTPS download was checked against apt's SHA-256 metadata.
Lint dependencies were installed under `/tmp/beamo-ui-lint`.

The ignored live-image Python staging tree was stale (including a removed
asset and missing source files). Its previous contents were preserved at
`/tmp/beamo-ui-stale-stage-20260908`, then refreshed from tracked source using
the build script's staging rule.

The local file named `beamo-wipe-0.1.0-amd64.iso` did not match the manufacturing
fixture checksum. Its SHA-256 was
`6754b8d4e197887ca5b4d56c67d3fb0d5b08b1241ab15049694cdc4b0bfcf3eb`,
while the test pins
`8a531d35c437d858512ccbba20913cd7dbd9237cc9a2e2a1b7935ba9d9781c55`.
It and its checksum sidecar were preserved under
`dist/quarantine-ui-20260908/`. Tests and checksum expectations were not weakened.
The artifact-dependent tests now report their existing explicit skips.

## Remaining external gate

`./scripts/ci-cloud.sh` was attempted for project `beamo-wipe`. Submission was
rejected because the configured account cannot access the
`beamo-wipe_cloudbuild` bucket. No build was created. Hosted ISO/QEMU validation
remains unverified until an authorized account can submit the feature branch.
No permissions or application safety gates were changed to bypass this blocker.

## Reviewed screenshots

Tk captures use the real renderer and demo disks at 1024×740 and 72 DPI.
The GTK capture is 800×600. The progress capture uses a supplied `ProgressView`
(82%, Verifying) to inspect long elapsed/remaining-time text; it is not a real
wipe or a measured performance result.

- [Opening](splash.png)
- [Disk picker](pick.png)
- [Confirmation](confirm.png)
- [Method — Advanced fully visible](method.png)
- [Final review](last_chance.png)
- [Progress](working.png)
- [Native screen-reader view](screen-reader.png)
