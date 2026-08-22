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
    """The real Beamo mark as a one-line inline SVG sized for the template."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="128 162 264 221" aria-hidden="true">{_mark_body()}</svg>'
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
        "what": list(C.WHAT_BULLETS),
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
        "recommended": C.RECOMMENDED_TAG,
        "matchWait": C.CONFIRM_MATCH_WAIT,
        "matchOk": C.CONFIRM_MATCH_OK,
        "countdownCaption": C.COUNTDOWN_CAPTION,
        "countdownReady": C.COUNTDOWN_READY,
        "advancedLead": C.ADVANCED_LEAD,
        "advancedNote": C.ADVANCED_LOG_NOTE,
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
    data = json.dumps(payload)
    return (
        _TEMPLATE
        .replace("__PAYLOAD__", data)
        .replace("__LOGO_HEADER__", _logo_svg(36, 30))
        .replace("__LOGO_SPLASH__", _logo_svg(139, 116))
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
    --bg: #EDF0F7; --surface: #FFFFFF; --surface-alt: #F4F6FB;
    --ink: #0C1728; --muted: #47536B;
    --border: #DCE2EC; --border-strong: #74839F;
    --navy: #0A1B34; --navy-soft: #16315C; --navy-muted: #C9D6E8; --navy-text: #DAE3F1;
    --navy-deep: #071426; --navy-glow: #1C3A6E;
    --primary: #1D4ED8; --primary-dark: #1A41B8; --primary-press: #16337F; --primary-tint: #E9EFFC;
    --danger: #B3261E; --danger-dark: #8E1D16; --danger-press: #6E1510; --danger-tint: #FBEBE9; --danger-border: #E6A79E;
    --ok: #17703F; --ok-tint: #E7F2EB;
    --warn: #7A5200; --warn-bg: #FBF1D5; --warn-border: #E3CE96;
    --usb-bg: #F4EFE3; --usb-border: #D9CEB5;
    --focus: #1A3FA0; --accent: #E8A317;
    --disabled-bg: #E4E8EF; --disabled-fg: #6E7989; --track: #DFE5EF;
    /* One quiet shadow layer, mirroring the single offset rect in _Box. */
    --shadow: 0 4px 0 0 #D7DEEB;
    /* Single-ring selection halo, mirroring _Box(halo=True). */
    --halo: 0 0 0 3px rgba(29,78,216,.18);
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
  .preview-stripe { background: var(--accent); color: var(--navy); padding: 10px 28px; font-size: 16px; font-weight: 700; }
  .hdr { background: var(--navy); border-bottom: 1px solid var(--navy-soft); color: #fff; height: 66px; padding: 0 28px; display: flex; justify-content: space-between; align-items: center; }
  .brandrow { display: flex; align-items: center; gap: 14px; font-size: 21px; font-weight: 700; }
  .brandrow svg { flex: none; display: block; }
  .steppill { font-size: 14px; font-weight: 700; color: var(--navy-muted); background: var(--navy-soft); border: 1px solid #2A4A7E; border-radius: 999px; padding: 7px 14px; white-space: nowrap; }
  .strip { height: 6px; background: var(--track); }
  .strip .sfill { height: 100%; background: var(--primary); width: 0; transition: width .25s ease; border-radius: 0 3px 3px 0; }
  .body { flex: 1; padding: 26px 24px 12px; }
  .body.navy { background: radial-gradient(ellipse 72% 82% at 50% 40%, var(--navy-glow), var(--navy-deep)); }
  .col { max-width: 940px; margin: 0 auto; }
  h1 { font-size: 34px; margin: 0 0 14px; color: var(--ink); letter-spacing: -.01em; }
  .lead { font-size: 20px; line-height: 1.45; margin: 0 0 12px; }
  .muted { color: var(--muted); }
  .small { font-size: 16px; }
  .mono { font-family: "SF Mono", Menlo, Consolas, "DejaVu Sans Mono", monospace; }
  .kbd { display: inline-block; background: var(--surface); border: 1px solid var(--border-strong); border-radius: 7px; padding: 2px 9px; font-size: 14px; font-weight: 700; color: var(--ink); line-height: 1.3; }
  .kbd.dark { background: var(--navy-soft); border-color: #33517F; color: var(--navy-text); }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 18px 20px; margin: 0 4px 12px; }
  .card.hero { box-shadow: var(--shadow); margin-left: 0; margin-right: 0; }
  .card.pickable { cursor: pointer; }
  .card.pickable:hover { background: var(--surface-alt); }
  .card.pickable:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
  .card.sel { border: 2px solid var(--primary); background: var(--primary-tint); padding: 17px 19px; box-shadow: var(--halo); }
  .card.sel:hover { background: var(--primary-tint); }
  .card.boot { background: var(--usb-bg); border-color: var(--usb-border); cursor: not-allowed; }
  .card .row { display: flex; align-items: flex-start; gap: 16px; }
  .card .grow { flex: 1; min-width: 0; }
  .card .title { font-size: 18px; font-weight: 700; }
  .card .size { font-size: 22px; font-weight: 700; white-space: nowrap; }
  .card .meta { margin-top: 6px; font-size: 16px; color: var(--muted); display: flex; flex-wrap: wrap; gap: 4px 0; align-items: center; }
  .card .meta .mono { color: var(--ink); font-size: 16px; }
  .card .meta .mono.ser { font-weight: 700; }
  .card .meta .dot { color: var(--border-strong); margin: 0 8px; }
  .card .meta .dev { color: var(--muted); }
  .radio { flex: none; width: 26px; height: 26px; margin-top: 1px; border: 2px solid var(--border-strong); border-radius: 50%; position: relative; background: var(--surface); }
  .sel .radio { border-color: var(--primary); }
  .sel .radio::after { content: ""; position: absolute; inset: 5px; border-radius: 50%; background: var(--primary); }
  .chip { display: inline-block; font-size: 14px; font-weight: 700; padding: 3px 12px; background: var(--surface-alt); color: var(--muted); border-radius: 999px; vertical-align: 2px; }
  .chip.ok { color: var(--ok); background: var(--ok-tint); }
  .bootbanner { display: inline-block; margin-top: 10px; margin-left: 42px; color: var(--danger); font-weight: 700; font-size: 16px; background: var(--danger-tint); border: 1px solid var(--danger-border); border-radius: 999px; padding: 4px 12px; }
  .panel { display: flex; gap: 16px; align-items: flex-start; border: 1px solid; border-radius: 14px; padding: 16px 18px; margin: 12px 0; font-size: 18px; line-height: 1.4; }
  .panel svg { flex: none; margin-top: 2px; }
  .panel.warn { background: var(--warn-bg); border-color: var(--warn-border); }
  .panel.danger { background: var(--danger-tint); border-color: var(--danger-border); }
  .panel.info { background: var(--surface-alt); border-color: var(--border); }
  .hint { max-width: 940px; margin: 0 auto; padding: 14px 24px 0; color: var(--muted); font-size: 16px; border-top: 1px solid var(--border); line-height: 2; }
  .hint .kbd { margin: 0 1px; }
  .btnrow { max-width: 940px; margin: 0 auto; padding: 14px 24px 22px; display: flex; justify-content: space-between; gap: 12px; }
  button.btn { font-size: 20px; font-weight: 700; padding: 15px 28px; border: 0; border-radius: 999px; cursor: pointer; min-width: 124px; }
  button.btn:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
  .primary { background: var(--primary); color: #fff; min-width: 172px; }
  .primary:hover:not(:disabled) { background: var(--primary-dark); }
  .primary:active:not(:disabled) { background: var(--primary-press); }
  .danger { background: var(--danger); color: #fff; min-width: 172px; }
  .danger:hover:not(:disabled) { background: var(--danger-dark); }
  .danger:active:not(:disabled) { background: var(--danger-press); }
  .secondary { background: var(--surface); color: var(--ink); border: 1px solid var(--border-strong); }
  .secondary:hover:not(:disabled) { background: var(--surface-alt); }
  .secondary:active:not(:disabled) { background: #E6EAF0; }
  button.btn:disabled { background: var(--disabled-bg); color: var(--disabled-fg); border-color: transparent; box-shadow: none; cursor: not-allowed; }
  .linkbtn { background: none; border: 0; color: var(--primary); font-size: 16px; font-weight: 700; cursor: pointer; padding: 8px 12px; text-align: left; border-radius: 10px; margin-left: -12px; }
  .linkbtn:hover { background: var(--primary-tint); }
  .linkbtn:focus-visible { outline: 3px solid var(--focus); }
  .entryshell { background: var(--surface); border: 1px solid var(--border-strong); border-radius: 14px; padding: 12px 18px; box-shadow: var(--shadow); }
  .entryshell:focus-within { outline: 3px solid var(--focus); outline-offset: 2px; border-color: var(--focus); }
  input.token { font-family: "SF Mono", Menlo, Consolas, "DejaVu Sans Mono", monospace; font-size: 30px; font-weight: 700; width: 100%; padding: 6px 0; border: 0; outline: none; background: transparent; color: var(--ink); }
  .match { display: inline-flex; align-items: center; gap: 10px; font-size: 16px; font-weight: 700; margin: 16px 0 0; color: var(--muted); background: var(--surface-alt); border: 1px solid var(--border-strong); border-radius: 999px; padding: 8px 14px; }
  .match.ok { color: var(--ok); background: var(--ok-tint); border-color: var(--ok); }
  .bigstat { font-size: 64px; font-weight: 700; line-height: 1.05; letter-spacing: -.01em; min-height: 70px; }
  .bar { height: 26px; background: var(--track); border-radius: 13px; overflow: hidden; margin-top: 10px; }
  .fill { height: 100%; background: var(--primary); width: 2%; border-radius: 13px; transition: width .2s ease; }
  .fill.indet { width: 30%; animation: slide 1.7s ease-in-out infinite alternate; }
  @keyframes slide { from { margin-left: 0; } to { margin-left: 70%; } }
  .status { width: 104px; height: 104px; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto 24px; }
  .status.ok { background: var(--ok-tint); }
  .status.bad { background: var(--danger-tint); }
  .status .core { width: 78px; height: 78px; border-radius: 50%; color: #fff; font-size: 44px; font-weight: 700; display: flex; align-items: center; justify-content: center; }
  .status.ok .core { background: var(--ok); }
  .status.bad .core { background: var(--danger); }
  .badgehalo { width: 96px; height: 96px; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto; }
  .badgehalo.warn { background: var(--warn-bg); }
  .badgehalo.danger { background: var(--danger-tint); }
  .badgehalo.info { background: var(--surface-alt); }
  .ok { color: var(--ok); } .bad { color: var(--danger); }
  ul.bullets { list-style: none; margin: 0; padding: 20px 22px; background: var(--surface); border: 1px solid var(--border); border-radius: 16px; box-shadow: var(--shadow); }
  ul.bullets li { font-size: 20px; line-height: 1.45; padding: 8px 0; display: flex; }
  ul.bullets li::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: var(--primary); margin: 11px 14px 0 2px; flex: none; }
  .ownercard { display: flex; gap: 18px; align-items: flex-start; background: var(--surface); border: 1px solid var(--border-strong); border-radius: 16px; padding: 22px; cursor: pointer; font-size: 20px; line-height: 1.45; }
  .ownercard:hover { background: var(--surface-alt); }
  .ownercard:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
  .ownercard.checked { border: 2px solid var(--primary); background: var(--primary-tint); padding: 21px; box-shadow: var(--halo); }
  .ownercard.checked:hover { background: var(--primary-tint); }
  .cbox { flex: none; width: 32px; height: 32px; margin-top: 1px; border: 2px solid var(--border-strong); border-radius: 8px; background: var(--surface); color: #fff; font-size: 22px; font-weight: 700; line-height: 28px; text-align: center; }
  .ownercard.checked .cbox { background: var(--primary); border-color: var(--primary); }
  .ringwrap { display: flex; flex-direction: column; align-items: center; margin-top: 26px; }
  .ringnum { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; font-size: 64px; font-weight: 700; }
  .countcap { font-size: 18px; color: var(--muted); margin-top: 12px; }
  .countcap.ready { color: var(--ok); font-weight: 600; }
  .advrow { font-size: 15px; margin: 0; padding: 10px 0; }
  .advrow + .advrow { border-top: 1px solid var(--border); }
  .methodblurb { font-size: 16px; color: var(--muted); margin: 4px 16px 0 58px; }
  .methodpace { font-size: 16px; color: var(--muted); margin: 4px 16px 0 58px; display: flex; gap: 8px; align-items: flex-start; }
  .methodpace svg { flex: none; margin-top: 2px; }
  .centerstage { min-height: 340px; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; }
  .centerstage h1 { margin: 26px 0 12px; }
  .centerstage .lead { max-width: 760px; }
  .splashwrap { min-height: 560px; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; }
  .emblemwrap { position: relative; width: 176px; height: 176px; display: flex; align-items: center; justify-content: center; }
  .emblemwrap::before { content: ""; position: absolute; inset: 0; border-radius: 50%; background: radial-gradient(circle, rgba(232,163,23,.20), rgba(232,163,23,.07) 55%, transparent 72%); }
  .wordmark { font-size: 54px; font-weight: 700; color: #fff; letter-spacing: -.01em; margin-top: 40px; }
  .anykey { margin-top: 46px; font-size: 18px; color: var(--navy-text); display: flex; align-items: center; gap: 8px; }
  .body.navy h1, .body.navy .lead { color: #fff; }
  .body.navy .muted { color: var(--navy-muted); }
  .disklist { max-height: 372px; overflow-y: auto; scrollbar-width: thin; scrollbar-color: #A3AEC2 transparent; }
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
    <div class="hdr"><div class="brandrow">__LOGO_HEADER__<div id="brand"></div></div><span class="steppill" id="step"></span></div>
    <div class="strip"><div class="sfill" id="sfill"></div></div>
    <div class="body" id="body"><div class="col" id="main"></div></div>
    <div class="hint" id="hint"></div>
    <div class="btnrow" id="btns"></div>
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
const ICON_NO = '<svg width="26" height="26" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9.2" stroke="#B3261E" stroke-width="2.6"/><line x1="6" y1="18" x2="18" y2="6" stroke="#B3261E" stroke-width="2.6" stroke-linecap="round"/></svg>';
const MATCH_WAIT = '<svg width="26" height="26" viewBox="0 0 26 26"><circle cx="13" cy="13" r="11" fill="none" stroke="#74839F" stroke-width="2"/></svg>';
const MATCH_OK = '<svg width="26" height="26" viewBox="0 0 26 26"><circle cx="13" cy="13" r="12" fill="#17703F"/><path d="M7 13.5 11 17.5 19 8.5" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>';
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
  const map = {splash:[0,"",""], what:[1,"Step 1 of 8","What this is"], owner:[2,"Step 2 of 8","Ownership"],
    pick:[3,"Step 3 of 8","Pick a disk"], blocked:[3,"Step 3 of 8","Pick a disk"], empty:[3,"Step 3 of 8","Pick a disk"],
    confirm:[4,"Step 4 of 8","Confirm the disk"], method:[5,"Step 5 of 8","How thorough"],
    advanced:[5,"Advanced","Advanced"], last:[6,"Step 6 of 8","Last chance"],
    working:[7,"Step 7 of 8","Erasing"], done:[8,"Step 8 of 8","Finished"]};
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
  return `<div class="panel ${kind}">${badge(kind, 34)}<div>${text}</div></div>`;
}
function metaLine(d) {
  return `<div class="meta"><span>${d.bus}</span><span class="dot">·</span><span>Serial <span class="mono ser">${d.serial}</span></span><span class="dot">·</span><span>Device <span class="mono dev">${d.path}</span></span></div>`;
}
function summaryCard(d) {
  return `<div class="card hero" style="padding:18px 20px"><div class="row" style="align-items:center">
    <div class="title grow">${d.name} &nbsp;<span class="chip">${d.kind}</span></div>
    <div class="size">${d.size}</div></div>
    ${metaLine(d)}
  </div>`;
}
function diskCard(d) {
  const sel = selected && selected.path === d.path;
  const cls = d.isBoot ? "card boot" : ("card pickable" + (sel ? " sel" : ""));
  const icon = d.isBoot ? `<span class="radio" style="border:0;background:none">${ICON_NO}</span>` : `<span class="radio"></span>`;
  return `<div class="${cls}" data-path="${d.path}" ${d.isBoot ? "" : 'tabindex="0" role="button"'}>
    <div class="row">${icon}
      <div class="grow">
        <div class="row" style="align-items:center">
          <div class="title grow">${d.name} &nbsp;<span class="chip">${d.kind}</span></div>
          <div class="size">${d.size}</div>
        </div>
        ${metaLine(d)}
        ${d.isBoot ? `<div class="bootbanner">${P.bootUsb}</div>` : ""}
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
  document.getElementById("body").className = screen === "splash" ? "body navy" : "body";
  const main = document.getElementById("main");
  const btns = document.getElementById("btns");
  main.innerHTML = "";
  btns.innerHTML = "";
  renderHint(P.hints.default);
  if (screen === "splash") {
    main.innerHTML = `<div class="splashwrap"><div class="emblemwrap">${EMBLEM}</div><div class="wordmark">${P.app}</div>
      <p class="lead" style="color:var(--navy-text);max-width:760px;margin-top:22px">${P.splash}</p>
      <div class="anykey"><span class="kbd dark">any key</span><span>to continue.</span></div></div>`;
    renderHint(P.hints.splash);
    btns.append(btn("Continue", () => { screen = "what"; draw(); }, "primary"));
  } else if (screen === "what") {
    main.innerHTML = `<h1>What this is</h1><ul class="bullets">${P.what.map(x=>"<li>"+x+"</li>").join("")}</ul>
      <div class="panel info" style="margin-top:16px">${badge("info", 26)}<div>
      <div class="small muted">${P.engine}</div><div class="small muted" style="margin-top:8px">${P.secureBoot}</div></div></div>`;
    btns.append(btn("Close preview", closePreview, "secondary"));
    btns.append(btn("I understand", () => { screen = "owner"; draw(); }, "primary"));
  } else if (screen === "owner") {
    main.innerHTML = `<h1 style="margin-bottom:6px">You must be the owner</h1>
      <p class="lead muted" style="font-size:18px;margin:0 0 14px">${P.ownerLead}</p>
      <div class="ownercard${owner ? " checked" : ""}" id="own" tabindex="0" role="checkbox" aria-checked="${owner}">
        <span class="cbox">${owner ? "✓" : ""}</span><span>${P.owner}</span></div>`;
    const card = main.querySelector("#own");
    const toggle = () => { owner = !owner; draw(); };
    card.onclick = toggle;
    card.onkeydown = (e) => { if (e.key === " ") { e.preventDefault(); toggle(); } };
    btns.append(btn("Back", () => { screen = "what"; draw(); }));
    renderHint(P.hints.owner);
    btns.append(btn("Continue", () => { if (owner) { if (mode==="blocked") screen="blocked"; else if (!selectable().length) screen="empty"; else screen="pick"; draw(); } }, "primary", !owner));
  } else if (screen === "blocked") {
    main.innerHTML = `<div class="centerstage"><div class="badgehalo warn">${badge("warn", 56)}</div>
      <h1>Stop</h1><p class="lead">${P.identify}</p></div>`;
    btns.append(btn("Back", () => { screen = "owner"; draw(); }));
    btns.append(btn("Close preview", closePreview, "primary"));
  } else if (screen === "empty") {
    main.innerHTML = `<div class="centerstage"><div class="badgehalo info">${badge("info", 56)}</div>
      <h1>No disk to erase</h1><p class="lead">${P.empty}</p></div>`;
    btns.append(btn("Back", () => { screen = "owner"; draw(); }));
    btns.append(btn("Close preview", closePreview, "primary"));
  } else if (screen === "pick") {
    let html = `<h1 style="margin-bottom:6px">Pick a disk</h1><p class="muted" style="font-size:18px;margin:0 0 14px">${P.pickSubtitle}</p>`;
    if (P.sameSizeConflict && mode === "happy") html += panel("warn", P.sameSize);
    if (selected && (selected.kind === "SSD" || selected.kind === "NVMe")) html += panel("info", P.ssd);
    html += `<div class="disklist">`;
    disks().forEach(d => { html += diskCard(d); });
    html += `</div>`;
    main.innerHTML = html;
    main.querySelectorAll(".card.pickable").forEach(el => {
      const pick = () => { selected = disks().find(d => d.path === el.dataset.path); draw(); };
      el.onclick = pick;
      el.onkeydown = (e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); pick(); } };
    });
    renderHint(P.hints.pick);
    btns.append(btn("Back", () => { screen = "owner"; draw(); }));
    btns.append(btn("Continue", () => { if (selected && !selected.isBoot) { screen = "confirm"; token=""; draw(); } }, "primary", !(selected && !selected.isBoot)));
  } else if (screen === "confirm") {
    const d = selected;
    main.innerHTML = `<h1>Confirm the disk</h1>
      ${summaryCard(d)}
      ${panel("warn", d.warning)}
      <p class="lead" style="margin:2px 0 10px">${d.prompt}</p>
      <div class="entryshell"><input class="token" id="tok" autocomplete="off" spellcheck="false"></div>
      <p class="match" id="match"></p>`;
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
    btns.append(btn("Back", () => { screen = "pick"; draw(); }));
    const cont = btn("Continue", () => { if (tokenOk()) { screen = "method"; draw(); } }, "primary", !tokenOk());
    cont.id = "cont";
    btns.append(cont);
  } else if (screen === "method") {
    let html = `<h1 style="margin-bottom:8px">How thorough</h1>`;
    ["everyday","extra","quick_zero"].forEach(id => {
      const m = P.methods[id];
      const sel = method === id;
      html += `<div class="card pickable${sel ? " sel" : ""}" data-id="${id}" tabindex="0" role="button" style="padding-top:12px;padding-bottom:12px">
        <div class="row"><span class="radio"></span>
          <div class="grow">
            <div class="title"><span class="kbd">${m.key}</span>&nbsp; ${m.title}${id === "everyday" ? ` &nbsp;<span class="chip ok">${P.recommended}</span>` : ""}</div>
            <div class="methodblurb">${m.blurb}</div>
            <div class="methodpace"><svg width="18" height="18" viewBox="0 0 18 18"><circle cx="9" cy="9" r="7.5" fill="none" stroke="#47536B" stroke-width="1.6"/><path d="M9 4.6V9l3.1 2" fill="none" stroke="#47536B" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg><span>${m.pace}</span></div>
          </div>
        </div>
      </div>`;
    });
    html += panel("info", P.ssd);
    html += `<button class="linkbtn" id="adv">Advanced (technicians)</button>`;
    main.innerHTML = html;
    main.querySelectorAll(".card.pickable").forEach(el => {
      const pick = () => { method = el.dataset.id; draw(); };
      el.onclick = pick;
      el.onkeydown = (e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); pick(); } };
    });
    main.querySelector("#adv").onclick = () => { screen = "advanced"; draw(); };
    renderHint(P.hints.method);
    btns.append(btn("Back", () => { screen = "confirm"; draw(); }));
    btns.append(btn("Continue", () => { screen = "last"; tLeft = 5; startCount(); draw(); }, "primary"));
  } else if (screen === "advanced") {
    let html = `<h1 style="margin-bottom:6px">Advanced</h1><p class="muted" style="font-size:18px;margin:0 0 14px">${P.advancedLead}</p><div class="card hero" style="padding:10px 20px">`;
    ["everyday","extra","quick_zero"].forEach(id => {
      const m = P.methods[id];
      html += `<p class="mono advrow">${id}: nwipe --method=${m.nwipe} &nbsp;(${m.docs})</p>`;
    });
    html += `</div><p class="muted small" style="margin-top:18px">Log file (never on the target disk): <span class="mono">(no wipe yet)</span></p>
      <p class="muted small">${P.advancedNote}</p>`;
    main.innerHTML = html;
    btns.append(btn("Back", () => { screen = "method"; draw(); }));
    btns.append(btn("Continue", () => { screen = "method"; draw(); }, "primary"));
  } else if (screen === "last") {
    if (!selected) { screen = "pick"; draw(); return; }
    const ready = tLeft <= 0;
    const CIRC = 2 * Math.PI * 85;
    const frac = ready ? 1 : Math.max(0, Math.min(1, tLeft / 5));
    const ringColor = ready ? "var(--ok)" : "var(--primary)";
    main.innerHTML = `<h1>Last chance</h1>${panel("danger", selected.eraseLabel)}
      <div class="ringwrap"><div style="position:relative;width:200px;height:200px">
        <svg width="200" height="200" viewBox="0 0 200 200">
          <circle cx="100" cy="100" r="85" fill="none" stroke="var(--track)" stroke-width="13"/>
          ${ready ? `<circle cx="100" cy="100" r="85" fill="none" stroke="var(--ok)" stroke-width="13"/>` :
            `<circle cx="100" cy="100" r="85" fill="none" stroke="${ringColor}" stroke-width="13" stroke-linecap="round"
              stroke-dasharray="${CIRC}" stroke-dashoffset="${CIRC * (1 - frac)}" transform="rotate(-90 100 100)"/>`}
        </svg>
        <div class="ringnum" style="${ready ? "color:var(--ok)" : ""}">${ready ? "✓" : tLeft}</div></div>
      <div class="countcap${ready ? " ready" : ""}">${ready ? P.countdownReady : P.countdownCaption}</div></div>`;
    btns.append(btn("Back", () => { if (timer) clearInterval(timer); screen = "method"; draw(); }));
    btns.append(btn("Erase now", () => { if (tLeft<=0) startWork(); }, "danger", tLeft>0));
    renderHint(P.hints.lastChance);
  } else if (screen === "working") {
    if (!selected) { screen = "pick"; draw(); return; }
    const m = P.methods[method];
    const known = demoPct !== null;
    const pct = known ? demoPct : 0;
    main.innerHTML = `<h1>Working</h1>
      ${summaryCard(selected)}
      <div class="bigstat" id="pct" style="margin:30px 0 12px">${known ? pct + "%" : ""}</div>
      <div class="bar" style="margin-top:0"><div class="fill${known ? "" : " indet"}" id="fill" style="width:${Math.max(2, pct)}%"></div></div>
      <p class="muted" style="font-size:18px;margin-top:18px" id="pulse">${m.title}. &nbsp;${P.working}</p>`;
    renderHint(P.hints.working);
  } else if (screen === "done") {
    if (!selected) { screen = "pick"; draw(); return; }
    const ok = !fail;
    main.innerHTML = `<div class="centerstage"><div class="status ${ok ? "ok" : "bad"}"><div class="core">${ok ? "✓" : "✕"}</div></div>
      <h1 style="margin-top:2px">${ok?"Finished":"The wipe did not finish"}</h1>
      <p class="lead ${ok?"ok":"bad"}">${ok?P.doneOk:P.doneFail}</p>
      <div style="width:100%;margin-top:10px">${summaryCard(selected)}</div></div>`;
    btns.append(btn("Close preview", closePreview, "secondary"));
    btns.append(btn("Run again", () => boot(fail ? "fail" : mode), "primary"));
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
