# Guided boot troubleshooting — #59

Recorded **before product edits**. Branch `feat/guided-boot-troubleshooting` off
`origin/main` `4c26217877047abe244bd3ef9266a1ced1db5491`. PR #42
(`feat/slow-unusual-interactions`) is open and unmerged; this work does not
depend on it.

## Baseline (current main, before coding)

- `helper/index.html` is a linear offline page: banner, desktop-launcher
  intro, vendor key table, BitLocker warning, screen-reader key, separate
  Windows 11 and Windows 10 Recovery Environment steps, fallbacks, Secure
  Boot refusal paragraph, kiosk recovery, and “what this USB does”.
- There is **no problem chooser**. A stuck owner has to scan every card.
- `desktop/web/index.html` help is one collapsed `<details>` wall of keys
  and Windows paths. It auto-opens when readiness checks fail.
- Helper contract: single self-contained HTML file, **no `<script>`**, no
  external stylesheet. `scripts/build-iso.sh` copies it to
  `START-HERE.html` and `helper/index.html` on the image.
- Desktop contract: Go embeds `desktop/web/{index.html,app.js,style.css}`
  only. CSP is `default-src 'none'` with `'self'` script/style; `form-action
  'none'`; `img-src 'self'`. Inline SVG in HTML is allowed; extra asset
  files and forms are not.
- Helper tests on this SHA (no product edits):
  `python3 -m pytest tests/test_helper_boot_guidance.py` — **14 passed**.

## Measurable acceptance criteria

1. **Chooser + four branches** on the offline helper and in desktop help:
   USB missing / not detected; ineffective boot-menu key; firmware
   refusal (Secure Boot / legacy as already documented); launcher failure.
2. Each branch is a short numbered recipe in plain language, with a simple
   inline illustration, a link to existing detail (keys, Windows 10/11,
   BitLocker, Secure Boot, kiosk recovery), and technical detail in a
   disclosure — not in the first steps.
3. **Offline:** the guided flow adds no network, no `<script>` on the
   helper, no new external CSS/fonts/images. Optional Microsoft reference
   links stay optional, at the bottom, unchanged in role.
4. **Phone / narrow:** chooser stacks to one column at `max-width: 600px`
   (helper) and `580px` (desktop). At 360×900, `documentElement.scrollWidth
   <= innerWidth`. Illustrations `max-width: 100%`.
5. **Keyboard:** skip link still lands in `main`; chooser is a list of
   links; `:focus-visible` outline on chooser links and summaries;
   branch targets are focusable (`tabindex="-1"`).
6. **Text resize:** new UI uses `em`/`rem`/`%`, wraps, does not use
   `nowrap` or `overflow: hidden` on the guide. 200% browser zoom at 360px
   CSS width must not clip branch titles or steps.
7. **Accurate, non-risky recovery:** BitLocker warning remains before
   firmware-change language. No “disable Secure Boot”, “turn off Secure
   Boot”, “clear CMOS”, “reset BIOS”, or “disable Secure Boot forever”.
   Helper still does not change Secure Boot or extract BitLocker keys.
   First steps are port, Windows Recovery, manufacturer docs — not
   firmware writes.
8. **Scope:** no Apple Silicon, Chromebook, or RAID claims beyond existing
   copy. Intel Mac Option key stays on the helper only. Desktop still
   states it does not run on macOS.
9. **Contracts preserved:** boot USB exclusion, confirm gates, packaging
   copy of helper → `START-HERE.html`, Go embed map, desktop CSP, and
   existing helper tests (Win10/Win11 split, key caps, Microsoft citations).
10. **Intentional differences documented** in this folder: helper is the
    full USB document (incl. kiosk recovery and Intel Mac key); desktop
    help is the same four branches for someone already in the launcher and
    points at `START-HERE.html` for the rest.

## Out of scope / not a pass by themselves

- Physical firmware on a named PC (see #111).
- ISO rebuild / QEMU boot (packaging is the existing `cp` of helper).
- Changing readiness probes, restart authorization, or nwipe flags.
- Notion write from this session (MCP Notion tools are not connected).

## Implementation (after the baseline above)

Offline chooser on `helper/index.html` (no `<script>`, no extra files) and the
same four branches in `desktop/web` help. Supporting browsers show one branch
after a chooser tap (`:has()` / `:target`); print and older browsers keep every
branch visible. Technical detail stays in `<details>`. Firmware steps start
with the BitLocker warning and never tell the owner to disable Secure Boot or
clear CMOS.

Packaging is unchanged: `scripts/build-iso.sh` still copies the helper to
`START-HERE.html`. Go still embeds only `index.html`, `app.js`, and `style.css`.

## Verification

```text
python3 -m pytest tests/test_helper_boot_guidance.py
# 20 passed (includes Chrome 360px dumps of the four branches)

cd desktop && go test -count=1 ./...
# ok

node --check desktop/web/app.js
# ok

BEAMO_WIPE_DRY_RUN=1 dbus-run-session -- xvfb-run -a \
  -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest -q --tb=line
# Full suite reached 100%. One failure:
# tests/test_kiosk_recovery.py::test_idle_recovery_is_stable_and_signals_never_relaunch[1]
# (SIGHUP). packaging/live and that test file are unchanged vs main — not this
# work. Reproduced on a focused re-run. SIGTERM case passed.
```

Shots and layout notes: `LAYOUT.md`. Fake UI only. No nwipe, no ISO, no real
firmware.

## Intentional differences

| Surface | Role |
| --- | --- |
| Helper / START-HERE.html | Canonical offline USB page. Chooser plus full cards, kiosk recovery, Intel Mac Option key. No JS. |
| Desktop launcher help | Same four branches inside the existing `<details>`. No Option key (launcher does not run on macOS). Points at START-HERE.html for kiosk recovery. |

