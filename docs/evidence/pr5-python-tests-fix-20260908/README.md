# PR #5: reliable accessible GTK sizing

Validated 2026-09-09 on `codex/cross-platform-20260908`, based on
`068e290ae922aea4d81f29c7625780a33448db24`.
PR: https://github.com/BeamoINT/beamo-wipe/pull/5

The hosted failure in build `db45687a-5824-4c78-bd5b-7bb7bdf03d78`
was reproduced locally: the unchanged low-resolution test observed width 900
immediately after requesting 800. See [original failure](lowres-original-failure.txt).
GTK's pending-event drain can finish before X11's asynchronous configure event.

The wizard now caps its initial 900×700 default to the monitor work area before
showing the window. The fixture waits, with a five-second deadline, for mapping,
the requested dimensions, and the matching GTK allocation. It does not retry the
resize or relax the existing 800×600/footer assertions. New tests cover small and
normal work areas and shrinking an already mapped 900×700 window to 800×600.

Validation:

- Exact requested command: `sudo -n env DEBIAN_FRONTEND=noninteractive ./scripts/ci-hosted.sh tests`
  — **1718 passed, 12 skipped**, exit 0, 81.59 seconds, private 1600×1000 Xvfb
  at 72 DPI on Debian Trixie. [Full gate log](lowres-hosted-tests-final.txt).
- Debian Bookworm chroot, Python 3.11.2 / GTK 3.24.38, full accessible runtime
  suite on private Xvfb display 198: **57 passed**, exit 0.
  [Bookworm runtime log](lowres-bookworm-accessible.txt).
- Four focused sizing cases passed on actual 800×600 Xvfb screens in both
  [Bookworm](lowres-bookworm-800x600.txt) and [Trixie](lowres-trixie-800x600.txt),
  and on [1600×1000 Trixie](lowres-trixie-1600x1000.txt).
- The new startup regression rejects the original source: **1 failed, 1 passed**,
  with `(900, 700) != (800, 600)`. [Regression proof](lowres-regression-old-source.txt).
- [Intermediate attempts](lowres-attempts.txt) record the mirror error, stale
  generated packaging copy, and concurrent accessibility failures. The final
  full gate ran alone after the Bookworm suite ended.

Source SHA-256:

```text
292c81ac005e45890f617c925291fbc4d790a89fef987842b7d8e66c6c7340af  src/beamo_wipe/ui/accessible_wizard.py
c0631609d2809e17c5faa2023ea2c1dcc44efc1430fb0caefc64ee9f5870cbf5  tests/test_accessible_runtime.py
```

The PR's Cloud Build check records hosted status after push; these local results
do not replace it. No main merge, release publication, or real-disk wipe is part
of this fix. Pre-existing evidence files in this directory were left untouched.
