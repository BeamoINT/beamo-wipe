# Notion Details append — #59 (paste this)

**Status: Done.** Coordinator: mark the Notion card Done. MCP Notion tools were not available in this Grok CLI session.

Continued with **Grok 4.6 high** via the T3-wired Grok CLI. Branched from current `main` as-is. Did not merge or depend on PR #42 (`feat/slow-unusual-interactions`).

### Baseline

- Repo: `beamo-wipe`
- Starting `main`: `4c26217877047abe244bd3ef9266a1ced1db5491` — `fix: gallery HTML-escape pin matches boot-card serial rendering`
- Branch: `feat/guided-boot-troubleshooting`
- Implementation commit: `5a69ae5970233e1cd933411759f7ad3e49a188ae` — `feat: guide USB, boot-key, firmware, and launcher failures`
- Helper tests on that SHA before product edits: 14 passed (`tests/test_helper_boot_guidance.py`)
- Acceptance criteria were written in `docs/evidence/guided-boot-help-59/README.md` before coding

### What landed

Offline guided troubleshooting for four startup problems, with simple illustrations and phone-friendly steps:

1. USB missing / not listed
2. Boot-menu key does nothing
3. Computer refused the USB (Secure Boot / legacy, non-risky)
4. Launcher failed

- `helper/index.html` — chooser at the top of START-HERE.html. No JavaScript, no extra files, no network required for the flow.
- `desktop/web/index.html` + `style.css` — the same four branches in launcher help.
- Tests in `tests/test_helper_boot_guidance.py` pin branches, BitLocker-before-firmware, forbidden phrases, offline/keyboard/narrow CSS, and Chrome 360px dumps.
- Evidence shots and layout notes under `docs/evidence/guided-boot-help-59/`.

Firmware copy still starts with the BitLocker recovery-key warning. The helper does not change Secure Boot, does not extract BitLocker keys, and does not tell anyone to disable Secure Boot, clear CMOS, or reset BIOS. First steps are another direct port, Windows Recovery **Use a device**, and the manufacturer’s startup instructions.

### Intentional differences

Helper is the full USB document (kiosk recovery, Intel Mac Option key). Desktop help is for someone already in the launcher; it omits the Option key because the launcher does not run on macOS, and it points at START-HERE.html for kiosk recovery.

### Verification

- `python3 -m pytest tests/test_helper_boot_guidance.py` — **20 passed**
- `go test ./...` in `desktop/` — ok
- `node --check desktop/web/app.js` — ok
- Full local pytest at Xvfb 72 DPI reached 100%. One failure is `test_kiosk_recovery.py::test_idle_recovery_is_stable_and_signals_never_relaunch[1]` (SIGHUP). `packaging/live` and that test are unchanged vs main — not this change. SIGTERM case passed.

No nwipe on a real disk. No ISO built or released. Fake UI / dry-run only.

### Confirmations

- Offline guided flow: yes
- No risky firmware advice: yes
- Notion: **Done** (coordinator apply; tools were not connected)
