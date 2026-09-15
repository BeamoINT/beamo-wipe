# Commands run for #113

All fake disks. `BEAMO_WIPE_DRY_RUN=1` is forced by `tests/conftest.py`.
Never nwipe. No ISO build.

```sh
git fetch && git pull --ff-only
git checkout -b feat/slow-unusual-interactions   # from main 4c26217

python3 -m pytest tests/test_slow_unusual_interactions.py -v --tb=short
# 33 passed

python3 -m ruff check tests/test_slow_unusual_interactions.py
python3 -m compileall -q src/beamo_wipe tests/test_slow_unusual_interactions.py
git diff --check

python3 -m pytest \
  tests/test_refresh_scan_flow.py \
  tests/test_progress_timing.py \
  tests/test_unsure_disk.py \
  tests/test_confirmation_gates.py \
  tests/test_identity_soft_break.py \
  tests/test_console_parity.py \
  tests/test_report_failure_recovery.py \
  tests/test_refresh_disks.py \
  tests/test_slow_unusual_interactions.py -q

dbus-run-session -- xvfb-run -a -s "-screen 0 1600x1000x24 -dpi 72" python3 -m pytest
```

Original-gap probe (inverted Enter-repeat helper; fake runner only):

```sh
PYTHONPATH=src python3 -c '...'  # see original-regression.txt
```
