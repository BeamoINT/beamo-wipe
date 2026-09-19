# #80 Reflow the whole layout for larger text

Fake disks only. No image published.

## Baseline

Stacked on `feat/user-text-size` (`09808dc`). Pixel fonts already grow with
the session text-size id, but many labels still wrapped at a snapshot of
`lay.wrap`. Cards, chips, and warnings live in `_Box` canvases that
`_clipping_problems` does not inspect. The last-chance ring was a fixed
64px canvas. Comparison stayed two columns above 700px even when type
was large.

## Acceptance

1. Prose wraplength follows the parent allocation, not a fixed wrap snapshot.
2. Last-chance review stacks and the countdown ring grows with type scale.
3. Footer hints wrap above the action row when type is enlarged.
4. Comparison drops to one column when type is enlarged.
5. At 800×600 and 1024×740 with Extra large (`text_scale=1.35`), walkable
   screens keep footer actions on-window and do not clip labels inside cards.
6. Identity, warnings, and destructive copy stay in the widget tree.
7. `layout_for` takes one `text_size` id; `type_scale` is derived.

## Verification

- `python3 -m pytest tests/test_layout.py tests/test_text_size.py tests/test_reflow_large_text.py`

Tk pixels: large-type walks cover 800×600 and 1024×740.

## Intentional difference

Console 80×24 already wraps by character columns. Helper is a boot page.
`tk scaling 1.0` stays pinned; type scale is derived from the #79 control
(`wizard.text_size` → `wizard.text_scale`).
