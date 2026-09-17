# #81 Unify native control appearance and behavior

Fake disks only. No image published.

## Baseline (`origin/main` `60d827a`)

Footer actions use `_Button` with hover, press, focus, and disabled fills.
Ghost utilities share that class but a disabled ghost still paints the grey
disabled pill. `_CheckRow` (compare disks, report preferences) has no hover,
press, or checked fill, so it reads as leftover native chrome next to the
owner card and gallery `.checkrow`. Gallery ghost buttons have hover only.
GTK utilities have no hover/press CSS.

## Acceptance

1. Ghost, primary, secondary, and danger share hover, press, focus, and
   disabled treatment. Disabled ghost stays quiet (no grey pill).
2. `_CheckRow` matches gallery `.checkrow`: hover, press, checked tint,
   keyboard focus. Space/Return and `invoke()` still toggle. Release-inside
   activates, like `_Button`.
3. In-body ghosts (storage limits, disk help, more details, refresh,
   diagnostic, report help) use the same compact ghost.
4. Gallery and GTK pick up the same hover/press/disabled/checked states.
   GTK keeps native CheckButton/RadioButton roles.
5. Identity, warnings, and destructive red are unchanged.

## Verification

- `python3 -m pytest tests/test_ui_system.py::test_shared_controls_share_hover_press_checked_and_disabled`
- `DISPLAY=:0 pytest tests/test_compare_disks.py tests/test_tk_runtime.py::test_report_help_rendered_preference_and_layout`
- Hosted `lint` PASS

## Intentional difference

Console has no pointer states. Helper is a boot page. Owner remains a large
choice card (28px check); compact rows stay 22px.
