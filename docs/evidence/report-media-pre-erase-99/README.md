# Backlog #99 — Surface report-media requirements before erase

RISK (honest): FR/DE wording is first-draft, written without
native-speaker review (same standing risk as #87–#98).
Recommend native review before any release.

## Baseline (before implementation)

Source identity: `60d827a` on branch
`feat/improve-screen-hierarchy`, plus uncommitted #87–#98 WIP
(all preserved untouched).

Reproduce: `BEAMO_WIPE_DRY_RUN=1 python3 -m pytest`

Result at #98 close: **2 failed, 2816 passed, 549 skipped**
(headless Chrome SIGABRT + sandbox socket denial, both
pre-existing environmental).

Guidance baseline (verified by reading the code):

- Requirements exist only inside "Need a report?" help
  (`REPORT_HELP_NEED/INSERT/PLUGGED`), reachable
  pre-erase solely via a utility link on WHAT/METHOD/
  ADVANCED. WHAT and PICK mention no report media.
- Exporter truth (`support_export.py`): exactly one NEW
  removable USB, exactly one FAT32 volume (FAT12/16
  refused, other filesystems unmounted), volume size at
  least 1 MiB, writable and unmounted; already-attached
  media refused (insert only when prompted).
- Helper "What this USB does" card has no report-media
  paragraph.

## Design decisions (recorded before implementation)

- Two shared constants, no new wizard API (renderers
  branch on `report_wanted` directly): static
  `REPORT_MEDIA_WHAT` on WHAT (separate FAT32 USB, one
  volume any size, unplugged until asked, already-plugged
  refused, pointer to Need a report?) and conditional
  `REPORT_MEDIA_WANTED` on PICK iff wanted (stay
  unplugged, extra USBs confuse the list, unplug-only-
  that-USB + Check-disks-again remedy).
- WHAT_BULLETS stays at 3 (pinned by `test_copy.py`);
  the notice is a separate info panel between bullets
  and power in every renderer.
- Full filesystem matrix stays in `REPORT_HELP_NEED`
  (already complete); the notice carries essentials +
  pointer. No notice on destructive confirm screens.

## Acceptance criteria (measurable)

1. WHAT shows the static notice in Tk, console curses,
   plain console, accessible, and gallery with identical
   shared text.
2. PICK shows the conditional notice iff
   `report_wanted`, in all renderers + gallery.
3. No-report path: no PICK notice; WHAT notice stays
   informational with an opt-in pointer.
4. Keyboard access: R opens help from WHAT, Space
   toggles the preference (existing entry + new toggle
   test); notices add no focusable controls.
5. Filesystem/space: FAT32 + one volume + any size in
   the notice; exFAT/NTFS/FAT12/16/no-format pinned in
   help text.
6. Already-attached refusal + no target confusion:
   named in both notices; exporter refusal behavior
   unchanged.
7. FR/DE parity, helper EN/FR/DE, packaged
   `START-HERE.html` sync, docs updated.

## Implementation

- `src/beamo_wipe/copy.py`: `REPORT_MEDIA_WHAT`,
  `REPORT_MEDIA_WANTED`.
- Tk `_what` (info panel between bullets and power),
  `_pick` (conditional info panel after warnings);
  console curses WHAT (paged lines) + PICK (fixed
  notice above disk list), plain WHAT + PICK;
  accessible WHAT + PICK labels; gallery payload +
  WHAT panel + conditional PICK panel.
- `locales/fr.py`, `locales/de.py`; helper "What this
  USB does" paragraph x3; `START-HERE.html` sync;
  `docs/screens.md` WHAT/PICK rows.

Fold work during verification: WHAT was exactly at the
80x24 fold (18/18) before #99, so the notice now sits
between bullets and power (all renderers, same order).
Verified above-fold in EN/FR/DE with the wall-power
reminder still visible. Tk WHAT always has a scroll
host; console WHAT pages with the read-more hint.

## Verification

- New `tests/test_report_media_notice.py` (16 tests):
  13 failed before, all pass after. Tk (4) and
  accessible (3) tests added; they skip headless here
  and run under CI/Xvfb.
- `test_short_terminal_scrolls_power_warning_into_view`
  budget 8→10 downs (task adds WHAT rows; intent —
  scroll reachability + geometry bounds — preserved and
  strengthened with a notice assertion).
- Full suite: **2 failed, 2832 passed, 553 skipped** —
  the same 2 pre-existing environmental failures.
- Blocking ruff selections pass (src + tests); new
  file clean under full ruff; gallery JS passes
  `node --check`; mypy advisory unchanged (22
  pre-existing errors).
- Ignored staged-chroot tree re-synced (8 files).
- Tk/accessible runtime, ISO/QEMU, live nwipe remain
  CI/VM-only, unproven on this Mac.
- No commit (not authorized).
