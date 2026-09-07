# Quality and usability review — September 7, 2026

The review found and corrected interface defects in the desktop launcher and
browser preview, plus outdated platform wording in the live welcome screen and
USB help. This report distinguishes software validation from physical-machine
acceptance; it is not a claim of flawless universal operation or formal accessibility
certification.

Reviewed baseline: `c8cb71506c80b071641d3297d1879c8a495afc6c`.
Interface correction revision: `90bcc69419bf8a81b1a3cbabdd079b4f90151eb3` (including
interface changes in `45b1fcec858502f04d1bc4baa9fbfdbb43fa4748`).
No disk-discovery, target-selection, confirmation-gate, firmware-write, erase-engine,
report-storage, or image-layout logic changed in this review.

## Findings and fixes

| Demonstrated issue | Correction | Verification |
| --- | --- | --- |
| Desktop Close text became white on an almost-white hover background | Keep the hover background dark; use a visible yellow keyboard focus ring | Chromium computed styles: text contrast increased from 1.11:1 to 11.09:1; screenshot inspected |
| Keyboard focus fell onto the document body after an action disabled/removed its button | Focus the result heading or status, never the next action; preserve focus if the user moved elsewhere while waiting | Enter on Restart, Tab to Check again, and Enter on Check again; result focus assertions passed; delayed request preserved focus on Help |
| A failed request retained its previous readiness/checking heading | Show an explicit failure heading, explanation, recovery action and boot help | Injected connection refusal and expired-session HTTP 403; restart hidden, error visible, retry recovered |
| Closing the app removed the interface without focusing its completion message | Focus the closed message and remove the session credential | Close completed with zero buttons, focus on main, and no saved session token |
| Final warning in the browser preview inherited white text from the erase-button CSS | Scope destructive-button styles to buttons | Final warning contrast increased from 1.16:1 to 15.54:1; the real Tk warning already used dark text |
| Storage limits in the browser preview used an unstyled browser-default button | Use the existing help-button style | Method screenshot inspected; action remains available |
| Boot-help table forced horizontal scrolling at narrow widths | Allow explanatory text and the source link to wrap | At 375 pixels the page was 559 pixels wide before the fix; final checks fit at 320, 375, 768, 1024 and 1440 pixels |
| Advisory type check reported two errors in desktop provenance hashing | Reuse the byte-path variable instead of assigning bytes to the text-path variable | Same hash algorithm; local mypy changed from two errors to no issues in 28 source files |
| Welcome and boot help still described only Windows PCs | Describe 64-bit Intel/AMD Windows or Linux PCs; clarify that erasure still requires the live environment | Rendered welcome inspected; shared copy and helper checks passed |

The contrast values are calculated from the rendered foreground/background colors.
They do not establish accessibility conformance for the entire product. No real
screen-reader user or novice user study was performed.

## Review and executed checks

- Read the desktop local-server authorization, readiness planning, native Windows
  and Linux inventory, one-time firmware restart, and rollback paths. Confirmed
  that UI restart does not select a disk or authorize erasure.
- Reviewed the live target-exclusion, fresh identity checks, explicit owner/token/
  countdown claim, nwipe argument binding, process locking, conservative outcomes,
  and report/recovery boundaries against the existing automated checks.
- Reviewed packaging of embedded launcher assets into the FAT32 image and the
  source/checksum checks at staging and readback. Normal BIOS/UEFI boot remains
  part of the final hosted validation.
- Final local Python: **1,404 passed, 138 skipped**, 28.74 seconds. The skips include
  Linux/display-specific tests; they are not counted as passes. JUnit and console
  results were captured. The suite uses fake disks and dry-run isolation.
- Local Go race tests and vet: **PASS**. Bounded EFI parser fuzzing: **578,048
  executions**, 15 seconds, **PASS**. macOS execution does not validate native
  Windows/Linux platform APIs; native Linux and cross-compilation belong to the
  hosted gate, and the previous Windows fixture evidence remains separately dated.
- Browser: **Chromium 152.0.7977.76** against the actual embedded Go launcher in
  `--preview`, which never reads firmware/devices or requests a real restart.
  Readiness, no-op restart, boot-menu fallback, refresh, Close, failed connections,
  expired sessions, disabled controls while busy, and focus preservation passed.
- Launcher viewport widths **320, 375, 768, 1024, 1440 CSS pixels**: no horizontal
  overflow; visible action buttons were at least 57 CSS pixels high. This checks
  browser reflow, not OS display scaling or native accessibility settings.
- Browser gallery: 14 screens at **1024 and 1280 CSS pixels** wide, including
  ownership, target selection, confirmation, methods, last chance, progress,
  completion, blocked/empty states, advanced, limits, report help, and unsaved-report
  shutdown. Headings and horizontal-overflow checks passed; screenshots inspected.
  Scrollable information regions intentionally reveal more text by scrolling.
- JavaScript syntax and `git diff --check`: **PASS**.

## Final hosted gate

Build [8496a9c0-4249-4a34-8ad7-f62c303b1904](https://console.cloud.google.com/cloud-build/builds/8496a9c0-4249-4a34-8ad7-f62c303b1904?project=368895881889)
finished **SUCCESS** at `2026-09-07T03:00:20.634270Z` for clean source
`fd39d5c8ad6246764163593b1d59365cd726d260`. All eight stages passed:
launcher, lint, Python, preview, negative safety, ISO, QEMU, and the disabled
publication step. **1,583 Python tests passed, 12 skipped**. The advisory
mypy check is also clean across 28 source files. Native Linux launcher race/vet tests and 537,670 bounded
firmware-parser fuzz executions passed; both platform launchers compiled.

The rebuilt ISO and FAT32 USB passed BIOS/UEFI ISO boot, BIOS erase and report
export, and BIOS/UEFI/enrolled Secure Boot USB target confirmation. Independent
readback confirmed the disposable target was zeroed; report verification checked
clean FAT, completion metadata, content checksums, read-only inspection, and unmount.
The Secure Boot test requires the guest firmware variable to be enabled; a normal
UEFI boot alone does not satisfy it. Publication was explicitly disabled.

The uploaded archive was independently downloaded and checked: commit `fd39d5c`,
all 155 tracked files checked across source/desktop/helper/scripts/packaging/tests
matched the reviewed checkout, and archive SHA-256 was
`4da974d61e12caf8be7e5eb18c7120188a110044764bb46b4d69b76d25dbe670`. The [validation receipt](evidence/quality-review-20260907.txt)
contains source provenance, build status, stage results, counts, and log excerpts.

The static USB help page was additionally inspected at 375, 1024 and 1440 pixels;
the final wrapping fix passed at all five launcher widths. Its source link is
the project GitHub repository.

## Retained test corrections

One local suite run failed because the ignored live-build staging directory still
contained the old `copy.py`. The staging consistency check correctly rejected it.
The two changed generated Python copies were refreshed using the normal source
inputs; the complete unfiltered local suite then passed. No assertion was weakened. The final type-only change likewise refreshed its
generated staging copy.

Build `9bb7db24-146f-4118-b98a-8f7e93e9f71d` was canceled after the help-page
wrapping defect was found. Build `25c2a3e7-f00a-497d-823d-1d74e9485a7f` was
canceled immediately because its snapshot included uncommitted review artifacts.
Build `d3629b1c-9171-4340-ba0b-1fcda85ae1bb` passed 1,583 Python tests,
launcher race/vet/fuzz, and the negative gate, but was canceled during image
building to include the advisory type-check correction. None of these is counted
as a passing full gate. The evidence files were committed before resubmitting; the source-cleanliness requirement was not bypassed.

Initial gallery automation changed only the URL fragment, which does not reload
this preview's initial-state code. Those captures were not accepted as coverage of
other screens. The final matrix uses fresh document URLs and checks each heading.
An intermediate automation query also used a `main` tag where the gallery has a
div; the final checks use the actual rendered headings. These were harness mistakes,
not product failures. The injected network/403 errors were deliberate negative tests.

## Remaining acceptance limits

The [previous VM report](vm-usb-simulation-2026-09-06.md) retains the writable USB,
NVMe erase/readback, protected-disk hashes, Linux hot-insertion/handoff, keyboard fix,
and infrastructure cleanup evidence for its exact revisions. It is not relabeled
as a new physical USB test or a new native Windows test.

Windows 10/11 Explorer, UAC/SmartScreen and actual firmware handoff; Linux graphical
launch and polkit; physical firmware/USB controllers and trust stores; and novice
usability remain unaccepted. Follow the [hardware checklist](desktop-hardware-acceptance.md)
before a release or compatibility claim. There is no automatic app execution on
USB insertion, Apple Silicon support, or guarantee of SSD hidden-area sanitization.
All erasure still takes place after booting into the protected live environment.

No physical disk was wiped, no physical USB was flashed, and no release was pushed
or published by this review.

## Visual evidence

- [Desktop ready state and keyboard focus](evidence/quality-20260907-desktop-ready.png)
- [Desktop connection failure and recovery](evidence/quality-20260907-desktop-error.png)
- [Corrected final-warning preview](evidence/quality-20260907-live-last.png)
- [Consistent Windows/Linux welcome](evidence/quality-20260907-live-what.png)
- [Boot help at a narrow viewport](evidence/quality-20260907-helper-narrow.png)

## Cleanup

The final build is SUCCESS and all three superseded builds are independently
confirmed CANCELLED. All three local Go previews exited after Close; both static
preview servers were stopped and their ports checked. The dedicated 253 MiB Go
build cache created for this review was removed. No dedicated VM or network was
created in this review; Cloud Build supplied its managed disposable workers.
Both required storage reports completed successfully in read-only mode. No storage
cleanup action was applied; only this review's known disposable Go cache was removed.
