# Notion Details append — #113 (paste this)

**Status: Done.** Acceptance for slow and unusual interaction coverage is met with deterministic fakes. Notion MCP tools were not available in this Grok CLI session; coordinator should paste this block and mark the card Done.

---

Continued with **Grok 4.6 high** via the T3-wired Grok CLI. Jack asked for this on Grok 4.6 high.

### Baseline

- Repo: `beamo-wipe`
- Starting `main`: `4c26217` — `fix: gallery HTML-escape pin matches boot-card serial rendering`
- Branch: `feat/slow-unusual-interactions` (independent from current main)
- Product source: **unchanged**. The gap was missing explicit coverage, not a missing engine.
- Implementation commit: `f78b360e19b3762ffc0d467d28cfacd5253b26b9` — `test: cover slow and unusual interaction scenarios`
- Handoff commit: `62c3f5b017eb6e848a2612dd4f7e42afb9accb8b`
- PR: https://github.com/BeamoINT/beamo-wipe/pull/42
- Implementation: `tests/test_slow_unusual_interactions.py` plus `docs/evidence/slow-unusual-113/`

### What landed

Deterministic fakes and regression tests for the eight interaction contracts:

1. Slow discovery (refresh seq, second-scan refuse, startup stages, Tk loop beats)
2. Delayed progress (old %, silence text, no cancel, 5 s throttle, Tk bar frozen)
3. Long identifiers (wrap, exact confirm token, console 80×24, Tk tail visible)
4. Many disks (boot excluded, overflow list that cannot skip, scroll-into-view)
5. Failed exports (visible failure, one-at-a-time, evidence retries capped at 3)
6. Changed media (auth cleared; identity change refuses erase; lost boot fail-closed)
7. Repeated keys (Enter hold helper; held Enter after help does not skip)
8. Return from help (revoke selection, restore origin, focus on Back, stale ignored)

Native **Tk** and **console** are covered. Gallery remains a static click-through and is asserted **not** to simulate these timings.

### Verification

Fake disks only. Never nwipe. No ISO.

- New suite: **33 passed**
- Related suites: **230 passed**
- Prescribed local gate (`dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest`): **3212 passed, 28 skipped, 1 failed**

The one failure is pre-existing on unmodified `main` 4c26217 in this environment:
`tests/test_kiosk_recovery.py::test_idle_recovery_is_stable_and_signals_never_relaunch[1]`
(extra `stty sane` in a kiosk recovery trace). Outside this card; not a disk-safety regression.

Original-gap probes (`original-regression.txt`): inverting `_is_enter_repeat` starts a fake wipe on extra Enter; stale refresh sequences stay dropped; many-disk fixture has 27 selectable disks.

### Confirmations

- No real-disk nwipe
- No ISO release
- Fail-closed disk-safety language unchanged
- Public wizard/export/progress contracts unchanged
- Notion should be **Done** for #113 (coverage acceptance met)

Coordinator: paste this block into page `3d50a633-535c-81d3-95f6-f5155f5f795f` Details.
