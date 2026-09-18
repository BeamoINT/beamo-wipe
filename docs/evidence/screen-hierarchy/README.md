# #83 Improve hierarchy on dense and sparse screens

Fake disks only. No image published.

## Baseline (`origin/main` `60d827a`)

One spacing rhythm is used regardless of how much the screen has to say.

Introductions (keyboard, what happens, ownership) open with `title_top=24`
and `title_bottom=14`. Gallery `h1` uses `margin: 28px 0 16px`. Ownership
is a title plus one checkbox, then a large empty band above the footer.
Splash clusters the mark, tagline, roadmap, and Continue with 26/12/24/34
px gaps inside a centered field.

Dense screens do not group their tasks:
- Method: a full identity card, storage notice, and limits control sit
  above three method cards with 10px gaps, so the choice is not the
  first scannable group.
- Comparison: identities sit in an unframed grid (`padx=3, pady=3`).
- Result: `_done` packs expanding spacers above and below, vertically
  centering erase status, disk identity, and report status. Gallery
  `.centerstage` does the same and puts the disk card after report
  status.
- Report help: six long paragraphs with no headings.

Identity, exclusions, destructive warnings, and report/erase separation
are present. This task must not hide them.

## Acceptance

1. Introductions start closer to the header. Default `title_top` is at
   most 16px and `title_bottom` at most 10px. Compact 800×600 stays at
   most 8/6. Splash stays centered but the mark–action cluster is tighter.
2. Method cards are the scannable choice group: tighter within the group,
   identity and storage limits still visible above them, no field removed.
3. Comparison identities read as separate grouped cards with model,
   capacity, serial, connection, and uncertainty notes still shown.
4. Result is top-aligned. Erase status is above report status. The
   selected disk stays visible and above report status in Tk. Gallery
   matches that reading order. Expanding spacers no longer center the
   result.
5. Report help keeps every requirement and adds a short heading on each
   existing section. Sequential console still uses one Enter per section.
6. Long identities, focus, keyboard, and 800×600 / 1024×740 / 1280×820
   still fit. Fail-closed disk-safety is unchanged.
7. Tk, gallery, GTK, console, helper, and docs stay aligned. Intentional
   differences are documented.

## After (branch `feat/improve-screen-hierarchy`, base `60d827a`)

1. Introductions: default `title_top`/`title_bottom` are now 16/10 and
   large 18/12 (`src/beamo_wipe/ui/layout.py`); compact stays 8/6.
   Splash keeps its centered field with a tighter mark–tagline–roadmap–
   action cluster in Tk (`_splash`) and gallery (`.splashwrap`).
2. Method: Tk method cards use 6px gaps with 8px inner pad
   (`_method_card`); identity summary, storage notice, and limits
   control stay above them, untouched. Gallery already grouped at 8px.
3. Comparison: Tk identity cells are framed `SURFACE_ALT` cards with
   6px gutters (`_comparison`); entries (model, capacity, serial,
   connection, uncertainty notes) are unchanged. Gallery `.compare-pre`
   was already framed.
4. Result: `_done` no longer packs expanding centering spacers; the
   badge is 72px and content starts at the top. Reading order is erase
   status, selected-disk summary, then report status in Tk, gallery
   (`.result`, `summaryCard` before `report-status-heading`), and GTK
   (linear `identity()` before report heading, unchanged).
5. Report help: each of the six `REPORT_HELP_SECTIONS` keeps its full
   requirement text and gains a one-line heading (`src/beamo_wipe/copy.py`).
   Tk/GTK readers and gallery show the heading as the first line;
   plain console prints the heading line then the wrapped body with
   the same one-Enter-per-section loop; curses already split on `\n`.
6. Nothing in disk discovery, boot-USB exclusion, confirm gating, or
   nwipe flags changed. Reduced title pads strictly add room at
   800×600 / 1024×740 / 1280×820; no focus, keyboard, or reader
   behavior changed.
7. Helper has no wizard screens (only passing prose mentions of
   reports); no docs copy changed meaning.

Gallery selected states (`.card.sel`, `.ownercard.checked`) were
re-based to 13/17px against the tighter base padding so checking or
selecting a card no longer grows its box by a step.

Verification: `tests/test_screen_hierarchy.py` (5 tests) pins the new
rhythm, result order, method grouping, headings, and stable
selected-state box sizes. Full
`python3 -m pytest` passes except three failures also present on the
clean base: headless-Chrome SIGABRT in `test_helper_boot_guidance`,
staged-copy drift in `test_live_image`, and QMP `PermissionError` in
`test_usb_lab`. Tk/GTK/browser tests skip in this sandbox (no
DISPLAY, no `gi`, browsers abort); the hosted gate covers them.

After screenshots: not captured here — headless Chrome SIGABRTs and
Firefox exits without rendering in this sandbox. To reproduce the
before/after pairs at 1280×1100:

```bash
BEAMO_WIPE_NO_OPEN=1 ./preview --web
P="file://$PWD/web-preview/index.html"
chrome --headless=new --screenshot=after-what-1280.png --window-size=1280,1100 "$P#s=what"
chrome --headless=new --screenshot=after-owner-1280.png --window-size=1280,1100 "$P#s=owner"
chrome --headless=new --screenshot=after-method-1280.png --window-size=1280,1100 "$P#scenario=happy&s=method&disk=0"
chrome --headless=new --screenshot=after-report-1280.png --window-size=1280,1100 "$P#s=report_help"
chrome --headless=new --screenshot=after-done-1280.png --window-size=1280,1100 "$P#scenario=happy&s=done&disk=0"
```

Incidental: `tests/test_compare_disks.py` and
`tests/test_group_partitions.py` now use the repo-standard
`_needs_display()` / `pytest.importorskip("gi")` guards so the local
suite skips instead of SIGABRTing Tk on headless macOS. Both aborts
reproduce on the clean base.

## Intentional differences

- Splash remains a centered field; only inner gaps tighten. Blocked and
  empty status screens stay centered — they are not dense results.
- GTK comparison stays sequential labeled text (AT-SPI). Tk/gallery use
  visual cards.
- Console has no pixel spacing; report headings appear as the first line
  of each existing help paragraph.
- Curses result keeps its existing disk-first order (identity, erase
  status, report status); only Tk and gallery were reordered here.
- The boot helper has no wizard screens.
