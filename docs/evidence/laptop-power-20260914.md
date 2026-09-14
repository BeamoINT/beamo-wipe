# Laptop power guidance — task #57 handoff

Date: 2026-09-14. Author: Codex. Physical acceptance: pending.

The owner authorized committing all current source work and pushing GitHub and
Cursor Origin `main`, with further testing deferred. This does not authorize a
release or establish physical-hardware acceptance.

## Source and integration

The complete local source snapshot was committed as
`1a283d2` on `feat/qemu-three-method-journeys`. Its tree matches the isolated
verification checkpoint `207f7e984658fe1b42822a08b5d91b380b5f90a8`.
Both remote main branches were at `452cfc061ad20a9c44df202201404f3c4130fbb6`
before integration. Newer main changes are preserved: version 0.2.9,
the existing public signing registry, speech boot entries, kiosk recovery,
development workflows and their tests. The resulting source change relative
to that main is the 16-file power-guidance change, plus this receipt.

Tk scrolling retains the existing results screen while adding introduction
and working-screen scrolling. Power readings remain advisory and cannot change
disk selection, authorization, cancellation or erase-engine flags.

## Earlier full verification

The earlier checkpoint passed Cloud Build
`f046bc99-4c9d-4d01-92c3-778fab8942a2` in project `beamo-wipe`:
2,403 tests passed, 15 skipped; lint, launchers, preview, negative safety,
ISO and QEMU gates passed. QEMU executed all three erase methods twice,
verified target overwrite and reports, and checked BIOS/UEFI/Secure Boot.
Publication was disabled. That build predates integration with newer main;
it does not qualify the newly merged source or its newer speech boot paths.

- Source: `207f7e984658fe1b42822a08b5d91b380b5f90a8`
- ISO SHA256: `c364dd11a5f61223b9cd5a943bb7e05548159413b94954e62fc337fb47bd5ab2`
- Manifest SHA256: `422cb6ff265ac9a3628d1075802f789bfddcef3c16ba0d9ea05cdcdcb0f431d9`

Artifacts were ephemeral; do not assume that this ISO is still available.
The first full attempt failed because the isolated clone retained a local
origin URL. Correcting its Git metadata resolved the provenance failure;
the successful retry above retained the same source bytes.

## Merge verification and follow-up

Ruff checks passed for source, tests and developer tooling; developer-tool
format checks passed; mypy passed for 41 source files; compilation and diff
whitespace checks passed. Focused fake-device and native-display checks cover
power readings/layout, existing power policy, busy transitions, helper,
speech boot options, kiosk recovery and developer tooling. An initial run
found one stale ignored helper staging copy (181 passed, 8 skipped); the
generated helper copies were refreshed from current source before rerunning.
The rerun passed 181 tests with 8 platform skips; its sole failure was an
HTTP 403 from an unchanged Microsoft reference URL. A subsequent unchanged
run of all four Microsoft-reference checks passed (4 passed in 2.63s).
No test assertion or link was weakened. All focused cases passed across
these runs, but this is not a claim of one entirely green combined run.

Full ISO/QEMU qualification of the merged revision and dedicated physical
battery/AC, lid, power-button and firmware acceptance remain follow-up work.
Do not mark task #57 physically accepted or Done based on this receipt.
Retain unknown readings and hardware limitations in all product claims.

Local detailed logs, rendered evidence and the 13-case unexecuted physical
acceptance procedure are in `dist/task-57-baseline/`. These generated local
artifacts are intentionally excluded from source commits. No real host disk
was erased or passed through to QEMU.
