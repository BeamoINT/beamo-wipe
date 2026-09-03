# SPDX-License-Identifier: GPL-3.0-or-later
"""Write a browser click-through of the wizard. Preview only — does not wipe."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote

from beamo_wipe import copy as C
from beamo_wipe.demo import discovery_for_scenario
from beamo_wipe.methods import METHODS
from beamo_wipe.models import MethodId
from beamo_wipe.safety import confirm_spec, listed_disks, same_size_conflict


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


_ASSETS = Path(__file__).resolve().parent / "assets"


def _mark_body() -> str:
    """The brand mark's inner artwork (path elements), whitespace-collapsed."""
    svg = (_ASSETS / "logo-mark.svg").read_text(encoding="utf-8")
    body = re.sub(r"^[\s\S]*?<svg[^>]*>", "", svg)
    body = re.sub(r"</svg>\s*$", "", body)
    return re.sub(r"\s+", " ", body).strip()


def _logo_svg(width: int, height: int) -> str:
    """The real Beamo mark as a one-line inline SVG sized for the template.

    Recolors the B to navy so the mark reads on the white wizard chrome.
    The favicon keeps the dark-surface (white B on a navy tile) treatment.
    """
    body = _mark_body().replace('fill="#FFFFFF"', 'fill="#0A1B34"')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="128 162 264 221" aria-hidden="true">{body}</svg>'
    )


def _favicon_uri() -> str:
    """The mark on a navy tile, as a self-contained data-URI favicon."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        '<rect width="64" height="64" rx="14" fill="#0A1B34"/>'
        '<g transform="translate(9 12.75) scale(0.1742) translate(-128 -162)">'
        + _mark_body()
        + "</g></svg>"
    )
    return "data:image/svg+xml," + quote(svg, safe="")


def _disks_payload(scenario: str = "happy") -> list[dict]:
    result = discovery_for_scenario(scenario)  # type: ignore[arg-type]
    peers = listed_disks(result)
    out = []
    for disk in result.disks:
        spec = None
        if not disk.is_boot:
            spec = confirm_spec(disk, peers)
        out.append(
            {
                "path": disk.path,
                "name": disk.display_name,
                "size": disk.size_phrase,
                "kind": disk.kind.value,
                "kindLabel": C.kind_label(disk.kind),
                "bus": disk.bus,
                "serial": disk.serial or "no serial",
                "isBoot": disk.is_boot,
                "token": spec.token if spec else "",
                "prompt": spec.prompt if spec else "",
                "warning": "" if disk.is_boot else C.confirm_warning(disk),
                "eraseLabel": "" if disk.is_boot else C.erase_now_label(disk),
            }
        )
    return out


def gallery_html() -> str:
    result = discovery_for_scenario("happy")
    payload = {
        "app": C.APP_NAME,
        "previewBanner": C.PREVIEW_BANNER,
        "splash": C.SPLASH_TAGLINE,
        "titles": {
            "what": C.TITLE_WHAT,
            "owner": C.TITLE_OWNER,
            "pick": C.TITLE_PICK,
            "confirm": C.TITLE_CONFIRM,
            "method": C.TITLE_METHOD,
            "advanced": C.TITLE_ADVANCED,
            "last": C.TITLE_LAST,
            "working": C.TITLE_WORKING,
            "doneOk": C.TITLE_DONE_OK,
            "doneFail": C.TITLE_DONE_FAIL,
            "blocked": C.TITLE_BLOCKED,
            "empty": C.TITLE_EMPTY,
        },
        "whatLead": C.WHAT_LEAD,
        "what": list(C.WHAT_BULLETS),
        "whatMore": C.WHAT_MORE,
        "engine": C.ENGINE_LINE,
        "secureBoot": C.SECURE_BOOT_HINT,
        "owner": C.OWNER_CHECKBOX,
        "ownerLead": C.OWNER_LEAD,
        "bootUsb": C.BOOT_USB_BANNER,
        "identify": C.IDENTIFY_ERROR,
        "empty": C.EMPTY_DISKS,
        "ssd": C.SSD_FOOTER,
        "sameSize": C.SAME_SIZE_HINT,
        "sameSizeConflict": same_size_conflict(listed_disks(result)),
        "working": C.WORKING_PULSE,
        "doneOk": C.DONE_OK_PREVIEW,
        "doneFail": C.DONE_FAIL_PREVIEW,
        "pickSubtitle": C.pick_subtitle(),
        "confirmLead": C.CONFIRM_LEAD,
        "methodLead": C.METHOD_LEAD,
        "lastLead": C.LAST_LEAD,
        "recommended": C.RECOMMENDED_TAG,
        "matchWait": C.CONFIRM_MATCH_WAIT,
        "matchOk": C.CONFIRM_MATCH_OK,
        "countdownCaption": C.COUNTDOWN_CAPTION,
        "countdownReady": C.COUNTDOWN_READY,
        "advancedLead": C.ADVANCED_LEAD,
        "advancedNote": C.ADVANCED_LOG_NOTE,
        "advancedLogLabel": C.ADVANCED_LOG_LABEL,
        "buttons": {
            "understand": C.BTN_UNDERSTAND,
            "shutdown": C.BTN_SHUTDOWN,
            "closePreview": C.BTN_CLOSE_PREVIEW,
            "runAgain": C.BTN_RUN_AGAIN,
            "continue": C.BTN_CONTINUE,
            "back": C.BTN_BACK,
            "erase": C.BTN_ERASE,
            "advanced": C.BTN_ADVANCED,
            "more": C.BTN_MORE,
            "less": C.BTN_LESS,
        },
        "hints": {
            "default": C.HINT_DEFAULT,
            "pick": C.HINT_PICK,
            "owner": C.HINT_OWNER,
            "method": C.HINT_METHOD,
            "confirm": C.HINT_CONFIRM,
            "lastChance": C.HINT_LAST_CHANCE,
            "blocked": C.HINT_BLOCKED,
            "working": C.HINT_WORKING,
            "splash": C.HINT_SPLASH,
        },
        "helperHref": "../helper/index.html",
        "methods": {
            mid.value: {
                "title": C.METHOD_CARDS[mid]["title"],
                "blurb": C.METHOD_CARDS[mid]["blurb"],
                "pace": C.METHOD_CARDS[mid]["pace"],
                "key": C.METHOD_CARDS[mid]["key"],
                "docs": METHODS[mid].docs_name,
                "nwipe": METHODS[mid].nwipe_method,
            }
            for mid in (MethodId.EVERYDAY, MethodId.EXTRA, MethodId.QUICK_ZERO)
        },
        "disks": _disks_payload("happy"),
    }
    # JSON is embedded in a script element. Escaping HTML-significant code
    # points prevents a future fixture/copy string containing </script> from
    # terminating the element and injecting markup into the local preview.
    data = (
        json.dumps(payload)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    return (
        _TEMPLATE
        .replace("__PAYLOAD__", data)
        .replace("__LOGO_HEADER__", _logo_svg(36, 30))
        .replace("__LOGO_SPLASH__", _logo_svg(70, 58))
        .replace("__FAVICON__", _favicon_uri())
    )


def write_gallery(dest: Path | None = None) -> Path:
    if dest is None:
        root = project_root()
        if (root / "helper" / "index.html").is_file():
            dest = root / "web-preview" / "index.html"
        else:
            dest = Path.cwd() / "web-preview" / "index.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(gallery_html(), encoding="utf-8")
    return dest


def open_gallery(dest: Path | None = None) -> Path:
    import webbrowser

    path = write_gallery(dest)
    webbrowser.open(path.resolve().as_uri())
    return path


# The template mirrors the Tk design system in ui/tk_wizard.py: same tokens,
# same components (cards, panels, buttons, key-caps, countdown ring), same
# screen layouts. Keep the two in sync when the design changes.
_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="__FAVICON__">
<title>Beamo Wipe — screen preview</title>
<style>
  :root {
    /* Shared palette, pinned against ui/tk_wizard.py by tests/test_ui_system.py. */
    --bg: #FFFFFF; --surface: #FFFFFF; --surface-alt: #F4F6FB;
    --ink: #0C1728; --muted: #47536B;
    --border: #DCE2EC; --border-strong: #74839F;
    --navy: #0A1B34; --navy-soft: #16315C; --navy-muted: #C9D6E8;
    --primary: #1D4ED8; --primary-dark: #1A41B8; --primary-press: #16337F; --primary-tint: #E9EFFC;
    --danger: #B3261E; --danger-dark: #8E1D16; --danger-press: #6E1510; --danger-tint: #FBEBE9; --danger-border: #E6A79E;
    --ok: #17703F; --ok-tint: #E7F2EB;
    --warn: #7A5200; --warn-bg: #FBF1D5; --warn-border: #E3CE96;
    --usb-bg: #F4EFE3; --usb-border: #D9CEB5;
    --focus: #1A3FA0; --accent: #E8A317;
    --disabled-bg: #E4E8EF; --disabled-fg: #6E7989; --track: #DFE5EF;
    /* Soft three-layer shadow, mirroring the stacked rects in _Box._redraw:
       darkest sliver hugging the card, lighter bands falling away. */
    --shadow: 0 1px 0 #E0E5EF, 0 3px 0 #ECEFF5, 0 6px 0 #F7F8FB;
    /* Selection halo, mirroring _Box(halo=True): PRIMARY blended 22% toward white. */
    --halo: 0 0 0 2px #4F75E1;
  }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; background: #D5DBE4; color: var(--ink); }
  .page { max-width: 1100px; margin: 0 auto; padding: 24px 16px 64px; }
  .note { background: var(--accent); color: var(--navy); font-weight: 700; padding: 14px 18px; margin-bottom: 16px; font-size: 17px; border-radius: 12px; }
  .note code { background: #fff7d6; padding: 2px 6px; border-radius: 6px; }
  .note a { color: var(--navy); }
  .scenarios { margin: 0 0 20px; }
  .scenarios button { font-size: 15px; font-weight: 600; margin: 0 8px 8px 0; padding: 10px 18px; background: var(--navy); color: #fff; border: 0; border-radius: 10px; cursor: pointer; }
  .scenarios button:hover { background: var(--navy-soft); }
  .scenarios button:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
  .shell { background: var(--bg); min-height: 740px; box-shadow: 0 12px 40px rgba(10,27,52,.25); border-radius: 14px; overflow: hidden; display: flex; flex-direction: column; }
  .preview-stripe { background: var(--accent); color: var(--navy); padding: 7px 24px; font-size: 14px; font-weight: 700; }
  /* Quiet white chrome: the navy-on-transparent mark sits on the field,
     a hairline separates header from body — mirroring _draw_header. */
  .hdr { background: var(--bg); border-bottom: 1px solid var(--border); color: var(--ink); height: 56px; padding: 0 24px; display: flex; justify-content: space-between; align-items: center; }
  .brandrow { display: flex; align-items: center; gap: 12px; font-size: 16px; font-weight: 700; }
  .brandchip { display: flex; align-items: center; justify-content: center; flex: none; }
  .brandchip svg { display: block; }
  .steptext { font-size: 12px; font-weight: 700; color: var(--muted); letter-spacing: .07em; text-transform: uppercase; white-space: nowrap; }
  .strip { height: 3px; background: var(--track); }
  .strip .sfill { height: 100%; background: var(--accent); width: 0; transition: width .25s ease; border-radius: 0 1.5px 1.5px 0; }
  .body { flex: 1; padding: 0 24px 12px; background: var(--bg); display: flex; }
  .col { max-width: 940px; margin: 0 auto; width: 100%; display: flex; flex-direction: column; }
  /* The one screen-header pattern, mirroring _title_block: bold title,
     optional muted subtitle. compact is for the tightest screens. */
  h1 { font-size: 34px; margin: 24px 0 14px; color: var(--ink); letter-spacing: -.01em; }
  h1.sub { margin-bottom: 4px; }
  h1.compact { margin: 10px 0 6px; }
  .subtitle { font-size: 16px; color: var(--muted); margin: 0 0 14px; }
  /* Vertically centered content band between title and footer, mirroring
     _center_zone: short content floating at the top reads as unfinished. */
  .cz { flex: 1; display: flex; flex-direction: column; }
  .czc { margin: auto 0; padding: 8px 0; }
  .lead { font-size: 18px; line-height: 1.45; margin: 0 0 12px; }
  .muted { color: var(--muted); }
  .small { font-size: 14px; }
  .mono { font-family: "SF Mono", Menlo, Consolas, "DejaVu Sans Mono", monospace; }
  .kbd { display: inline-block; background: var(--surface-alt); border: 1px solid var(--border); border-radius: 6px; padding: 1px 7px; font-size: 12px; font-weight: 700; color: var(--ink); line-height: 1.35; }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 15px 18px; margin: 0 4px 10px; }
  .card.hero { box-shadow: var(--shadow); margin-left: 0; margin-right: 0; padding: 16px 20px; }
  .card.pickable { cursor: pointer; }
  .card.pickable:hover { background: var(--surface-alt); }
  .card.pickable:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
  .card.sel { border: 2px solid var(--primary); background: var(--primary-tint); padding: 14px 17px; box-shadow: var(--halo); }
  .card.sel:hover { background: var(--primary-tint); }
  .card.boot { background: var(--usb-bg); border-color: var(--usb-border); cursor: not-allowed; }
  .card .row { display: flex; align-items: flex-start; gap: 14px; }
  .card .grow { flex: 1; min-width: 0; }
  .card .title { font-size: 16px; font-weight: 700; }
  .card .title .chip { margin-left: 10px; }
  .card .size { font-size: 20px; font-weight: 700; white-space: nowrap; }
  .card .meta { margin-top: 4px; font-size: 14px; color: var(--muted); display: flex; flex-wrap: wrap; gap: 4px 0; align-items: center; }
  .card .meta .mono { color: var(--ink); font-size: 14px; }
  .card .meta .mono.ser { font-weight: 700; }
  .card .meta .mono.dev { color: var(--muted); font-size: 13px; }
  .card .meta .dot { color: var(--border-strong); margin: 0 6px; }
  .radio { flex: none; width: 22px; height: 22px; margin-top: 1px; border: 2px solid var(--border-strong); border-radius: 50%; position: relative; background: var(--surface); }
  .sel .radio { border-color: var(--primary); }
  .sel .radio::after { content: ""; position: absolute; inset: 4px; border-radius: 50%; background: var(--primary); }
  .chip { display: inline-block; font-size: 12px; font-weight: 700; padding: 2px 10px; background: var(--surface-alt); color: var(--muted); border-radius: 999px; vertical-align: 2px; }
  .chip.ok { color: var(--ok); background: var(--ok-tint); }
  .bootbanner { display: inline-block; margin-top: 10px; margin-left: 36px; color: var(--danger); font-weight: 700; font-size: 14px; background: var(--danger-tint); border: 1px solid var(--danger-border); border-radius: 999px; padding: 3px 11px; }
  .panel { display: flex; gap: 12px; align-items: flex-start; border: 1px solid; border-radius: 12px; padding: 13px 16px; font-size: 16px; line-height: 1.4; }
  .panel svg { flex: none; margin-top: 1px; }
  .panel.warn { background: var(--warn-bg); border-color: var(--warn-border); }
  .panel.danger { background: var(--danger-tint); border-color: var(--danger-border); }
  .panel.info { background: var(--surface-alt); border-color: var(--border); }
  .panel .extra { font-size: 14px; color: var(--muted); margin-top: 4px; }
  /* One-row footer, mirroring _footer_shell: secondary actions left, key
     hints centered, the primary action right, hairline on top. */
  .foot { border-top: 1px solid var(--border); padding: 0 24px; }
  .footrow { max-width: 940px; margin: 0 auto; padding: 12px 0 16px; display: flex; align-items: center; gap: 16px; }
  .fleft, .fright { display: flex; gap: 12px; flex: none; }
  .fhint { flex: 1; text-align: center; color: var(--muted); font-size: 14px; line-height: 1.9; }
  .fhint .kbd { margin: 0 1px; }
  button.btn { font-size: 17px; font-weight: 700; padding: 10px 24px; border: 0; border-radius: 999px; cursor: pointer; min-width: 112px; }
  button.btn:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
  .primary { background: var(--primary); color: #fff; min-width: 160px; }
  .primary:hover:not(:disabled) { background: var(--primary-dark); }
  .primary:active:not(:disabled) { background: var(--primary-press); }
  .danger { background: var(--danger); color: #fff; min-width: 160px; }
  .danger:hover:not(:disabled) { background: var(--danger-dark); }
  .danger:active:not(:disabled) { background: var(--danger-press); }
  .secondary { background: var(--surface); color: var(--ink); border: 1px solid var(--border-strong); }
  .secondary:hover:not(:disabled) { background: var(--surface-alt); }
  .secondary:active:not(:disabled) { background: #E6EAF0; }
  button.btn:disabled { background: var(--disabled-bg); color: var(--disabled-fg); border-color: transparent; box-shadow: none; cursor: not-allowed; }
  .linkbtn { background: none; border: 0; color: var(--primary); font-size: 14px; font-weight: 700; cursor: pointer; padding: 6px 10px; text-align: left; border-radius: 8px; margin-left: -10px; }
  .linkbtn:hover { background: var(--primary-tint); }
  .linkbtn:focus-visible { outline: 3px solid var(--focus); }
  .morelink { display: inline-block; margin: 8px 0 0; }
  .entryshell { background: var(--surface); border: 1px solid var(--border-strong); border-radius: 12px; padding: 10px 16px; box-shadow: var(--shadow); }
  .entryshell:focus-within { outline: 3px solid var(--focus); outline-offset: 2px; border-color: var(--focus); }
  input.token { font-family: "SF Mono", Menlo, Consolas, "DejaVu Sans Mono", monospace; font-size: 26px; font-weight: 700; width: 100%; padding: 4px 0; border: 0; outline: none; background: transparent; color: var(--ink); }
  .match { display: inline-flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 700; margin: 12px 0 0; color: var(--muted); background: var(--surface-alt); border: 1px solid var(--border); border-radius: 999px; padding: 6px 12px; }
  .match.ok { color: var(--ok); background: var(--ok-tint); border-color: var(--ok); }
  .bigstat { font-size: 56px; font-weight: 700; line-height: 1.05; letter-spacing: -.01em; min-height: 62px; }
  .bar { height: 14px; background: var(--track); border-radius: 7px; overflow: hidden; }
  .fill { height: 100%; background: var(--primary); width: 2%; border-radius: 7px; transition: width .2s ease; }
  .fill.indet { width: 30%; animation: slide 1.7s ease-in-out infinite alternate; }
  @keyframes slide { from { margin-left: 0; } to { margin-left: 70%; } }
  .status { width: 96px; height: 96px; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto; }
  .status.ok { background: var(--ok-tint); }
  .status.bad { background: var(--danger-tint); }
  .status .core { width: 72px; height: 72px; border-radius: 50%; color: #fff; font-size: 40px; font-weight: 700; display: flex; align-items: center; justify-content: center; }
  .status.ok .core { background: var(--ok); }
  .status.bad .core { background: var(--danger); }
  .badgehalo { width: 88px; height: 88px; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto; }
  .badgehalo.warn { background: var(--warn-bg); }
  .badgehalo.danger { background: var(--danger-tint); }
  .badgehalo.info { background: var(--surface-alt); }
  .ok { color: var(--ok); } .bad { color: var(--danger); }
  ul.bullets { list-style: none; margin: 0; padding: 20px 24px; background: var(--surface); border: 1px solid var(--border); border-radius: 14px; box-shadow: var(--shadow); }
  ul.bullets li { font-size: 18px; line-height: 1.45; padding: 2px 0; display: flex; }
  ul.bullets li + li { margin-top: 10px; }
  ul.bullets li::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: var(--accent); margin: 10px 14px 0 1px; flex: none; }
  .ownercard { display: flex; gap: 16px; align-items: flex-start; background: var(--surface); border: 1px solid var(--border-strong); border-radius: 14px; padding: 20px 22px; cursor: pointer; font-size: 18px; line-height: 1.45; }
  .ownercard:hover { background: var(--surface-alt); }
  .ownercard:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
  .ownercard.checked { border: 2px solid var(--primary); background: var(--primary-tint); padding: 19px 21px; box-shadow: var(--halo); }
  .ownercard.checked:hover { background: var(--primary-tint); }
  .cbox { flex: none; width: 28px; height: 28px; margin-top: 1px; border: 2px solid var(--border-strong); border-radius: 7px; background: var(--surface); color: #fff; font-size: 18px; font-weight: 700; line-height: 24px; text-align: center; }
  .ownercard.checked .cbox { background: var(--primary); border-color: var(--primary); }
  .ringwrap { display: flex; flex-direction: column; align-items: center; }
  .ringnum { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; font-size: 56px; font-weight: 700; }
  .countcap { font-size: 16px; color: var(--muted); margin-top: 12px; }
  .countcap.ready { color: var(--ok); font-weight: 600; }
  .advrow { font-size: 13px; margin: 0; padding: 7px 0; }
  .advrow + .advrow { border-top: 1px solid var(--border); }
  .methodblurb { font-size: 14px; color: var(--muted); margin: 4px 0 0; }
  .methodpace { font-size: 14px; color: var(--muted); margin: 4px 0 0; display: flex; gap: 7px; align-items: flex-start; }
  .methodpace svg { flex: none; margin-top: 1px; }
  .centerstage { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; }
  .centerstage h1 { margin: 22px 0 8px; }
  .statustext { font-size: 16px; color: var(--muted); max-width: 700px; margin: 0 auto; line-height: 1.45; }
  /* Splash: a plain white field, the navy-on-transparent brand mark,
     huge simple type, and one primary action — mirroring TkWizard._splash. */
  .splashwrap { min-height: 640px; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; position: relative; }
  .marktile { display: flex; }
  .marktile svg { display: block; }
  .wordmark { font-size: 64px; font-weight: 700; color: var(--ink); letter-spacing: -.01em; margin-top: 26px; line-height: 1.05; }
  .splashlead { font-size: 18px; line-height: 1.45; color: var(--muted); max-width: 620px; margin: 12px 0 0; }
  .splashwrap .btn.primary { min-width: 240px; padding: 14px 34px; margin-top: 34px; }
  .anykeycap { margin-top: 14px; font-size: 12px; color: var(--muted); }
  .disklist { flex: 1; min-height: 160px; overflow-y: auto; scrollbar-width: thin; scrollbar-color: #A3AEC2 transparent; }
  .disklist::-webkit-scrollbar { width: 12px; }
  .disklist::-webkit-scrollbar-thumb { background: #A3AEC2; border-radius: 6px; border: 3px solid var(--bg); }
  .disklist::-webkit-scrollbar-track { background: transparent; }
</style>
</head>
<body>
<div class="page">
  <div class="note">
    This is a <strong>preview</strong>. It does not erase disks. Click through like the USB wizard.
    The real window (same Tk screens as the live USB): <code>./preview</code>
    &nbsp;·&nbsp; <a href="../helper/index.html">Boot-menu helper</a>
  </div>
  <div class="scenarios">
    <button type="button" onclick="boot('happy')">Happy path</button>
    <button type="button" onclick="boot('empty')">No other disks</button>
    <button type="button" onclick="boot('blocked')">Cannot identify USB</button>
    <button type="button" onclick="boot('fail')">Failed wipe</button>
  </div>
  <div class="shell">
    <div class="preview-stripe" id="stripe"></div>
    <div class="hdr"><div class="brandrow"><span class="brandchip">__LOGO_HEADER__</span><div id="brand"></div></div><span class="steptext" id="step"></span></div>
    <div class="strip"><div class="sfill" id="sfill"></div></div>
    <div class="body" id="body"><div class="col" id="main"></div></div>
    <div class="foot" id="foot"><div class="footrow"><div class="fleft" id="btnsL"></div><div class="fhint" id="hint"></div><div class="fright" id="btnsR"></div></div></div>
  </div>
</div>
<script>
const P = __PAYLOAD__;
let screen = "splash";
let owner = false;
let selected = null;
let token = "";
let method = "everyday";
let tLeft = 5;
let timer = null;
let fail = false;
let mode = "happy";
let demoPct = null;
let showMore = false;

document.getElementById("stripe").textContent = P.previewBanner;
document.getElementById("brand").textContent = P.app;

// Filled badge icons, mirroring _icon_alert in the Tk UI.
function badge(kind, size) {
  const s = size;
  if (kind === "info") {
    const c = "#1D4ED8";
    return `<svg width="${s}" height="${s}" viewBox="0 0 ${s} ${s}">` +
      `<circle cx="${s/2}" cy="${s/2}" r="${s/2-2}" fill="${c}"/>` +
      `<circle cx="${s/2}" cy="${s*0.26}" r="${s*0.075}" fill="#fff"/>` +
      `<line x1="${s/2}" y1="${s*0.46}" x2="${s/2}" y2="${s*0.74}" stroke="#fff" stroke-width="${s*0.09}" stroke-linecap="round"/></svg>`;
  }
  const c = kind === "warn" ? "#7A5200" : "#B3261E";
  return `<svg width="${s}" height="${s}" viewBox="0 0 ${s} ${s}">` +
    `<path d="M ${s/2} ${2} L ${s-2} ${s-3} L 2 ${s-3} Z" fill="${c}" stroke="${c}" stroke-width="${s*0.18}" stroke-linejoin="round"/>` +
    `<line x1="${s/2}" y1="${s*0.36}" x2="${s/2}" y2="${s*0.62}" stroke="#fff" stroke-width="${s*0.09}" stroke-linecap="round"/>` +
    `<circle cx="${s/2}" cy="${s*0.75}" r="${s*0.06}" fill="#fff"/></svg>`;
}
const ICON_NO = '<svg width="22" height="22" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9.2" stroke="#B3261E" stroke-width="2.6"/><line x1="6" y1="18" x2="18" y2="6" stroke="#B3261E" stroke-width="2.6" stroke-linecap="round"/></svg>';
const MATCH_WAIT = '<svg width="22" height="22" viewBox="0 0 22 22"><circle cx="11" cy="11" r="8" fill="none" stroke="#74839F" stroke-width="2"/></svg>';
const MATCH_OK = '<svg width="22" height="22" viewBox="0 0 22 22"><circle cx="11" cy="11" r="10" fill="#17703F"/><path d="M6 11.5 9.5 15 16 7.5" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>';
const EMBLEM = '__LOGO_SPLASH__';

// Key names inside hint copy render as key-caps, mirroring _hint_bar.
const KEY_RE = /(Up\/Down|1, 2, or 3|any key|Enter|Esc|Space)/g;
const KEY_MAP = {"Up/Down": ["↑", "↓"], "1, 2, or 3": ["1", "2", "3"]};
function renderHint(text) {
  const el = document.getElementById("hint");
  el.innerHTML = "";
  let pos = 0;
  for (const m of text.matchAll(KEY_RE)) {
    if (m.index > pos) el.append(document.createTextNode(text.slice(pos, m.index)));
    const keys = KEY_MAP[m[0]] || [m[0]];
    keys.forEach((k, i) => {
      if (i > 0) el.append(document.createTextNode(" "));
      const cap = document.createElement("span");
      cap.className = "kbd";
      cap.textContent = k;
      el.append(cap);
    });
    pos = m.index + m[0].length;
  }
  if (pos < text.length) el.append(document.createTextNode(text.slice(pos)));
}

function boot(m) {
  mode = m;
  fail = (m === "fail");
  if (m === "fail") mode = "happy";
  screen = "splash";
  owner = false;
  selected = null;
  token = "";
  method = "everyday";
  tLeft = 5;
  demoPct = null;
  showMore = false;
  if (timer) clearInterval(timer);
  draw();
}
function disks() {
  let list;
  if (mode === "blocked") list = [];
  else if (mode === "empty") list = P.disks.filter(d => d.isBoot);
  else list = P.disks.slice();
  list.sort((a, b) => (a.isBoot - b.isBoot) || a.path.localeCompare(b.path));
  return list;
}
function selectable() { return disks().filter(d => !d.isBoot); }
function stepInfo() {
  const map = {splash:[0,"",""], what:[1,"Step 1 of 8",P.titles.what], owner:[2,"Step 2 of 8","Ownership"],
    pick:[3,"Step 3 of 8",P.titles.pick], blocked:[3,"Step 3 of 8",P.titles.pick], empty:[3,"Step 3 of 8",P.titles.pick],
    confirm:[4,"Step 4 of 8",P.titles.confirm], method:[5,"Step 5 of 8",P.titles.method],
    advanced:[5,P.titles.advanced,P.titles.advanced], last:[6,"Step 6 of 8",P.titles.last],
    working:[7,"Step 7 of 8",P.titles.working], done:[8,"Step 8 of 8",P.titles.doneOk]};
  return map[screen] || [0,"",""];
}
function btn(label, fn, cls, disabled) {
  const b = document.createElement("button");
  b.textContent = label;
  b.className = "btn " + (cls || "secondary");
  b.disabled = !!disabled;
  b.onclick = fn;
  return b;
}
function closePreview() {
  alert("Preview only. Close this tab when you are done.");
}
function tokenOk() {
  return selected && token.trim().toLowerCase() === selected.token.toLowerCase();
}
function panel(kind, text) {
  return `<div class="panel ${kind}">${badge(kind, 28)}<div>${text}</div></div>`;
}
function moreLink() {
  return `<button type="button" class="linkbtn morelink" id="more">${showMore ? P.buttons.less : P.buttons.more}</button>`;
}
function bindMore() {
  const el = document.getElementById("more");
  if (el) el.onclick = () => { showMore = !showMore; draw(); };
}
function esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
function metaLine(d) {
  let html = `<div class="meta"><span class="mono ser">${esc(d.serial)}</span>`;
  if (showMore) {
    html += `<span class="dot">·</span><span>${esc(d.bus)}</span><span class="dot">·</span><span class="mono dev">${esc(d.path)}</span>`;
  }
  html += `</div>`;
  return html;
}
function summaryCard(d) {
  const chip = d.kindLabel ? `<span class="chip">${esc(d.kindLabel)}</span>` : "";
  return `<div class="card hero"><div class="row" style="align-items:center">
    <div class="title grow">${esc(d.name)}${chip}</div>
    <div class="size">${esc(d.size)}</div></div>
    ${metaLine(d)}
  </div>`;
}
function diskCard(d) {
  const sel = selected && selected.path === d.path;
  const cls = d.isBoot ? "card boot" : ("card pickable" + (sel ? " sel" : ""));
  const icon = d.isBoot ? `<span class="radio" style="border:0;background:none">${ICON_NO}</span>` : `<span class="radio"></span>`;
  const chip = d.kindLabel ? `<span class="chip">${esc(d.kindLabel)}</span>` : "";
  // Use esc for attribute to prevent `"` breakout
  return `<div class="${cls}" data-path="${esc(d.path)}" ${d.isBoot ? "" : 'tabindex="0" role="button"'}>
    <div class="row">${icon}
      <div class="grow">
        <div class="row" style="align-items:center">
          <div class="title grow">${esc(d.name)}${chip}</div>
          <div class="size">${esc(d.size)}</div>
        </div>
        ${metaLine(d)}
        ${d.isBoot ? `<div class="bootbanner">${esc(P.bootUsb)}</div>` : ""}
      </div>
    </div>
  </div>`;
}
function draw() {
  const info = stepInfo();
  const stepEl = document.getElementById("step");
  stepEl.textContent = info[1];
  stepEl.style.visibility = stepEl.textContent ? "visible" : "hidden";
  document.getElementById("sfill").style.width = (info[0] / 8 * 100) + "%";
  const main = document.getElementById("main");
  const btnsL = document.getElementById("btnsL");
  const btnsR = document.getElementById("btnsR");
  const foot = document.getElementById("foot");
  main.innerHTML = "";
  btnsL.innerHTML = "";
  btnsR.innerHTML = "";
  // The splash keeps the white field clean: no header, no progress strip,
  // no footer — just the mark, the type, and one action.
  const splash = screen === "splash";
  document.querySelector(".hdr").style.display = splash ? "none" : "";
  document.querySelector(".strip").style.display = splash ? "none" : "";
  foot.style.display = splash ? "none" : "";
  renderHint(P.hints.default);
  if (screen === "splash") {
    main.innerHTML = `<div class="splashwrap">
      <div class="marktile">${EMBLEM}</div>
      <div class="wordmark">${P.app}</div>
      <p class="splashlead">${P.splash}</p>
      <button class="btn primary" id="herogo">${P.buttons.continue}</button>
      <div class="anykeycap">${P.hints.splash}</div></div>`;
    main.querySelector("#herogo").onclick = () => { screen = "what"; draw(); };
  } else if (screen === "what") {
    main.innerHTML = `<h1 class="sub">${P.titles.what}</h1><p class="subtitle">${P.whatLead}</p><div class="cz"><div class="czc">
      <ul class="bullets">${P.what.map(x=>"<li>"+x+"</li>").join("")}</ul>
      ${moreLink()}
      ${showMore ? `<div class="panel info" style="margin-top:12px">${badge("info", 28)}<div>
      <div>${P.secureBoot}</div><div class="extra">${P.engine}</div></div></div>` : ""}</div></div>`;
    bindMore();
    btnsL.append(btn(P.buttons.closePreview, closePreview, "secondary"));
    btnsR.append(btn(P.buttons.understand, () => { screen = "owner"; draw(); }, "primary"));
  } else if (screen === "owner") {
    main.innerHTML = `<h1 class="sub">${P.titles.owner}</h1>
      <p class="subtitle">${P.ownerLead}</p>
      <div class="cz"><div class="czc"><div class="ownercard${owner ? " checked" : ""}" id="own" tabindex="0" role="checkbox" aria-checked="${owner}">
        <span class="cbox">${owner ? "✓" : ""}</span><span>${P.owner}</span></div></div></div>`;
    const card = main.querySelector("#own");
    const toggle = () => { owner = !owner; draw(); };
    card.onclick = toggle;
    card.onkeydown = (e) => { if (e.key === " ") { e.preventDefault(); toggle(); } };
    btnsL.append(btn(P.buttons.back, () => { screen = "what"; draw(); }));
    renderHint(P.hints.owner);
    btnsR.append(btn(P.buttons.continue, () => { if (owner) { if (mode==="blocked") screen="blocked"; else if (!selectable().length) screen="empty"; else screen="pick"; draw(); } }, "primary", !owner));
  } else if (screen === "blocked") {
    main.innerHTML = `<div class="centerstage"><div class="badgehalo warn">${badge("warn", 51)}</div>
      <h1>${P.titles.blocked}</h1><p class="statustext">${P.identify}</p></div>`;
    btnsL.append(btn(P.buttons.back, () => { screen = "owner"; draw(); }));
    btnsR.append(btn(P.buttons.closePreview, closePreview, "primary"));
  } else if (screen === "empty") {
    main.innerHTML = `<div class="centerstage"><div class="badgehalo info">${badge("info", 51)}</div>
      <h1>${P.titles.empty}</h1><p class="statustext">${P.empty}</p></div>`;
    btnsL.append(btn(P.buttons.back, () => { screen = "owner"; draw(); }));
    btnsR.append(btn(P.buttons.closePreview, closePreview, "primary"));
  } else if (screen === "pick") {
    let html = `<h1 class="sub">${P.titles.pick}</h1><p class="subtitle">${P.pickSubtitle}</p>`;
    if (P.sameSizeConflict && mode === "happy") html += `<div style="margin-bottom:12px">${panel("warn", P.sameSize)}</div>`;
    if (selected && (selected.kind === "SSD" || selected.kind === "NVMe")) html += `<div style="margin-bottom:12px">${panel("info", P.ssd)}</div>`;
    html += moreLink();
    html += `<div class="disklist">`;
    disks().forEach(d => { html += diskCard(d); });
    html += `</div>`;
    main.innerHTML = html;
    bindMore();
    main.querySelectorAll(".card.pickable").forEach(el => {
      const pick = () => { selected = disks().find(d => d.path === el.dataset.path); draw(); };
      el.onclick = pick;
      el.onkeydown = (e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); pick(); } };
    });
    renderHint(P.hints.pick);
    btnsL.append(btn(P.buttons.back, () => { screen = "owner"; draw(); }));
    btnsR.append(btn(P.buttons.continue, () => { if (selected && !selected.isBoot) { screen = "confirm"; token=""; draw(); } }, "primary", !(selected && !selected.isBoot)));
  } else if (screen === "confirm") {
    const d = selected;
    main.innerHTML = `<h1>${P.titles.confirm}</h1><div class="cz"><div class="czc">
      ${summaryCard(d)}
      ${moreLink()}
      <div style="margin-top:12px">${panel("warn", d.warning)}</div>
      <p style="font-size:16px;margin:14px 0 8px">${d.prompt}</p>
      <div class="entryshell"><input class="token" id="tok" autocomplete="off" spellcheck="false"></div>
      <p class="match" id="match"></p></div></div>`;
    bindMore();
    const inp = main.querySelector("#tok");
    const matchEl = main.querySelector("#match");
    inp.value = token;
    const sync = () => {
      token = inp.value;
      const cont = document.getElementById("cont");
      if (cont) cont.disabled = !tokenOk();
      if (tokenOk()) { matchEl.innerHTML = MATCH_OK + "<span>" + P.matchOk + "</span>"; matchEl.className = "match ok"; }
      else { matchEl.innerHTML = MATCH_WAIT + "<span>" + P.matchWait + "</span>"; matchEl.className = "match"; }
    };
    inp.oninput = sync;
    inp.onkeydown = (e) => { if (e.key === "Enter" && tokenOk()) { e.preventDefault(); screen = "method"; draw(); } };
    sync();
    setTimeout(() => { inp.focus(); inp.setSelectionRange(token.length, token.length); }, 0);
    renderHint(P.hints.confirm);
    btnsL.append(btn(P.buttons.back, () => { screen = "pick"; draw(); }));
    const cont = btn(P.buttons.continue, () => { if (tokenOk()) { screen = "method"; draw(); } }, "primary", !tokenOk());
    cont.id = "cont";
    btnsR.append(cont);
  } else if (screen === "method") {
    let html = `<h1 class="compact sub">${P.titles.method}</h1><p class="subtitle" style="margin-bottom:6px">${P.methodLead}</p><div class="cz"><div class="czc">`;
    ["everyday","extra","quick_zero"].forEach(id => {
      const m = P.methods[id];
      const sel = method === id;
      html += `<div class="card pickable${sel ? " sel" : ""}" data-id="${id}" tabindex="0" role="button" style="padding-top:13px;padding-bottom:13px">
        <div class="row"><span class="radio"></span>
          <div class="grow">
            <div class="title"><span class="kbd">${m.key}</span><span style="margin-left:10px">${m.title}</span>${id === "everyday" ? `<span class="chip ok">${P.recommended}</span>` : ""}</div>
            <div class="methodblurb">${m.blurb}</div>
            <div class="methodpace"><svg width="16" height="16" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6.5" fill="none" stroke="#47536B" stroke-width="1.6"/><path d="M8 4.2V8l2.6 1.7" fill="none" stroke="#47536B" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg><span>${m.pace}</span></div>
          </div>
        </div>
      </div>`;
    });
    html += `<button class="linkbtn" id="adv">${P.buttons.advanced}</button></div></div>`;
    main.innerHTML = html;
    main.querySelectorAll(".card.pickable").forEach(el => {
      const pick = () => { method = el.dataset.id; draw(); };
      el.onclick = pick;
      el.onkeydown = (e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); pick(); } };
    });
    main.querySelector("#adv").onclick = () => { screen = "advanced"; draw(); };
    renderHint(P.hints.method);
    btnsL.append(btn(P.buttons.back, () => { screen = "confirm"; draw(); }));
    btnsR.append(btn(P.buttons.continue, () => { screen = "last"; tLeft = 5; startCount(); draw(); }, "primary"));
  } else if (screen === "advanced") {
    let html = `<h1 class="compact sub">${P.titles.advanced}</h1><p class="subtitle" style="margin-bottom:6px">${P.advancedLead}</p><div class="cz"><div class="czc"><div class="card hero" style="padding:12px 20px">`;
    ["everyday","extra","quick_zero"].forEach(id => {
      const m = P.methods[id];
      html += `<p class="mono advrow">${id}: nwipe --method=${m.nwipe} &nbsp;(${m.docs})</p>`;
    });
    html += `</div><p class="muted small" style="margin:14px 0 4px">${P.advancedLogLabel}<span class="mono" style="color:var(--ink)">(no wipe yet)</span></p>
      <p class="muted small">${P.advancedNote}</p></div></div>`;
    main.innerHTML = html;
    btnsL.append(btn(P.buttons.back, () => { screen = "method"; draw(); }));
    btnsR.append(btn(P.buttons.continue, () => { screen = "method"; draw(); }, "primary"));
  } else if (screen === "last") {
    if (!selected) { screen = "pick"; draw(); return; }
    const ready = tLeft <= 0;
    const CIRC = 2 * Math.PI * 81;
    const frac = ready ? 1 : Math.max(0, Math.min(1, tLeft / 5));
    const ringColor = ready ? "var(--ok)" : "var(--primary)";
    main.innerHTML = `<h1 class="sub">${P.titles.last}</h1><p class="subtitle">${P.lastLead}</p>${panel("danger", selected.eraseLabel)}
      <div class="cz"><div class="czc"><div class="ringwrap"><div style="position:relative;width:190px;height:190px">
        <svg width="190" height="190" viewBox="0 0 190 190">
          <circle cx="95" cy="95" r="81" fill="none" stroke="var(--track)" stroke-width="11"/>
          ${ready ? `<circle cx="95" cy="95" r="81" fill="none" stroke="var(--ok)" stroke-width="11"/>` :
            `<circle cx="95" cy="95" r="81" fill="none" stroke="${ringColor}" stroke-width="11" stroke-linecap="round"
              stroke-dasharray="${CIRC}" stroke-dashoffset="${CIRC * (1 - frac)}" transform="rotate(-90 95 95)"/>`}
        </svg>
        <div class="ringnum" style="${ready ? "color:var(--ok)" : ""}">${ready ? "✓" : tLeft}</div></div>
      <div class="countcap${ready ? " ready" : ""}">${ready ? P.countdownReady : P.countdownCaption}</div></div></div></div>`;
    btnsL.append(btn(P.buttons.back, () => { if (timer) clearInterval(timer); screen = "method"; draw(); }));
    btnsR.append(btn(P.buttons.erase, () => { if (tLeft<=0) startWork(); }, "danger", tLeft>0));
    renderHint(P.hints.lastChance);
  } else if (screen === "working") {
    if (!selected) { screen = "pick"; draw(); return; }
    const m = P.methods[method];
    const known = demoPct !== null;
    const pct = known ? demoPct : 0;
    main.innerHTML = `<h1>${P.titles.working}</h1>
      ${summaryCard(selected)}
      ${moreLink()}
      <div class="cz"><div class="czc">
      <div class="bigstat" id="pct" style="margin:0 0 12px">${known ? pct + "%" : ""}</div>
      <div class="bar"><div class="fill${known ? "" : " indet"}" id="fill" style="width:${Math.max(2, pct)}%"></div></div>
      <p class="muted" style="font-size:16px;margin-top:14px" id="pulse">${m.title}. &nbsp;${P.working}</p></div></div>`;
    bindMore();
    renderHint(P.hints.working);
  } else if (screen === "done") {
    if (!selected) { screen = "pick"; draw(); return; }
    const ok = !fail;
    main.innerHTML = `<div class="centerstage"><div class="status ${ok ? "ok" : "bad"}"><div class="core">${ok ? "✓" : "✕"}</div></div>
      <h1>${ok?P.titles.doneOk:P.titles.doneFail}</h1>
      <p class="statustext" style="color:var(--ink)">${ok?P.doneOk:P.doneFail}</p>
      <div style="width:100%;margin-top:24px">${summaryCard(selected)}</div>
      ${moreLink()}</div>`;
    bindMore();
    btnsL.append(btn(P.buttons.closePreview, closePreview, "secondary"));
    btnsR.append(btn(P.buttons.runAgain, () => boot(fail ? "fail" : mode), "primary"));
  }
}
function startCount() {
  if (timer) clearInterval(timer);
  timer = setInterval(() => {
    tLeft -= 1;
    if (tLeft <= 0) { tLeft = 0; clearInterval(timer); }
    if (screen === "last") draw();
  }, 1000);
}
function startWork() {
  screen = "working";
  demoPct = null;
  draw();
  let p = 0;
  if (timer) clearInterval(timer);
  timer = setInterval(() => {
    p += 8;
    demoPct = Math.min(p, 100);
    const pctEl = document.getElementById("pct");
    const fill = document.getElementById("fill");
    if (pctEl) pctEl.textContent = demoPct + "%";
    if (fill) { fill.classList.remove("indet"); fill.style.width = demoPct + "%"; }
    if (p >= 100) { clearInterval(timer); screen = "done"; draw(); }
  }, 280);
}
// Deep-link for screenshot verification, e.g.:
// #scenario=happy&s=confirm&disk=0&typed=1  ·  #s=last&ready=1  ·  #s=working&pct=42
function applyHash() {
  const q = new URLSearchParams(location.hash.slice(1));
  const scenario = q.get("scenario") || "happy";
  boot(scenario);
  const di = q.get("disk");
  if (di !== null) selected = selectable()[parseInt(di, 10)] || null;
  if (q.get("typed") === "1" && selected) token = selected.token;
  if (q.get("owner") === "1") owner = true;
  if (q.get("method")) method = q.get("method");
  if (q.get("ready") === "1") tLeft = 0;
  if (q.get("pct")) demoPct = parseInt(q.get("pct"), 10);
  const s = q.get("s");
  if (s) { screen = s; draw(); }
}
if (location.hash) applyHash(); else boot("happy");
</script>
</body>
</html>
"""
