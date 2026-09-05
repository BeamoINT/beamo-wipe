# Beamo Wipe — Accessibility & Low-Resolution Verification Matrix

> **Matrix v1.0 — for Beamo Wipe 0.1.1 (nwipe 0.42, commit `6082bde060091e66365d852a1877f2ee80c67105`)**
> Date: 2026-09-02
> Author: Accountable senior engineer (this checkout)
> Status: Published from fake-device evidence + Xvfb 72 DPI + browser inspection. No real disks wiped. ISO/QEMU only on isolated x86_64 with disposable qcow2.

This matrix proves keyboard-only operation, visible focus, contrast, wrapping, warning comprehension, error recovery, progress, and color-independent meaning on the low-resolution and older displays that retiring machines actually have. It does not weaken safety gates. Every destructive path still requires ownership checkbox, type-to-confirm, 5 s countdown, no auto-start, boot exclusion, pinned nwipe.

Current screen-reader behavior and limitations are documented in
[screen-reader operation](screen-reader.md). The matrix below is historical
evidence for its stated commit, not an AT-SPI claim about Tk 8.6.

Related: `docs/compatibility-matrix.md` (boot/hardware), `docs/boot-exclusion-signals.md`, `docs/screens.md`, `docs/claims.md`.

---

## 1. Safety boundary (applies to every row)

- Never run nwipe against a real disk from dev machine. `./preview` and `pytest` use fake `lsblk` JSON (`tests/fixtures/*.json`, `demo_*.json`), `BEAMO_WIPE_DRY_RUN=1`, `DryRunRunner`. `subprocess.Popen` spy asserts `pass_fds` and no real exec.
- ISO/QEMU only on isolated x86_64 with explicitly created disposable `qcow2` (`qemu-img create -f qcow2 /tmp/beamo-wipe-target.qcow2 10G`), no host passthrough, VM torn down after.
- Fail closed on any missing/conflicting/stale/changed boot or target identity, state, or evidence → no selectable targets, `SafetyError`.
- Invariants never relaxed: boot exclusion, exact `/dev/` target binding, ownership acknowledgement, type-to-confirm token (`SAFE_TOKEN_RE`, casefold trimmed), `COUNTDOWN_S=5.0`, no-auto-start, pinned `nwipe` at `/usr/lib/beamo-wipe/nwipe`, logs under `/tmp/beamo-wipe/` never on target.

---

## 2. Environments & scaling

| Env | Identity | DPI / scaling | Use | Isolation |
| --- | --- | --- | --- | --- |
| **Local fake** | `Darwin MacBook-Air-7.local 25.5.0 arm64, Python 3.10.0, pytest 9.0.3` | Tk `tk scaling 1.0` pinned (font pt == px, deterministic) | Parser, state machine, token, safety | Fake lsblk, `BEAMO_WIPE_DRY_RUN=1`, `DryRunRunner` |
| **Xvfb 72 DPI** | `Ubuntu 22.04 x86_64, python3-tk, DejaVu, xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72"` | 72 DPI = live USB default X DPI; 96 DPI VNC (`DISPLAY=:1`) is not the gate | Clipping/off-window probes at `WINDOW 1280x820` and `MIN_WINDOW 1024x740` | `DISPLAY=:99` at 72 DPI |
| **Browser** | `gallery_html()` → `web-preview/index.html` + `helper/index.html` | CSS `px`, `max-width:940`, viewport 360–1920 | Click-through, helper key caps | No wipe code paths |
| **Console fallback** | `curses` or plain `input()` | Mono TTY, wrapping at terminal width | No-X machines | Same `Wizard` state machine |

DPI pinning: `TkWizard.__init__` calls `tk call tk scaling 1.0` so layouts at 72 DPI and 144 DPI render identically. Without this, text at 96 DPI would be ~33% larger than designed and clip.

---

## 3. Typography & contrast

One palette is shared by Tk, gallery, helper and pinned by `tests/test_ui_system.py`.

- **Body type**: `DejaVu Sans` / `Noto Sans` fallback, 34 px bold titles, 18 px lead, 16 px body/button, 14 px meta, 12 px tiny caps. Minimum readable ≥12 px (WCAG large-text threshold). Entry is 26 px bold mono so typed token is readable at 1024 width in bright rooms.
- **WCAG AA**: text pairs ≥4.5:1, white-on-primary/navy/danger ≥4.5:1, non-text UI (focus ring, strong border) ≥3:1 (`test_text_contrast_meets_wcag_aa`, `test_non_text_contrast_meets_wcag_aa`).
- **Key caps**: `Up/Down → ↑ ↓`, `1, 2, or 3 → 1 2 3`, `Enter/Esc/Space/any key` rendered as `_Box`/`span.kbd` with `BORDER_STRONG #74839F` (≥3:1 on `SURFACE`).
- **Color-independent meaning**: every tinted state pairs color with an icon + text. See §7.

---

## 4. Per-state matrix (keyboard, focus, low-res, warnings, recovery)

`Focus` = widget that receives `focus_set()` on entry (safe default = never the destructive action).
`Tab` = logical Tab order (wraps, no trap).
`Visible focus` = focus ring color `FOCUS #1A3FA0` on `BORDER_STRONG` or `PRIMARY` halo.
`Low 1024` = `test_screen_fits_without_clipping[WINDOW|MIN_WINDOW]` → `[]`.
`800×600` = degraded (needs vertical scroll) — documented below, verified not to bypass safety.
`Warning` = panel text always `wraplength=WRAP-110` so it never truncates before the window edge.
`Recovery` = Esc/Back path from this screen.

| # | Screen | Default focus (safe) | Tab order | Visible focus | Keyboard (no mouse) | No trap | 1024×740 fit | 800×600 | Warning / status | Recovery (Esc/Back) | Color-independent meaning |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | **SPLASH** | `Continue` hero pill (primary) | Hero only | FOCUS ring on pill | Any key / Enter / Esc → What | No trap (single focusable) | pass | degraded (centered, hero still visible) | None — tagline wraps `620` | `skip_splash()` via any key | Centered mark + text, not color |
| 1 | **WHAT** | `I understand` (primary right) | `Shut down` (secondary left) → `I understand` → wrap | Both buttons FOCUS ring | `Enter` → Owner; `Esc` → no-op; `Show more` via click only (info panel, not gate) | Tab cycles 2 buttons, `Esc` ignored | pass | degraded (bullets wrap `WRAP-120`, panel `WRAP-110`) | Info panel `Secure Boot hint + nwipe line` with info badge | `Back` not needed (first step) | Bullet amber dots + text, info badge |
| 2 | **OWNER** | Owner checkbox card (takefocus=1, ring) | Card → `Back` → `Continue` → wrap | Card `ring=True` → `FOCUS` outer when focused; checked halo `PRIMARY_TINT` | `Space` toggles card; `Enter` only when `owner_ok`; `Esc` → What | Tab cycles 3, card Space does not trap; held Space guard `arm_done_keyboard` | pass | pass (card `WRAP-140`) | Checkbox unchecked `BORDER_STRONG`, checked `PRIMARY` + halo | `Esc`/`Back` → What | Checked icon + halo + text, not color alone |
| 3 | **PICK** | `Back` when no selection; `Continue` when disk selected | `Back` ↔ `Continue` (2 Buttons) | Both Buttons FOCUS ring; disk rows are not focusable — Up/Down moves selection via root binding | `Up/Down` selects first/last edge or steps; click also; `Enter` only when selectable chosen; boot rows `is_boot` not selectable | Tab 2-cycle, Up/Down never traps (root `<Key>`); pick list overflow scrolls selected into view, scroll position preserved across rebuilds | pass | degraded (list overflows, `_Scrollbar` + `yview` keeps selection visible; footer stays via `pack fill=X side=BOTTOM` last-packed) | `SAME_SIZE_HINT` warn panel when same size, `SSD_FOOTER` info panel when NVMe/SSD selected | `Esc`/`Back` → Owner | Boot row has `⦻` no-entry icon + `DANGER` pill banner; selectable rows have radio; SSD panel has info badge |
| 3e | **PICK_EMPTY** | `Shut down` (primary) | `Back` → `Shut down` | Both ring | `Enter`/`Space` on Done gated by `arm_done_keyboard` (ignored until release) | Held Enter/Space must not shutdown before key up (`_return_held`/`_space_held`) | pass | pass (centered `_icon_badge`) | `EMPTY_DISKS` centered, `info` halo | `Esc`/`Back` → Owner; `Enter` → shutdown only after armed | `info` halo badge + muted text |
| 3b | **PICK_BLOCKED** | `Shut down` (primary) | `Back` → `Shut down` | Both ring | Same gated shutdown as empty | Same held-key guard | pass | pass | `IDENTIFY_ERROR` warn halo | `Esc`/`Back` → Owner | `warn` halo triangle |
| 4 | **CONFIRM** | Entry ( `_confirm_var` ), shell `ring=True` | `Entry` → `Back` → `Continue` (when enabled) | Entry shell ring via `set_focused(True)` → `FOCUS`; pill match icon updates | Type token; `Enter` only when `token_ok`; mismatch blocks | Tab 3-cycle; `Continue` `takefocus=0` while disabled so Tab skips disabled primary (focus stays on Entry/Back, not lost) | pass | pass (entry `fill=X`, match pill `PILL` hugged via `fit_now`) | Warning `confirm_warning()` warn panel (`WARN_BG`) + match pill: waiting `MUTED` + open circle vs ok `OK_TINT` + green check | `Esc`/`Back` → Pick (clears not token) | Match state: waiting open circle + text vs ok green pill + check icon |
| 5 | **METHOD** | `Continue` (primary right) | `Advanced (ghost)` → `Back` → `Continue`; cards are not Tab-focusable, selection via `1/2/3` or `Up/Down` | Footer buttons ring; selected card `halo` + `PRIMARY` border; hover `SURFACE_ALT` | `1/2/3` selects Everyday/Extra/Quick zero; `Up/Down` cycles order; `Enter` → Last chance | Tab cycles 3 buttons, card Up/Down never traps; `compact` title block keeps height inside 740 | pass | pass (compact margins `top 10/bot 6`, center_zone) | Each card `blurb` + `pace` with clock icon; footer hint `1, 2, or 3` as key caps | `Esc`/`Back` → Confirm; `Advanced` → Advanced | Radio selected vs unselected + Recommended chip, not color alone |
| 5a | **ADVANCED** | `Continue` | `Back` → `Continue` | Both ring | Any key `Back`/`Enter` → Method; no selection | Tab 2-cycle | pass | pass | `ADVANCED_LEAD` info, `package` lines mono wrapped `WRAP-60`, log path shown | `Esc`/`Back` or `Continue` → Method | Mono list with separators, log label muted |
| 6 | **LAST_CHANCE** | `Back` (safe, never Erase) | `Back` ↔ `Erase now` | Both ring; countdown ring draws `PRIMARY` vs `OK` + `✓` | `Enter` ignored while `countdown_left>0`; after 5 s `Enter`/`Space` on Erase triggers `confirm_erase`; `Esc`→Method | Held Enter from Method must not fire Erase when countdown completes (`_return_held`) | pass (ring `RING_SIZE 190`, bottom `SHADOW_H` reserved) | pass (ring centered in `center_zone`) | `erase_now_label` danger panel; countdown number `56 px bold` + caption; error panel if `w.error` | `Esc`/`Back` → Method (clears `_erase_until`) | Countdown: number + caption + arc color vs ready `OK` + ✓ |
| 7 | **WORKING** | No focusable (intentional) | No Tab stop — screen is non-interactive; `_close` ignores `WM_DELETE` while working non-preview | N/A | No keyboard action | No trap — `WM_DELETE_WINDOW` blocked during non-preview working so accidental close cannot interrupt wipe | pass (`bigstat 56px`, bar 14px, `_paint_bar` rounds) | pass (disk summary identical to confirm) | Disk summary + method title + pulse `Leave the USB in…` ; progress text via `format_progress_percent` (never 100% before 100.0) + indeterminate slide | No Back; `cancel_wipe` only via signal/interrupt evidence | Progress: percent text + bar fill + indeterminate segment, not color alone; `format_progress_percent(99.5)==99%` |
| 8a | **DONE OK** | `Shut down` or `Run again` (primary) | Preview: `Close preview` → `Run again`; Live: `Shut down` only | Both ring | `Enter`/`Space` gated by `arm_done_keyboard`; preview `Run again` resets wizard | Held Enter/Space from Working must not shutdown before release | pass | pass (icon `96`, heading centered `wraplength 700`) | `DONE_OK` / `DONE_OK_PREVIEW` centered; disk summary + Show more | `Esc` ignored (terminal) | Status `OK` green halo + ✓ + ink message |
| 8b | **DONE FAIL** | `Shut down` / `Run again` | Same as OK | Same | Same gated | Same guard (`test_held_enter_does_not_shutdown_failed_done`) | pass | pass | `DONE_FAIL` never contains "secure"; `log_text` shown; failure icon `danger` halo + ✕ | Same | `danger` halo + ✕ + ink message, not color alone |
| — | **Gallery (web)** | N/A | Tab cycles: scenario buttons → header not focused → disk cards `tabindex=0` when pickable → entry → footer buttons; all have `:focus-visible 3px solid #1A3FA0` | Buttons `.card.pickable:focus-visible`, `.scenarios button:focus-visible`, `button.btn:focus-visible`, `.ownercard:focus-visible`, `.entryshell:focus-within` | Click / Space / Enter on disk/method cards; owner card Space; confirm input Enter | No trap — `renderHint` key caps are not focusable; `location.hash` deep links preserve state without reload trap | Responsive `max-width 940`, `disklist overflow-y:auto`, `kbd` caps `BORDER` | 360px: cards stack, `disklist` scrolls, `brandchip` not tiled | `panel warn/danger/info` with inline SVG badge + text | `Esc` not needed (browser Back); scenario buttons reset state cleanly | Every panel pairs `badge()` SVG with text; status icons `status ok/bad` pair core color with ✓/✕ |
| — | **Helper (boot menu)** | N/A | Links `a:focus-visible` | `a:focus-visible 3px solid #1A3FA0` | Tab through links, key-cap table | No trap | `max-width 920`, table collapses via `overflow` not clip; `kbd` caps `BORDER` | 360px: table `width 100%` wraps, `kbd` stays readable | Banner `danger-tint` + triangle + text, always `This page does not erase` | N/A | Banner pairs triangle icon with text |

---

## 5. Low-resolution & scaling proof

| ID | Resolution | DPI / scaling | Hardware class | Expected rendering | Automated proof | Result |
|---|---|---|---|---|---|---|
| **DISP-01** | **1024×740** (minimum) | 72 DPI pinned | Old laptop LCD, Intel iGPU live X modesetting | All screens fit, no clipping, footer visible, pick list scrolls when overflow | `test_screen_fits_without_clipping[MIN_WINDOW]` at `MIN_WINDOW (1024,740)` → `[]` clipping + `[]` off-window; `test_status_screens_fit[MIN_WINDOW]` | **Supported** |
| **DISP-02** | **1280×820** (default) | 72 DPI | 13" laptop | Same with breathing room | `test_screen_fits_without_clipping[WINDOW]` | **Supported** |
| **DISP-03** | **1366×768** | 72 DPI | Common 720p laptop | Width >1024 so `CONTENT_W 940` fits via `fill=X`; inferred from bounds | Manual `./preview` resize check + `CONTENT_W 940` ≤ 1366 | **Supported** |
| **DISP-04** | **1920×1080** | 72 DPI | External FHD | Centered `CONTENT_W 940`, `center_zone` vertical centering, no stretch | Gallery `max-width:940`, Tk `CONTENT_W` | **Supported** |
| **DISP-05** | **800×600** | 72 DPI | Very old 4:3 / VM fallback `vga=788` | **Degraded:** content renders but requires vertical scroll or pick-list scroll; primary stays reachable via Tab, safety gates intact, no bypass | `test_small_window_never_bypasses_safety` (logic-level) + `test_pick_list_scrolls_selected_card_into_view[MIN_WINDOW]` overflow path | **Degraded (safe)** |
| **DISP-06** | **1024×600** | 72 DPI | Netbook (e.g. 10" 1024×600) | **Degraded:** height 600 < 740, vertical centering compresses but footer still packed last (`side=BOTTOM` packing order guarantees action buttons are last clipped) | Pack order comment in `_build_chrome` + footer shell test | **Degraded (safe)** |
| **DISP-07** | **HiDPI 200% (2560×1440 @2×)** | 144 DPI logical | Modern laptop | Without pinning would clip at `WRAP`; pinned `tk scaling 1.0` keeps layout identical to 72 DPI | `test_tk_scaling_is_pinned_to_one` (structural) + `Wraplength` checks | **Supported via pinning** |
| **DISP-08** | **800×600 @ 96 DPI VNC** | 96 DPI (`DISPLAY=:1`) | VNC desktop | **Not the gate** — VNC 96 DPI would enlarge ~33% vs live USB and clip. Gate uses `DISPLAY=:99` 72 DPI. | `docs/ci.md` gate definition | **Not claimed** |
| **DISP-09** | **Browser 360×640** | CSS px | Phone-preview of gallery/helper | Cards stack, `disklist` `overflow-y:auto` with 12px thumb, `wraplength` not needed; `kbd` caps still 12px bold | `test_browser_cards_have_tabindex_and_focus_visible` + manual resize | **Supported (degraded width)** |
| **DISP-10** | **Browser 1920×1080** | 1× | Desktop | `max-width 940` centered, gallery `page max-width 1100` | Same | **Supported** |
| **DISP-11** | **Console 80×24** | Mono | No-X fallback | `curses` wraps at `w-2`, `plain_loop` prints serial+path+`SAME_SIZE_HINT` | `test_curses_pick_shows_serial_and_same_size_hint` | **Supported** |

Pinning rationale: `TkWizard` sets `tk scaling 1.0` so point sizes are pixel-equivalent on every X DPI. Tests at 72 DPI therefore model the live USB exactly; a 96 DPI VNC inspection that shows clipping is expected and not the gate.

---

## 6. Full keyboard-only traversal proof

All sequences use fake disks (`make_demo_wizard(scenario=happy)`, `DryRunRunner`), no mouse, no real nwipe.

| Flow | Key sequence | Gate asserted | Test |
|---|---|---|---|
| Splash→Done happy | Any key, `Return` (What→Owner), `Space` (Owner check), `Return` (Owner→Pick), `Down` (pick), `Return` (Pick→Confirm), type token, `Return` (Confirm→Method), `2` or `Down` (Extra), `Return` (Method→Last), wait 5s, `Return` (Erase→Working→Done) | All gates in order | `test_keyboard_only_flow_reaches_working` + `test_happy_path_dry_run` |
| Owner blocked | `Return` from What without Space → stays Owner | `continue_owner` checks `owner_ok` | `test_happy_path_dry_run` (first `continue_owner` fails) |
| Pick without selection | `Return` with `selected is None` → stays Pick | `continue_pick` checks `selected` | Same |
| Confirm without token | `Return` while `token_ok False` → stays Confirm | `continue_confirm` checks `token_ok` | `test_preview` + `test_confirm_token` |
| Last chance countdown | `Return` during `countdown_left>0` → stays Last | `erase_enabled == countdown_left<=0` | `test_keyboard_only_flow_reaches_working` (countdown guard) + `test_held_enter_does_not_erase_when_countdown_completes` |
| Held Enter across screens | Hold `Return` Method→Last, keep held while countdown expires — must not auto-Erase; only after release + fresh press | `_return_held` guard | `test_held_enter_does_not_erase_when_countdown_completes`, `test_held_enter_does_not_skip_method_after_confirm`, `test_held_enter_does_not_shutdown_pick_empty/failed_done`, `test_held_space_does_not_shutdown_*` |
| Tab order | Tab cycles between the two footer buttons (and owner card / entry when present) without losing focus | `takefocus=1` only on enabled buttons; disabled `Continue` on Confirm has `takefocus=0` so focus stays reachable | `test_every_screen_has_a_focusable_action`, `test_browser_cards_have_tabindex_and_focus_visible` |
| Esc → Back | `Esc` on Owner/Pick/Confirm/Method/Last/Advanced → previous screen; on Splash → What; on What/Working/Done no-op | `back()` mapping clears `_erase_until` when leaving Last | `test_escape_goes_back`, `test_back_from_last_chance_redraws_method_state`, `test_open_advanced_twice_does_not_trap_on_advanced` |
| Method cycle | `Up/Down` cycles Everyday→Extra→Quick zero; `1/2/3` direct selects | `_on_key` handles both char and keysym | `test_method_keyboard_up_down_cycles` (new) |
| Console Pick | `Up/Down` then Enter on curses; `input("0")` rejected | `SAME_SIZE_HINT` printed, boot marked `is_boot` dimmed | `tests/test_console_pick.py` (9 tests) |
| Recovery | Done `Enter`/`Space` only after `arm_done_keyboard()` (key release). `reset_for_preview` clears `_wipe_request` args. `cancel_wipe` → interrupted evidence. | `arm_done_keyboard` + `_space_held`/`_return_held` | `test_pick_empty_keyboard_ignored_until_armed`, `test_pick_blocked_*`, `test_done_keyboard_ignored_until_armed`, `test_reset_for_preview_clears_selection` |

No shortcut bypasses ownership or token. `confirm_erase` re-discovers and calls `assert_ready_to_wipe(owner_ok, token, countdown)` + `assert_disk_identity` + `assert_boot_excluded` again before `runner.start`.

---

## 7. Contrast & color-independent meaning

| Meaning | Color only? | What the screen actually shows | Verification |
|---|---|---|---|
| Primary action | No | Filled `PRIMARY #1D4ED8` pill + white label **and** focused ring on Tab **and** centered footer hint `Enter continues. Esc goes back.` with key caps | `_Button._VARIANTS primary` + `_Button._draw` focus ring |
| Danger (Erase) | No | `DANGER #B3261E` + label `Erase now` + countdown number + label | `_last` danger variant |
| Disabled Continue | No | `DISABLED_BG #E4E8EF` + `DISABLED_FG` **and** `takefocus=0` so Tab skips it **and** match pill shows waiting text | `_Button.set_enabled` + `_confirm_var_written` |
| Owner checked | No | `PRIMARY_TINT` + `PRIMARY` ring + halo + check icon + unchecked `BORDER_STRONG` outline | `_owner` card styles |
| Disk selected | No | `PRIMARY_TINT` + `PRIMARY` ring + halo + radio dot | `_disk_row`, `_pick` |
| Boot USB | No | `USB_BG` + `USB_BORDER` + `⦻` no-entry icon + `This is the Beamo USB — do not erase` pill `DANGER_TINT` | `BOOT_USB_BANNER` + `_icon_no_entry` |
| Warning panel | No | `WARN_BG #FBF1D5` + `WARN_BORDER` + filled triangle glyph + text | `_panel kind warn` + `_draw_alert_glyph` |
| Danger panel | No | `DANGER_TINT` + `DANGER_BORDER` + triangle + text | Same `danger` |
| Info panel | No | `SURFACE_ALT` + `BORDER` + filled circle-i glyph + text | Same `info` |
| Match waiting | No | `SURFACE_ALT` + open circle outline + text `Type it exactly…` | `_paint_match` |
| Match OK | No | `OK_TINT` + `OK` border + green check circle + text `That matches…` | Same |
| Status blocked | No | `warn` halo (88px) + triangle + title `Stop` + `IDENTIFY_ERROR` text | `_status_screen warn` |
| Status empty | No | `info` halo + circle-i + `No disk to erase` | Same `info` |
| Status done OK | No | `OK_TINT` halo + green disk + ✓ + `Finished` | `_icon_status ok` |
| Status done FAIL | No | `DANGER_TINT` halo + red disk + ✕ + `The erase did not finish` (never "secure") | Same `not ok` |
| Working progress | No | `TRACK #DFE5EF` + `PRIMARY` fill **and** percent text `format_progress_percent` + pulse text | `_paint_bar`, `_refresh_working` |

---

## 8. Truncation, wrapping, readable type

| Risk | How the screen avoids silent truncation | Automated check |
|---|---|---|
| Long disk name | Title label at low-res still wraps via `WRAP-110` (panel text) / title row packs `size_phrase` right, name left trunc not clipped because `test_screen_fits_without_clipping` asserts `winfo_reqwidth <= winfo_width+2` | `test_screen_fits_without_clipping` |
| Long serial | Serial rendered `font_mono_bold 14` via `_meta_line`; serial first element, then optional `· bus · /dev/sda` only when `Show more`; raw serial `wraplength` not needed as mono single token, but card width `WRAP` guarantees it fits at 940 | `_meta_line` + `_disk_summary` + gallery `metaLine` |
| Missing serial | Falls back to `"no serial"` (`NO_CODE`) so UI never shows blank; confirm token falls back to device name via `SAFE_TOKEN_RE` | `test_plain_console_zero…`, `test_empty_serial…` |
| Partition / log path in Advanced | Advanced rows `wraplength=WRAP-60` so long `nwipe --method=` lines wrap inside hero card | `_advanced` |
| Owner checkbox text | `wraplength=WRAP-140` inside owned card, fitted with `fit_now` avoidance of transient geometry | `_owner` |
| What bullets | Each bullet row `marker Canvas 10×26` + label `wraplength=WRAP-120` inside hero card with shadow | `_what` |
| Warning panels | Panel label `wraplength=WRAP-110` with left icon, halved at 800 width still fits | `_panel` |
| Confirm token prompt | `spec.prompt` label `WRAP` then entry `font_entry 26px mono` fill `X` | `_confirm` |
| Boot helper table | Helper `table width 100%` `th` 12px uppercase, `td` 20px, `kbd` 14px bold — wraps at 360px CSS without horizontal scroll | `helper/index.html` inspection + `test_helper_page_renders_boot_keys_as_key_caps` |
| Gallery at 360px | `body 20px`, `disklist overflow-y:auto`, `max-width 940` container, `kbd` caps remain readable | Browser test |

---

## 9. Browser & helper matrix (click-through)

| State | Keyboard on gallery | Focus visible | Low width 360px | Warning text |
|---|---|---|---|---|
| Splash | `#herogo` button Enter | `button.btn:focus-visible` | Wordmark wraps, hero `min-width 240` still inside | Tagline muted |
| What | `Show more` `linkbtn` Tab, scenic buttons | `linkbtn:focus-visible` | Bullets `20px` wrap | `panel info` |
| Owner | `#own` `tabindex=0 role=checkbox` Space toggle | `.ownercard:focus-visible` | Card stacks | `HINT_OWNER` |
| Pick | `.card.pickable tabindex=0 role=button` Space/Enter | `.card.pickable:focus-visible halo` | `disklist` scrolls | Same-size warn panel |
| Confirm | `#tok` Entry auto-focus | `.entryshell:focus-within` | Entry `26px` fits | `panel warn` + match pill |
| Method | Cards `tabindex=0` Space/Enter + `1 2 3` | Same card focus | Cards stack | Pace with clock icon |
| Advanced | Buttons Tab | footer focus | Mono rows wrap `advrow` | Log note |
| Last | `Erase` disabled until `tLeft<=0` | danger focus ring | Ring `190px` centered | `panel danger` erase label |
| Working | Indeterminate `.fill.indet` slide | N/A | Bar `height 14` | Pulse text |
| Done | `Run again` / `Close` | Both focus | Status `96px` centered | `statustext` |

Automated: `test_gallery_uses_the_same_color_tokens`, `test_browser_cards_have_tabindex_and_focus_visible` (new), `test_helper_page_focus_visible` (new), `test_helper_page_renders_boot_keys_as_key_caps`.

---

## 10. Console fallback

| Screen | Rendering | Keyboard | Focus/selection indication |
|---|---|---|---|
| PICK | `listed_disks` sorted with boot dimmed `A_DIM`, selected `A_REVERSE` `>` | `Up/Down` then Enter | `>` + reverse attr |
| CONFIRM | `getch` loop, echo, `backspace` handling, `Enter` only when `token_ok` then `enter_held=True` | Type token chars, Backspace, Esc | `>` prompt + `token_ok` gate |
| METHOD | `1/2/3` mapping | Digits only (curses path also has no Tab) | `>` prefix on selected |
| LAST | `Wait Xs` countdown | `Enter` only when `countdown_left<=0` | Text countdown |
| WORKING | `format_progress_percent` or `—` | No input | `WORKING_PULSE` + percent |
| DONE/EMPTY/BLOCKED | `arm_done_keyboard` after `-1` idle gap | Enter only after armed | `Enter: shut down` hint |

Covered by `tests/test_console_pick.py` (9 tests) + `test_wizard_flow.py`.

---

## 11. Automation coverage map (which tests prove which row)

| Verification | Test(s) / spy |
|---|---|
| Contrast ≥4.5:1 text, ≥3:1 non-text | `test_ui_system.test_text_contrast_meets_wcag_aa`, `test_non_text_contrast_meets_wcag_aa` + token list `SHARED_TOKENS` vs gallery/helper |
| Shared palette | `test_gallery_uses_the_same_color_tokens`, `test_helper_page_uses_the_same_color_tokens` |
| Key caps render as caps | `test_every_hint_key_name_renders_as_a_key_cap` (`_KEY_TOKEN_RE` + `KEY_TOKEN_KEYS`) |
| 1024×740 fit | `test_tk_runtime.test_screen_fits_without_clipping[MIN_WINDOW]`, `test_status_screens_fit[MIN_WINDOW]`, `test_done_screen_fits` |
| 1280×820 fit | Same with `WINDOW` |
| Focusable action on every screen | `test_tk_runtime.test_every_screen_has_a_focusable_action` + new `test_accessibility_lowres.test_every_screen_has_focusable_and_no_trap` |
| Keyboard-only full path | `test_tk_runtime.test_keyboard_only_flow_reaches_working`, `test_wizard_flow.test_happy_path_dry_run` |
| Held-key guards | `test_held_enter_does_not_erase_when_countdown_completes`, `test_held_enter_does_not_skip_method_after_confirm`, `test_held_enter_does_not_shutdown_pick_empty/failed_done`, `test_held_space_does_not_shutdown_*` |
| Focus visible rings | `test_ui_system.test_button_variants_and_keyboard_activation` (`<FocusIn>`/`<FocusOut>` + `takefocus=1`) + new `test_accessibility_lowres.test_visible_focus_rings_on_all_screens` |
| Tab order logical | New `test_tab_order_is_logical_and_traps_free` — inspects `takefocus` order vs expected `Back→Primary` + owner card before footer |
| Safe default focus | New `test_safe_default_focus_on_every_screen` — asserts `focus_get()` after `_draw` is never Erase, is Back or Card or Entry |
| Method Up/Down | New `test_method_keyboard_up_down_cycles` + structural `test_method_supports_up_down` |
| Wrapping not clipped | `test_screen_fits_without_clipping` clipping probe + new `test_long_strings_do_not_clip_at_min_window` with 64-char serial + 40-char model |
| Warning comprehension | New `test_warning_and_error_text_are_wrapped_and_never_truncated` — asserts `wraplength` on every `tk.Label` created for warnings is ≤ WRAP |
| Progress color-independent | `test_wizard_flow.test_format_progress_percent_does_not_round_up_to_one_hundred`, `test_working_uis_never_round_percent_with_point_zero_f`, new `test_progress_bar_has_text_and_bar_and_indeterminate` |
| Browser keyboard + focus-visible | New `test_browser_cards_have_tabindex_and_focus_visible`, `test_gallery_mirrors_wizard_components`, `test_browser_disk_selection_via_keyboard` |
| Helper focus-visible + key caps at 360px | `test_ui_system.test_helper_page_renders_boot_keys_as_key_caps` + new `test_helper_page_focus_visible` |
| Error recovery (blocked/empty/fail/advanced/last back) | `test_wizard_flow.test_back_from_last_chance_redraws_method_state`, `test_open_advanced_twice_does_not_trap_on_advanced`, `test_empty_and_blocked_scenarios`, `test_pick_empty_keyboard_ignored_until_armed`, `test_console_pick` |
| Safety gates still closed on trap/aria misuse | `test_tk_enter_is_always_the_gated_screen_action` (Enter is global, Button Space-only), new `test_accessibility_shortcuts_cannot_bypass_gates` — fires focus/Tab/Shift-Tab/Space on random controls and asserts `runner.started False` |
| Destructive spies | `DryRunRunner` vs `NwipeRunner` in `test_confirm_erase_refuses_real_runner_in_dry_run`, `subprocess.Popen` spy in `test_nwipe_runner` |

---

## 12. Reproducible steps

```bash
# from repo root, no real disks
BEAMO_WIPE_DRY_RUN=1 python3 -m pytest -k "not tk_runtime"
BEAMO_WIPE_DRY_RUN=1 python3 -m pytest tests/test_accessibility_lowres.py -v  # new
BEAMO_WIPE_DRY_RUN=1 python3 -m pytest tests/test_ui_system.py tests/test_preview.py -v
BEAMO_WIPE_NO_OPEN=1 ./preview --web && ls web-preview/index.html
BEAMO_WIPE_NO_OPEN=1 ./preview --web && python3 -c "import pathlib; print(pathlib.Path('web-preview/index.html').read_text()[:200])"
python3 -c "from beamo_wipe.gallery import gallery_html; print('gallery', len(gallery_html()))"
python3 -c "from beamo_wipe.ui.tk_wizard import TkWizard; import inspect; print('scaling' in inspect.getsource(TkWizard.__init__))"

# Tk clipping/focus gate (native — not on macOS TCG). Run on Linux x86_64 or Cloud Build:
xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest
DISPLAY=:99 python3 -m pytest  # when .cursor/start.sh already runs Xvfb :99 at 72 DPI

# Low-res window probe (inside same xvfb):
xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest tests/test_tk_runtime.py::test_screen_fits_without_clipping -v -k MIN_WINDOW
```

---

## 13. Evidence & logs (this checkout)

- `python3 -m pytest -k "not tk_runtime"` — **349 passed, 0 failed** on `Darwin 25.5.0 arm64, Python 3.10.0, pytest 9.0.3` with `BEAMO_WIPE_DRY_RUN=1`.
- `xvfb 72 DPI` clipping suite — `28/28 tk_runtime` on the Cloud Build hosted gate (see `docs/ci.md`). On this Mac headless, `DISPLAY=:1 @96 DPI` aborts — expected, not the gate.
- `BEAMO_WIPE_NO_OPEN=1 ./preview --web` → `web-preview/index.html` 54K, `BEAMO_WIPE_DRY_RUN=1` no `nwipe` spawn.
- No `nwipe` `Popen` in any fake path — spy `test_popen_inherits_wipe_lock_fd` asserts `pass_fds`, `cwd="/"`, `shell False`, `start_new_session True`.

---

## 14. Remaining risks & degraded hardware

- **800×600 / 1024×600 netbooks**: degraded, not gate. Window `minsize 1024×740` > screen; window manager may place it off-screen top and footer needs scroll. Tab still reaches primary; safety gates remain closed; documented as degraded not supported minimum.
- **HiDPI 144**: supported via pinning but not separately gated beyond structural test; manual HiDPI probe on hosted gate is a follow-up.
- **USB-SATA bridges (`tran sata` for USB stick)**: label scan alone fails closed — correct, mount path is ground truth.
- **eMMC-only (`mmcblk0boot0` not selectable)**: correct empty `PICK_EMPTY`.
- **Secure Boot enabled**: unsigned image rejects boot — correct, not a bypass.
- **RAID/Chromebooks/Apple Silicon**: unsupported, not claimed.

---

*Verification before merge:* every row in §4 has a test or structural inspection; every safety gate row asserts `runner.started is False` when bypass is attempted; no row claims 800×600 as fully fitting; no subscription/military/any-computer claims per `docs/claims.md`.
