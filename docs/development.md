# Developing Beamo Wipe

Use a normal development computer and fake devices. The same source checkout
supports development from Windows, macOS and Linux; the Linux live USB remains
the only supported erasure runtime. No development command below erases a disk,
changes firmware, requests administrator access, or restarts the computer.

## Choose your environment

| Host | Python wizard and full checkout tests | Desktop launcher | ISO and complete acceptance |
| --- | --- | --- | --- |
| Linux x86_64 | Native; Tk or browser preview; Xvfb for headless tests | Native tests; Windows/Linux cross-builds | Google Cloud Build; interactive QEMU in an isolated x86_64 Linux VM |
| Linux ARM64 | Native Python development; platform-dependent tests may skip | Native Go tests; Windows/Linux amd64 cross-builds | Remote x86_64 Linux; local ARM emulation is not acceptance |
| macOS Intel or Apple Silicon | Native Python; modern Tk or browser preview | Native Go logic/UI tests; Windows/Linux cross-builds | Remote x86_64 Linux |
| Windows | WSL2 Ubuntu for the Python wizard and full suite; browser preview works without WSLg | Native Go tests and builds; native Python developer-tool tests | Remote x86_64 Linux |
| Other machines | Use a remote Linux development host over SSH | Unqualified locally | Remote x86_64 Linux |

The matrix describes intended development workflows, not certification of every
OS version or CPU. See the dated verification receipt for environments actually
tested. Native Windows Python cannot run the POSIX wizard: file locking, secure
file descriptors, terminal input and Linux device paths are intentional runtime
requirements. `dev.py` routes Python commands through WSL2 rather than weakening
those controls. Native Windows `test --native` tests developer tools only.
GTK/Orca accessibility, Linux mounts, process handling, live boot and firmware
behavior require Linux acceptance. Go tests on macOS do not exercise Windows
firmware APIs. Cross-compilation alone does not prove runtime behavior.

## First setup

Install Git and Python 3.10 or newer with venv/pip support. Use a current Python
with maintained security updates. Windows users can use `py -3` wherever these
examples say `python3`. Go **1.26.8** is needed only for desktop work; build
commands reject a different version and do not download a replacement silently.

Clone either canonical remote into a development directory:

```text
git clone https://github.com/BeamoINT/beamo-wipe.git
cd beamo-wipe
```

Cursor Origin is an equivalent authenticated source:
`https://origin.cursor.com/beamo/beamo-wipe.git`. Pull the same `main` revision
before comparing results on different machines; record `git rev-parse HEAD`.
Do not copy virtual environments or executable caches between operating systems.

On Debian/Ubuntu, install Python and optional graphical test dependencies:

```bash
sudo apt-get update
sudo apt-get install python3 python3-venv python3-tk git xvfb xauth dbus-x11
python3 dev.py setup
python3 dev.py doctor
```

On macOS, install Python with a working Tk. The canonical preview selects a
Tk version at least 8.6.13; older Aqua Tk bundles can crash when closing a
window. If none is available, it falls back to the console. Web mode does not
probe or need Tk. Install a modern Python/Tk before using the graphical tests.

```bash
python3 dev.py setup
python3 dev.py doctor
```

`setup` installs project development dependencies and the CI Ruff/mypy versions
inside `.venv-linux` or `.venv-darwin`. It never installs packages into system
Python. It is safe to rerun after a failed download. Activation is unnecessary:
`dev.py test` selects the host's environment automatically. On macOS the Tk
preview retains the existing modern-Tk interpreter selection.

On Windows, install WSL2 and Ubuntu following Microsoft's WSL setup, then open
Ubuntu and run the Debian/Ubuntu setup above. Prefer cloning inside Ubuntu's
home directory for filesystem performance and normal POSIX permissions.
WSLg provides Tk windows when available. A headless WSL installation can use
`preview --web`, then open the generated HTML in Windows through Explorer's
Linux filesystem view. `BEAMO_WIPE_NO_OPEN=1` prints the path without attempting
to open a browser.

From a Windows checkout in PowerShell, the following delegate to the default
WSL distribution using `wslpath`; paths with spaces remain one argument:

```powershell
py -3 dev.py setup
py -3 dev.py preview --web
py -3 dev.py test
```

Install `python3` and `python3-venv` in that distribution first. Missing WSL,
an uninitialized distribution, or an unconvertible checkout path produces a
nonzero error with instructions. No Windows Python wizard fallback is implied.
For native Windows developer tools and Go work:

```powershell
py -3 dev.py setup --native
py -3 dev.py test --native
py -3 dev.py desktop-test
py -3 dev.py desktop-build
```

The native environment is `.venv-win32`; `setup --native` installs only the
portable tooling test dependency. It does not install the POSIX application.

## Everyday commands

```bash
python3 dev.py preview                 # fake Tk wizard (or console fallback)
python3 dev.py preview --web           # browser click-through, no wipe engine
python3 dev.py preview --console       # keyboard console on POSIX
python3 dev.py preview --scenario empty
python3 dev.py preview --scenario blocked
python3 dev.py preview --scenario fail
python3 dev.py test                    # full existing checkout suite
python3 dev.py test --native           # portable developer-tool tests only
python3 dev.py desktop-test            # native Go unit tests and vet
python3 dev.py desktop-build           # Windows/Linux amd64 executables
```

The legacy `./preview`, `./scripts/test-all.sh`, and
`./scripts/build-desktop.sh` commands remain available. The shell desktop build
and `dev.py` use the same Python implementation, Go pin, flags, executable names,
and manifest schema. `BEAMO_GO_BIN` may select an explicit Go executable.
The generated `dist/desktop/desktop-build.json` identifies source and hashes;
the executables retain the existing embedded dirty-source indicator. A failed
build must not be presented as a successful latest build. Concurrent builds to
the same output are refused. Normal errors and keyboard cancellation release
`dist/desktop/.build.lock`; a force-killed process can leave it behind. Confirm
that no build is still running before manually removing that stale lock and
retrying. Never remove the lock to bypass an active build.

`doctor` reports tools without installing them or enumerating disks. A Tk import
is not a display test. Optional Go/gcloud absence does not prevent browser or
Python work. A missing Git/Python prerequisite or a live erasure environment
returns nonzero. Preview/test commands enforce fake mode and remove inherited
boot-device and native-inventory test overrides. They refuse a live system
instead of clearing its live identity.

Linux `test` uses a separate Xvfb display at 72 DPI when Xvfb and D-Bus are
installed. It does not replace an existing desktop. A local passing suite may
still contain explicit environment-dependent skips; inspect the summary. Full
GTK/speech and packaged-image checks require the dependencies in
`scripts/ci-hosted.sh` and the hosted gate. Do not enable native inventory tests
on a personal development computer. Use only controlled fixtures.

For launcher browser development, run `go run . --preview` inside `desktop/`.
That uses fake readiness and cannot reboot. Test UI behavior in the host browser;
Windows/Linux runtime and firmware tests remain separate. The offline helper is
`helper/index.html`; it provides boot guidance and never erases disks.

## Full build and handoff

From macOS/Linux/WSL with authenticated gcloud, run:

```bash
./scripts/ci-cloud.sh
```

This invokes the canonical `cloudbuild.yaml` in GCP project `beamo-wipe`.
Use a clean, attributed source checkpoint. Run local checks first; the hosted
pipeline adds security lint, Linux/Tk/accessibility tests, negative safety tests,
desktop builds, the amd64 ISO and controlled QEMU verification. Do not call a
skipped ISO/QEMU run full acceptance. Do not attempt local amd64 Docker/QEMU
acceptance on Apple Silicon. Never attach host disks to test VMs.

Build verification does not publish a release. Retaining a developer build for
another machine requires an authorized artifact destination and a receipt with
source commit, build ID, filenames, hashes and access instructions. Download
and verify hashes on the receiving machine. Production release publication,
signing and promotion remain separate authorized steps. Existing developer
artifacts do not automatically update when source changes.

## Troubleshooting and recovery

- Missing Python/venv/pip: install the OS prerequisite, rerun `setup`; do not use
  system-wide pip or copy another host's environment.
- Missing display/Tk: use `preview --web` or `--console`; install Tk/WSLg for GUI
  work. Use isolated Xvfb at 72 DPI for Linux layout tests.
- Test failure: keep the output and exact SHA; reproduce the failing case before
  editing. A skip is not a pass. Native tooling tests are not the full suite.
- Wrong Go version: install the pinned version or point `BEAMO_GO_BIN` at it.
  Do not change the project's Go pin merely to match your machine.
- Permission or cloud login failure: fix that specific prerequisite and rerun;
  never disable safety tests, use real disks, or broaden cloud IAM to get green.
- Interrupted preview/test/build: inspect the process and result before retrying.
  No preview state is evidence of erasure. Preserve unrelated working-tree edits.

## Desktop readiness checks

The desktop launcher reports three separate checks: original USB detection,
startup-settings readability, and a supported restart route. Partial results
retain successful evidence; checks that were not reached remain unverified.
A read failure may mean permission is needed, but does not prove that permission
was denied. The technical disclosure includes the available USB identity,
partition identities, Secure Boot read result and matched startup entry.
These checks never select a disk to erase or guarantee a successful boot.

The existing `ready`, `title`, `detail`, `preview` and `version` JSON fields are
preserved. `checks` and `technical` add explanations to `/api/check`, completed
`/api/state` results and `--check-json`. Restart authorization still uses the
original plan, explicit confirmation and a fresh elevated probe. A browser
retry or failed request clears stale displayed evidence and confirmation.

The offline helper describes these checks but cannot perform them. Build staging
copies `helper/index.html` into START-HERE.html; Go embeds `desktop/web/*` into
both launchers. Tk, console fallback and `./preview --web` run the wipe wizard
after USB startup (or simulate that wizard), so they do not show pre-restart
firmware checks. Their disk exclusion and erase confirmations are unchanged.
The desktop `--preview` uses simulated checks without reading devices.

For browser regressions, install Python `playwright` alongside the development
dependencies and install Chrome or Chromium. Run
`python3 -m pytest tests/test_launcher_readiness.py`; it renders shipped assets
against fake Go snapshots and intercepts all launcher requests. Missing browser
tooling is an explicit skip, not rendered acceptance. The tests inspect the
accessibility tree and keyboard behavior; actual screen-reader speech and
physical Windows/Linux restart acceptance remain separate environment checks.
