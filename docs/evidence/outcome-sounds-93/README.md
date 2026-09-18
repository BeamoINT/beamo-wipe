# Backlog #93 — Optional completion and failure sounds

RISK (honest): FR/DE safety wording is first-draft, written
without native-speaker review (same standing risk as #87–#92).
Recommend native review before any release. Audible output
itself cannot be proven on the dev Mac (no live audio); CI/VM
proves process behavior and rendering, not physical speakers.

## Baseline (before implementation)

Source identity: `60d827a` (origin/main) on branch
`feat/improve-screen-hierarchy`, plus uncommitted #87–#92 WIP
(all preserved untouched).

Reproduce: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest`

Result at #92 close: **2 failed, 2753 passed, 527 skipped**
(headless Chrome SIGABRT + sandbox socket denial, both
pre-existing environmental).

Audio baseline (verified by reading the code):

- `src/beamo_wipe/sound.py` (#86) handles sink choice,
  volume, mute, a speech test, and an Orca check:
  allowlisted `pactl`/`spd-say`/`espeak-ng`/`pgrep`,
  live-USB-gated, never raises. It is used only by the
  accessible Sound-check dialog.
- No outcome sounds exist: no WAV assets, no `paplay`
  usage, no `sounds_enabled` setting, no result-screen
  audio hook. Results are visual/text only in every
  renderer.
- PulseAudio starts only on the accessible path
  (`start_live_reader`, `--exit-idle-time=60`); Tk and
  console paths start no audio daemon.
- The live image ships `pulseaudio` + `pulseaudio-utils`
  (which provides `paplay`): no new package is needed.

## Design decisions (recorded before implementation)

- Two earcons: **finished** plays only for the `verified`
  outcome; **attention** plays for every other final
  outcome, including unverified completion, interruption,
  cancellation, and all failure codes. `ResultView.success`
  is True for unverified too, so the mapping keys on the
  outcome code, never on `.success`. Unknown codes map to
  attention (an unknown outcome must never sound like
  success).
- Silent by default: `sounds_enabled` is session memory
  (like `sound_output`), default off. Auto-play fires at
  most once per final outcome (wizard once-marker keyed by
  the evidence key); explicit Hear actions replay on demand
  and work even while sounds are off.
- Silent behavior is defined: muted sink, no sink, no
  `paplay`, or off-live/preview → auto-play stays silent;
  explicit Hear reports the reason instead of playing.
- Auto-play is fire-and-forget (`Popen`, reaped by a daemon
  thread) so it never blocks finalization or the UI;
  explicit tests use `run()` with a timeout for truthful
  feedback. Both lazily ensure the daemon first (covers
  the idle-exited daemon after a long wipe).
- One uniform surface: a sounds on/off toggle plus
  hear/replay actions on Working and Done in Tk, curses
  (`O`/`H` keys), plain console (`SOUNDS`/`HEAR` words),
  and the accessible Sound-check dialog; a shared
  `sound_message` last-status string; gallery renders the
  state without spawning audio; helper intentionally
  unchanged (boot guidance, no outcome surface).

## Acceptance criteria (measurable)

1. `verified` → finished earcon; every other `VIEWS` code
   plus unknown codes → attention earcon; preview → none.
2. Auto-play fires exactly once per final outcome on first
   Done display in each renderer; re-renders never replay;
   explicit Hear/Hear-again replays on demand.
3. No playback from any non-final screen render, and none
   from preview Done.
4. Default off spawns no audio process; muted / no sink /
   no `paplay` / off-live auto-play stays silent, and
   explicit Hear reports the reason without playing.
5. Unverified completion plays attention (pinned).
6. Cancelled + interrupted play attention (pinned).
7. Accessible Done announcement/heading/roles are byte-
   identical with sounds on and off; playback never blocks
   announcement.
8. Both WAVs ship in the live image, are valid mono
   16-bit, each ≤1.5s and ≤100KB, byte-distinct, and
   byte-identical to the committed generator; no new live
   package.
9. Toggle + hear/replay controls exist and work in Tk,
   curses, plain console, and the accessible dialog;
   gallery renders sounds state and spawns no audio.
10. Every new string exists in EN/FR/DE (exact key match);
    German fits (80-column console suite green, Tk
    clipping in CI).
11. Full gates pass apart from pre-existing environmental
    failures; preview/gallery never touch host audio.

## Implementation

- `scripts/make-outcome-sounds.py` (new, stdlib-only,
  deterministic) generates `packaging/sounds/finished.wav`
  (two rising tones, 0.42s, 18KB) and `attention.wav`
  (three beeps, 0.52s, 23KB); both 22050Hz mono 16-bit.
  `scripts/build-iso.sh` stages them to
  `/usr/share/beamo-wipe/sounds/` (missing files fail the
  build); `scripts/qemu-verify.sh` asserts both exist in
  the squashfs. No new live package (`paplay` ships with
  `pulseaudio-utils`).
- `src/beamo_wipe/sound.py`: `kind_for_code()`
  (`verified`→finished, everything else incl. unknown→
  attention), `ensure_audio()`, fire-and-forget
  `play_outcome()` (Popen + daemon-thread reap) and
  blocking `play_test()`, sharing one `_ready()` gate
  (known kind, live USB, output present, unmuted).
  Allowlisted argv only; nothing raises.
- `src/beamo_wipe/wizard.py`: `sounds_enabled` (default
  off), `sound_message` last-status,
  `set/toggle_sounds()`, `maybe_play_outcome_sound()`
  (Done + real + enabled + unplayed evidence key; marks
  before playing; never touches the message),
  `hear_outcome_sound()` (Done replay, works while off,
  preview reports silence), `hear_both_sounds()`
  (finished then attention, first failure wins).
- Renderers: Tk Working/Done footers (toggle + Hear /
  Hear-again + status label, sounds omitted from the
  stop-confirmation screen by design) with a Done
  auto-play hook; curses footers + `O`/`H` keys (free on
  both screens; verified against the full key map) with a
  Done paint hook; plain console `SOUNDS`/`HEAR` words on
  Working (handled before stop-confirm parsing so they
  never dismiss it) and Done + hooks; accessible
  Sound-check dialog toggle + Hear button (applies the
  chosen output first, announces via the status line)
  with a Done render hook. Gallery renders the same
  toggle/hear controls on working/done cards and reports
  the off-live note instead of playing. Helper
  intentionally unchanged (boot guidance, no outcome).
- 16 new copy strings in EN/FR/DE (exact key match;
  first-draft FR/DE); technical `KIND_*`/`SOUNDS_DIR`
  added to the translation-sweep exclusion list with the
  existing binaries/paths precedent.
- `docs/screens.md` (Working + Finished rows) and
  `docs/screen-reader.md` (dialog + coexistence) updated;
  the old "no sound UI outside accessible" claim now
  correctly covers speech only.

## Verification

- New `tests/test_outcome_sounds.py` (23 tests) failed
  before the fix and passes after: exhaustive code
  mapping, unverified/interrupted pins, unknown-kind
  rejection, off-live/muted/missing silence with reasons,
  asset argv + messages, Popen fire-and-forget,
  ensure-audio gating, defaults/toggle validation,
  no-sound-before-final across screens, disabled/preview
  silence, once-per-outcome + new-outcome replay,
  silent-attempt marking, hear-while-off, hear-both order
  + first-failure message, gallery labels without spawn,
  WAV validity/bounds/distinctness + generator
  byte-reproducibility + build-iso staging pin.
- Renderer tests: 2 curses + 2 plain-console tests pass
  locally (80x24 fit asserted); 2 Tk + 2 accessible tests
  added (skip locally — no display/`gi` — run in CI);
  gallery inline JS passes `node --check`.
- Full suite: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest`
  → **2 failed, 2780 passed, 531 skipped** (86s). The 2
  failures are the documented pre-existing environmental
  ones (headless Chrome SIGABRT exit -6, sandbox socket
  `PermissionError`). Two bare `SimpleNamespace` doubles
  needed the new wizard fields (same fix as #91).
- Hosted lint commands pass (ruff check + format on
  gated paths, security-select ruff on `src/beamo_wipe`,
  shellcheck on both edited shell scripts); default ruff
  on new/edited Python shows only pre-existing E402s;
  whole-package mypy shows the same 22 pre-existing
  errors (advisory gate, none on new lines).
- Preview gates pass (`--web` writes
  `web-preview/index.html` containing the sounds UI,
  `--console`, `--helper`).
- Staged chroot copies (ignored build output) re-synced.
- Skipped environments (honest limits): Tk/accessible
  runtime, ISO build, QEMU wipe, Orca voice, and audible
  output on physical speakers need CI
  (`./scripts/ci-cloud.sh`, project `beamo-wipe`) or an
  isolated x86_64 VM — not run here. Audible correctness
  (tone quality, volume) is unproven by construction.
  No commit made (awaiting authorization).
