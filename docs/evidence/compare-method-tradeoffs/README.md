# #76 Make erase-method tradeoffs easy to compare

Fake disks only. No image published.

## Baseline (`origin/main` `60d827a`)

All three method cards use the same layout: title, overwrite sentence, and a
clock plus check sentence. Quick zero’s “does not check” sits on a clock
row, so it looks like the others. Three overwrites does not say it is extra
work or that extra passes still miss hidden storage. The SSD/hidden-storage
panel is already on the method screen.

Engine mapping is unchanged: Everyday `prng`/`last`, Extra `dodshort`/`last`,
Quick zero `zero`/`off`.

## Acceptance

1. Quick zero is marked **No check**, without a clock, and still says it does
   not check the overwrite.
2. Three overwrites is marked **More overwrites** and states it is extra work
   versus Everyday, and that extra passes do not reach hidden storage.
3. Everyday stays the default and keeps **Recommended**.
4. Overwrite/verify sentences still match argv, evidence, and last-chance
   summaries. No certificate or hidden-area-erased claims.
5. The method-screen storage notice remains.
6. Keyboard 1/2/3 and card selection still choose the same methods.
7. Tk, gallery, console, GTK, and `docs/screens.md` stay aligned.

## Verification

- `python3 -m pytest tests/test_ui_system.py::test_method_tradeoffs_are_comparable tests/test_method_operation_copy.py`
- Tk method layout tests PASS
- Hosted `lint` / `preview` / `negative` PASS
- Full pytest: new tests passed. Pre-existing on this Mac: GTK `gi` missing, Microsoft citation HTTP 403, gitignored `support_export.py` drift, compare-disks Tk focus flake
- Gallery screenshot `method-1280.png` (fake disks)

Tk pixels: `screencapture` is TCC-blocked.

## Intentional difference

Helper does not choose a method. The 80×24 console keeps overwrite+verify
as one wrapped line and appends Extra’s extra-work sentence to that same
line so all three methods stay on one page.
