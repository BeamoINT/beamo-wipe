# Backlog #86 — Accessible audio controls and speech test

## Baseline (before implementation)

Source identity: `60d827a` (origin/main) on branch
`feat/improve-screen-hierarchy`, plus uncommitted #83/#84/#85 WIP
(all preserved untouched).

Reproduce: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest`

Result: **3 failed, 2630 passed, 524 skipped** (92s on the dev Mac).
Same 3 pre-existing environmental failures as before (headless Chrome
SIGABRT, staged-chroot drift at HEAD, sandbox socket denial).

Audio baseline (verified by reading the code):

- The app contains no audio code: no sink/volume/mute handling, no
  speech test, no Orca health check. `start_live_reader()` starts
  PulseAudio and Orca and swallows failures into `log_diag` only, so
  a blind owner gets silence with no recourse.
- Live image ships `pulseaudio`, `speech-dispatcher`,
  `speech-dispatcher-espeak-ng`, `espeak-ng`, `orca`, `procps`, but
  no output-control tool (`pulseaudio-utils`/`pactl` absent).
- `pactl`, `spd-say`, `espeak-ng` are absent on the dev Mac (only
  `pgrep` exists), so audio tests must fake process output; GTK
  runtime tests skip locally and run in CI.

## Acceptance criteria (measurable)

1. No audio: empty/failed sink listing shows "no sound output" plus
   offline recovery instructions, never a traceback or empty dialog.
2. Multiple outputs: two or more sinks list with distinct plain
   labels; choosing one calls `pactl set-default-sink`.
3. Headphones: a headphone sink is labeled "Headphones".
4. Muted/low volume: mute state and percent are shown; unmute and
   louder/quieter actions call `pactl`.
5. Orca failure: a dead/missing Orca is reported with recovery
   instructions; the view stays usable.
6. Keyboard-only: the check is a native dialog (Tab order, Enter
   activates, Esc closes) reachable from a footer utility button.
7. Persisted session choice: the chosen output is recorded on the
   wizard and re-applied; it survives dialog reopens and PulseAudio
   restarts within the session.
8. Offline recovery instructions exist as copy constants, render in
   the dialog, and need no network.
9. Suite results unchanged apart from new coverage and the 3
   pre-existing failures; preview never touches host audio.

## Intentional differences

- The check lives only in the accessible GTK view (the one path that
  speaks). Tk, console, gallery, and helper are unchanged: Tk has no
  speech, console is the no-speech fallback by design, gallery is a
  click-through, helper is boot guidance.
- Choice persistence is session memory (wizard + PulseAudio), not
  crash-recovery disk state: unlike a report, a sound choice is
  trivially re-picked and needs no failure modes.
- Pixel/audio output cannot be proven here: no sound hardware
  assertions on the Mac; CI proves process behavior and rendering,
  not audible sound on physical speakers.

## Implementation

- New `src/beamo_wipe/sound.py` (keyboard.py pattern): allowlisted
  `pactl`/`spd-say`/`espeak-ng`/`pgrep` calls, argv lists, timeouts,
  sink-id validation, volume clamped 0-100. Every call runs only on
  the live USB; off-live everything reports unavailable without
  spawning a process. Speech test uses Orca's chain (`spd-say -w`)
  with `espeak-ng` fallback. Nothing raises.
- `src/beamo_wipe/ui/accessible_wizard.py`: a `Sound check` utility
  button first in the footer grid opens a modal native dialog with
  plain-label output radios (technical name as each choice's
  screen-reader description), volume percent + muted state with a
  low-volume hint, Louder/Quieter/Mute, a Play speech test button,
  an announcing status line, an Orca-missing notice, and always-on
  offline recovery text. Shown with `show()`, never `run()`; Esc
  closes via the `close` signal. Choice applies via
  `set-default-sink` and is recorded on the wizard, re-applied on
  dialog open and before each test (survives PulseAudio restarts).
- `src/beamo_wipe/wizard.py`: `sound_output` session attribute +
  locked `set_sound_output` (memory only, no disk recovery).
- `src/beamo_wipe/copy.py`: sound strings in plain customer
  language; recovery text has no links or device paths.
- `packaging/.../beamo.list.chroot`: added `pulseaudio-utils`
  (pactl provider; not on the forbidden list).
- `docs/screen-reader.md`: Sound check section. Tk, console,
  gallery, helper, and `screens.md` intentionally unchanged (sound
  is not a wizard screen and speech belongs to this path alone).

## Results

- New `tests/test_sound_check.py` (12 tests): all failed before the
  fix (no module/strings/tooling/dialog), all pass after. Two dialog
  runtime tests appended to `tests/test_accessible_runtime.py` (skip
  without GTK/display; run in CI on Xvfb).
- Full suite after: 3 failed, 2642 passed, 524 skipped — the same 3
  pre-existing environmental failures as baseline (+12 passes).
- Blocking lint (`compileall`, ruff security subsets), `ruff
  format` + `ruff check` on new files, mypy on `sound.py` (no new
  errors; one pre-existing dependency error), preview gates
  (`--web`, `--console`, `--helper`): pass.
- Edge probe (`/tmp/beamo86-sound-probe.py`): duplicate labels
  numbered, unknown/failed default sinks, rc failures, timeouts,
  raising live-gate, 100% clamp, sink-id rejection — all structured.
- Source identity: HEAD `60d827a` + #83/#84/#85 WIP (preserved) +
  #86 changes above. Not committed (no commit authorization).

## Skipped environments (honest limits)

- GTK runtime tests skip locally (no `gi`/display); dialog rendering
  proven in CI.
- No manufactured-ISO/QEMU run (Mac TCG; no cloud credentials in
  sandbox) and no audible-output proof on physical hardware. The
  change adds one leaf package and touches no boot, wipe, disk, or
  engine path.
