# Method and storage wording validation

Scope: shared method facts, SSD limits, offline limits help, graphical and console
renderers, result evidence, and safe fake-device regressions. No release authorized.

## Sources

Pinned nwipe v0.42 commit: `6082bde060091e66365d852a1877f2ee80c67105`.
The exact commit's README SSD considerations and `ssd-guide.md` were retrieved
and read. They describe non-host-accessible spare flash, remapped blocks, and
controller restrictions; manufacturer support and validation vary by model.

- README SHA256: `06d89dd903af726974432e89e9ec4e2b901a378b5bbb32cf21f2fc1b73209581`
- SSD guide SHA256: `df3477a7d4d70ae9196c506f3177ad93dbfbd3503aaec7e5b27a12c3e123ec0d`

`methods.py` derives descriptions and pass counts from the selected nwipe
configuration. `storage_limits.py` provides the shared warning and offline help.
Reports record requested operation separately from the evidence outcome.

## Local checks

- `DISPLAY=:0 ./scripts/test-all.sh`: **789 passed**, no skips (44.57 seconds).
  A macOS display permission was necessary; sandbox-only Tk aborted.
  One concurrent-GUI run failed the existing scroll-position test. Three
  isolated repetitions and the subsequent full run passed; the transient
  failure was not treated as a confirmed production defect.
- `python3 -m ruff check src/beamo_wipe tests`: passed.
- `python3 -m mypy --ignore-missing-imports src/beamo_wipe`: passed, 21 source files.
- Compileall, prescribed ShellCheck paths, and both prescribed Ruff security
  selections: passed.
- Ruff formatting check for canonical method/limits modules and the two new
  standalone regression modules: passed. The repository prescribes no formatter.
- Web gallery generation, console EOF smoke, helper preview: passed.
- The exact `run_negative` function from `scripts/ci-hosted.sh`, run locally
  without its Debian dependency installer: expected broken-safety rejection,
  original file restored, clean safety regression passed; exit 0.
- `git diff --check`: passed.

All tests use fake devices and fake lsblk JSON. Engine flags, disk classification,
boot exclusion, device identity, and the destructive confirmation gates retain
their behavior. Type repairs affect annotations, equivalent Tk coordinate
representations, and explicit existing evidence preconditions. Lint repairs
remove unused imports and bindings without removing test assertions.

## Manual and accessibility checks

At 1024x740, the native Tk screen showed all three methods, their overwrite and
read-back counts, the prominent SSD limits, and the Storage limits button without
clipping. The L shortcut opened readable offline help; Esc returned. Quick zero's
Last chance screen retained the disk identity, destructive warning, delay, and
explicit statement that verification is not performed. The native fake run then
reached Finished with disk identity and the explicit no-real-overwrite preview message.

The plain console was walked from method selection through all eight offline
help sections, back to Quick zero, the five-second delay, explicit ERASE input,
and the fake Finished result. The result explicitly said no real overwrite or
verification was performed.

Rendered Tk regressions cover SSD, HDD, and unknown presentation at 1280x820 and
1024x740. Fake JSON classification remains unknown with missing rotational data.
Curses tests verify visible method facts at 80 columns. The web help uses a named,
focusable text region and a described native button.

Limitations: macOS exposed only the Tk window chrome in its accessibility tree,
so native screen-reader compatibility is not established. Actual screen-reader
validation on the shipped Linux image remains required. Browser policy blocked
opening the local gallery file, so browser visual/accessibility validation was
not completed; no workaround was attempted.

## macOS preview runtime

Manual native close aborted Python 3.10.0/Tk 8.6.11 with an Objective-C
autorelease-pool error. Homebrew Python 3.14.7/Tk 9.0.4 passed the same close
operation (exit 0). Homebrew Tk support was installed locally, including the
matching Python patch upgrade. The preview-only launcher now prefers an
installed modern Tk on macOS; its fake-device environment and arguments are
covered by a regression. The canonical `./preview` also closed with exit 0.
The live Linux launcher was not changed.

## Remaining hosted gate

The production manifest preflight exits 2 on this uncommitted patch:
`ERROR: uncommitted source state`. QEMU also rejects a dirty-source manifest.
No dirty-source override or publication was used. The user authorized a local review commit before the hosted gate to resolve
this ordering conflict. Push remains gated on validation, and release requires
separate explicit authorization. Hosted results will be reported against the
immutable review commit and Cloud Build ID.
