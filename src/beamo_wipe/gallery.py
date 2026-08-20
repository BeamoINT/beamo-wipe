# SPDX-License-Identifier: GPL-3.0-or-later
"""Write a browser click-through of the wizard. Preview only — does not wipe."""

from __future__ import annotations

import json
from pathlib import Path

from beamo_wipe import copy as C
from beamo_wipe.demo import discovery_for_scenario
from beamo_wipe.methods import METHODS
from beamo_wipe.models import MethodId
from beamo_wipe.safety import confirm_spec, same_size_conflict


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _disks_payload(scenario: str = "happy") -> list[dict]:
    result = discovery_for_scenario(scenario)  # type: ignore[arg-type]
    selectable = result.selectable
    out = []
    for disk in result.disks:
        spec = None
        if not disk.is_boot:
            spec = confirm_spec(disk, selectable)
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
        "sameSizeConflict": same_size_conflict(result.selectable),
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
    return _TEMPLATE.replace("__PAYLOAD__", data)


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


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Beamo Wipe — screen preview</title>
<style>
  :root {
    --bg: #EEF1F4; --surface: #FFFFFF; --surface-alt: #F5F8FB;
    --ink: #14202E; --muted: #5B6672; --faint: #7E8894;
    --border: #D6DCE3; --border-strong: #B7C0CA;
    --navy: #0B1F3A; --navy-muted: #B9C6D8;
    --primary: #1F4B99; --primary-dark: #173A79; --primary-tint: #E9F0FA;
    --danger: #B42318; --danger-dark: #8F1B12; --danger-tint: #FCEBE8; --danger-border: #E5B0A8;
    --ok: #177245; --ok-tint: #E8F4EC; --ok-border: #B7DBC5;
    --warn: #8A5A00; --warn-bg: #FDF3D7; --warn-border: #E7D59B;
    --usb-bg: #F0ECE2; --usb-border: #D9D0BC;
    --focus: #E8A317; --disabled-bg: #E2E6EA; --disabled-fg: #7E8894; --track: #E2E6EA;
  }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; background: #D8DDE3; color: var(--ink); }
  .page { max-width: 1100px; margin: 0 auto; padding: 24px 16px 64px; }
  .note { background: var(--focus); color: var(--navy); font-weight: 700; padding: 14px 18px; margin-bottom: 16px; font-size: 17px; border-radius: 6px; }
  .note code { background: #fff7d6; padding: 2px 6px; border-radius: 4px; }
  .note a { color: var(--navy); }
  .scenarios { margin: 0 0 20px; }
  .scenarios button { font-size: 15px; font-weight: 600; margin: 0 8px 8px 0; padding: 9px 16px; background: var(--navy); color: #fff; border: 0; border-radius: 6px; cursor: pointer; }
  .scenarios button:hover { background: #16305a; }
  .shell { background: var(--bg); min-height: 700px; box-shadow: 0 12px 40px rgba(11,31,58,.22); border-radius: 8px; overflow: hidden; display: flex; flex-direction: column; }
  .preview-stripe { background: var(--focus); color: var(--navy); padding: 10px 24px; font-size: 15px; font-weight: 700; }
  .hdr { background: var(--navy); color: #fff; padding: 16px 28px; display: flex; justify-content: space-between; align-items: center; font-size: 20px; font-weight: 700; }
  .hdr span { font-size: 15px; font-weight: 400; color: var(--navy-muted); }
  .strip { display: flex; gap: 4px; height: 6px; background: var(--track); }
  .strip i { flex: 1; background: var(--track); }
  .strip i.on { background: var(--primary); }
  .body { flex: 1; padding: 26px 24px 12px; }
  .col { max-width: 940px; margin: 0 auto; }
  h1 { font-size: 30px; margin: 0 0 14px; color: var(--ink); }
  .lead { font-size: 20px; line-height: 1.45; margin: 0 0 12px; }
  .muted { color: var(--muted); }
  .small { font-size: 15px; }
  .mono { font-family: "SF Mono", Menlo, Consolas, "DejaVu Sans Mono", monospace; }
  .card { background: var(--surface); border: 3px solid var(--border); border-radius: 4px; padding: 14px 16px; margin: 10px 0; }
  .card.pickable { cursor: pointer; }
  .card.pickable:hover { background: var(--surface-alt); }
  .card.pickable:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
  .card.sel { border-color: var(--primary); background: var(--primary-tint); }
  .card.boot { background: var(--usb-bg); border-color: var(--usb-border); cursor: not-allowed; }
  .card .row { display: flex; align-items: flex-start; gap: 14px; }
  .card .grow { flex: 1; min-width: 0; }
  .card .title { font-size: 18px; font-weight: 700; }
  .card .size { font-size: 18px; font-weight: 700; white-space: nowrap; }
  .card .meta { margin-top: 5px; font-size: 15px; color: var(--muted); display: flex; flex-wrap: wrap; gap: 6px 14px; align-items: center; }
  .card .meta .mono { color: var(--ink); }
  .radio { flex: none; width: 22px; height: 22px; margin-top: 2px; border: 2px solid var(--border-strong); border-radius: 50%; position: relative; }
  .sel .radio { border-color: var(--primary); }
  .sel .radio::after { content: ""; position: absolute; inset: 4px; border-radius: 50%; background: var(--primary); }
  .chip { display: inline-block; font-size: 13px; font-weight: 700; padding: 2px 8px; border: 1px solid var(--border); background: var(--surface-alt); color: var(--muted); border-radius: 4px; vertical-align: 2px; }
  .chip.ok { color: var(--ok); background: var(--ok-tint); border-color: var(--ok-border); }
  .bootbanner { margin-top: 8px; color: var(--danger); font-weight: 700; font-size: 15px; }
  .panel { display: flex; gap: 14px; align-items: flex-start; border: 2px solid; border-radius: 4px; padding: 14px 16px; margin: 12px 0; font-size: 18px; line-height: 1.4; }
  .panel svg { flex: none; margin-top: 2px; }
  .panel.warn { background: var(--warn-bg); border-color: var(--warn-border); }
  .panel.danger { background: var(--danger-tint); border-color: var(--danger-border); }
  .panel.info { background: var(--surface-alt); border-color: var(--border); }
  .hint { max-width: 940px; margin: 0 auto; padding: 12px 24px 0; color: var(--muted); font-size: 15px; border-top: 1px solid var(--border); }
  .btnrow { max-width: 940px; margin: 0 auto; padding: 12px 24px 24px; display: flex; justify-content: space-between; gap: 12px; }
  button.btn { font-size: 19px; font-weight: 700; padding: 12px 26px; border: 0; border-radius: 4px; cursor: pointer; }
  button.btn:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
  .primary { background: var(--primary); color: #fff; }
  .primary:hover:not(:disabled) { background: var(--primary-dark); }
  .danger { background: var(--danger); color: #fff; }
  .danger:hover:not(:disabled) { background: var(--danger-dark); }
  .secondary { background: #E4E8ED; color: var(--ink); }
  .secondary:hover:not(:disabled) { background: #D3D9E0; }
  button.btn:disabled { background: var(--disabled-bg); color: var(--disabled-fg); cursor: not-allowed; }
  .linkbtn { background: none; border: 0; color: var(--primary); font-size: 15px; font-weight: 700; cursor: pointer; padding: 4px 2px; text-align: left; }
  .linkbtn:focus-visible { outline: 3px solid var(--focus); }
  input.token { font-family: "SF Mono", Menlo, Consolas, "DejaVu Sans Mono", monospace; font-size: 28px; font-weight: 700; width: 100%; padding: 12px 14px; border: 2px solid var(--border-strong); border-radius: 4px; background: var(--surface); color: var(--ink); }
  input.token:focus { outline: 3px solid var(--focus); outline-offset: 1px; border-color: var(--focus); }
  .match { font-size: 15px; margin-top: 8px; color: var(--muted); }
  .match.ok { color: var(--ok); font-weight: 600; }
  .bigstat { font-size: 54px; font-weight: 700; line-height: 1; }
  .bar { height: 32px; background: var(--track); border-radius: 3px; overflow: hidden; margin-top: 10px; }
  .fill { height: 100%; background: var(--primary); width: 2%; }
  .status { width: 96px; height: 96px; border-radius: 50%; color: #fff; font-size: 54px; font-weight: 700; display: flex; align-items: center; justify-content: center; margin: 12px 0 18px; }
  .status.ok { background: var(--ok); }
  .status.bad { background: var(--danger); }
  .ok { color: var(--ok); } .bad { color: var(--danger); }
  ul.bullets { list-style: none; margin: 0; padding: 0; background: var(--surface); border: 2px solid var(--border); border-radius: 4px; }
  ul.bullets li { font-size: 20px; line-height: 1.45; padding: 14px 20px 0 20px; }
  ul.bullets li:last-child { padding-bottom: 16px; }
  ul.bullets li::before { content: "•"; color: var(--primary); font-weight: 700; margin-right: 12px; }
  .ownercard { display: flex; gap: 16px; align-items: flex-start; background: var(--surface); border: 3px solid var(--border-strong); border-radius: 4px; padding: 18px; cursor: pointer; font-size: 20px; line-height: 1.45; }
  .ownercard:hover { background: var(--surface-alt); }
  .ownercard:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
  .ownercard.checked { border-color: var(--primary); background: var(--primary-tint); }
  .cbox { flex: none; width: 26px; height: 26px; margin-top: 2px; border: 2px solid var(--border-strong); border-radius: 3px; background: var(--surface); color: #fff; font-size: 20px; line-height: 24px; text-align: center; }
  .ownercard.checked .cbox { background: var(--primary); border-color: var(--primary); }
  .countrow { display: flex; align-items: flex-end; gap: 16px; margin-top: 20px; }
  .countrow .cap { font-size: 18px; color: var(--muted); padding-bottom: 8px; }
  .countrow .cap.ready { color: var(--ok); font-weight: 600; }
  .methodblurb, .methodpace { font-size: 15px; color: var(--muted); margin: 3px 0 0 38px; }
  .splashmark { width: 120px; height: 6px; background: var(--focus); margin: 18px 0 26px; }
  .wordmark { font-size: 40px; font-weight: 700; color: var(--navy); margin: 60px 0 0; }
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
    <div class="hdr"><div id="brand"></div><span id="step"></span></div>
    <div class="strip" id="strip"></div>
    <div class="body"><div class="col" id="main"></div></div>
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

const ICON_WARN = '<svg width="28" height="28" viewBox="0 0 24 24" fill="none"><path d="M12 3 22 20 H2 Z" fill="none" stroke="#8A5A00" stroke-width="2" stroke-linejoin="round"/><line x1="12" y1="9.5" x2="12" y2="14" stroke="#8A5A00" stroke-width="2.4" stroke-linecap="round"/><circle cx="12" cy="16.8" r="1.3" fill="#8A5A00"/></svg>';
const ICON_WARN_RED = ICON_WARN.replaceAll("#8A5A00", "#B42318");
const ICON_INFO = '<svg width="26" height="26" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9.2" stroke="#5B6672" stroke-width="2"/><circle cx="12" cy="7.8" r="1.3" fill="#5B6672"/><line x1="12" y1="11" x2="12" y2="16.4" stroke="#5B6672" stroke-width="2.4" stroke-linecap="round"/></svg>';
const ICON_NO = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9.2" stroke="#B42318" stroke-width="2.6"/><line x1="6" y1="18" x2="18" y2="6" stroke="#B42318" stroke-width="2.6" stroke-linecap="round"/></svg>';

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
  const map = {splash:[0,""], what:[1,"Step 1 of 8"], owner:[2,"Step 2 of 8"], pick:[3,"Step 3 of 8"],
    blocked:[3,"Step 3 of 8"], empty:[3,"Step 3 of 8"], confirm:[4,"Step 4 of 8"], method:[5,"Step 5 of 8"],
    advanced:[5,"Advanced"], last:[6,"Step 6 of 8"], working:[7,"Step 7 of 8"], done:[8,"Step 8 of 8"]};
  return map[screen] || [0,""];
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
function panel(kind, icon, text) {
  return `<div class="panel ${kind}">${icon}<div>${text}</div></div>`;
}
function diskCard(d) {
  const sel = selected && selected.path === d.path;
  const cls = d.isBoot ? "card boot" : ("card pickable" + (sel ? " sel" : ""));
  const icon = d.isBoot ? `<span class="radio" style="border:0">${ICON_NO}</span>` : `<span class="radio"></span>`;
  return `<div class="${cls}" data-path="${d.path}" ${d.isBoot ? "" : 'tabindex="0" role="button"'}>
    <div class="row">${icon}
      <div class="grow">
        <div class="row" style="align-items:center">
          <div class="title grow">${d.name} &nbsp;<span class="chip">${d.kind}</span></div>
          <div class="size">${d.size}</div>
        </div>
        <div class="meta"><span>${d.bus}</span><span>Serial <span class="mono">${d.serial}</span></span><span>Device <span class="mono">${d.path}</span></span></div>
        ${d.isBoot ? `<div class="bootbanner">${P.bootUsb}</div>` : ""}
      </div>
    </div>
  </div>`;
}
function draw() {
  const info = stepInfo();
  document.getElementById("step").textContent = info[1];
  const strip = document.getElementById("strip");
  strip.innerHTML = "";
  for (let i = 0; i < 8; i++) {
    const seg = document.createElement("i");
    if (i < info[0]) seg.className = "on";
    strip.append(seg);
  }
  const main = document.getElementById("main");
  const btns = document.getElementById("btns");
  const hint = document.getElementById("hint");
  main.innerHTML = "";
  btns.innerHTML = "";
  hint.textContent = P.hints.default;
  if (screen === "splash") {
    main.innerHTML = `<div class="wordmark">${P.app}</div><div class="splashmark"></div>
      <p class="lead">${P.splash}</p><p class="muted" style="font-size:18px">Press any key to continue.</p>`;
    hint.textContent = P.hints.splash;
    btns.append(btn("Continue", () => { screen = "what"; draw(); }, "primary"));
  } else if (screen === "what") {
    main.innerHTML = `<h1>What this is</h1><ul class="bullets">${P.what.map(x=>"<li>"+x+"</li>").join("")}</ul>
      <p class="muted small" style="margin-top:18px">${P.engine}</p><p class="muted small">${P.secureBoot}</p>`;
    btns.append(btn("Close preview", closePreview, "secondary"));
    btns.append(btn("I understand", () => { screen = "owner"; draw(); }, "primary"));
  } else if (screen === "owner") {
    main.innerHTML = `<h1>You must be the owner</h1>
      <p class="lead">${P.ownerLead}</p>
      <div class="ownercard${owner ? " checked" : ""}" id="own" tabindex="0" role="checkbox" aria-checked="${owner}">
        <span class="cbox">${owner ? "✓" : ""}</span><span>${P.owner}</span></div>`;
    const card = main.querySelector("#own");
    const toggle = () => { owner = !owner; draw(); };
    card.onclick = toggle;
    card.onkeydown = (e) => { if (e.key === " ") { e.preventDefault(); toggle(); } };
    btns.append(btn("Back", () => { screen = "what"; draw(); }));
    hint.textContent = P.hints.owner;
    btns.append(btn("Continue", () => { if (owner) { if (mode==="blocked") screen="blocked"; else if (!selectable().length) screen="empty"; else screen="pick"; draw(); } }, "primary", !owner));
  } else if (screen === "blocked") {
    main.innerHTML = `<div style="margin-top:34px">${ICON_WARN.replace('width="28" height="28"', 'width="72" height="72"')}</div>
      <h1 style="margin-top:16px">Stop</h1><p class="lead">${P.identify}</p>`;
    btns.append(btn("Back", () => { screen = "owner"; draw(); }));
    btns.append(btn("Close preview", closePreview, "primary"));
  } else if (screen === "empty") {
    main.innerHTML = `<div style="margin-top:34px">${ICON_INFO.replace('width="26" height="26"', 'width="64" height="64"')}</div>
      <h1 style="margin-top:16px">No disk to erase</h1><p class="lead">${P.empty}</p>`;
    btns.append(btn("Back", () => { screen = "owner"; draw(); }));
    btns.append(btn("Close preview", closePreview, "primary"));
  } else if (screen === "pick") {
    let html = `<h1>Pick a disk</h1><p class="muted" style="font-size:18px;margin-top:-6px">${P.pickSubtitle}</p>`;
    if (P.sameSizeConflict && mode === "happy") html += panel("warn", ICON_WARN, P.sameSize);
    if (selected && (selected.kind === "SSD" || selected.kind === "NVMe")) html += panel("info", ICON_INFO, P.ssd);
    disks().forEach(d => { html += diskCard(d); });
    main.innerHTML = html;
    main.querySelectorAll(".card.pickable").forEach(el => {
      const pick = () => { selected = disks().find(d => d.path === el.dataset.path); draw(); };
      el.onclick = pick;
      el.onkeydown = (e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); pick(); } };
    });
    hint.textContent = P.hints.pick;
    btns.append(btn("Back", () => { screen = "owner"; draw(); }));
    btns.append(btn("Continue", () => { if (selected && !selected.isBoot) { screen = "confirm"; token=""; draw(); } }, "primary", !(selected && !selected.isBoot)));
  } else if (screen === "confirm") {
    const d = selected;
    main.innerHTML = `<h1>Confirm the disk</h1>
      <div class="card"><div class="row" style="align-items:center">
        <div class="title grow">${d.name}</div><div class="size">${d.size}</div></div>
        <div class="meta"><span class="chip">${d.kind}</span><span>Serial <span class="mono">${d.serial}</span></span><span>Device <span class="mono">${d.path}</span></span></div>
      </div>
      ${panel("warn", ICON_WARN, d.warning)}
      <p class="lead">${d.prompt}</p>
      <p><input class="token" id="tok" autocomplete="off" spellcheck="false"></p>
      <p class="match" id="match"></p>`;
    const inp = main.querySelector("#tok");
    const matchEl = main.querySelector("#match");
    inp.value = token;
    const sync = () => {
      token = inp.value;
      const cont = document.getElementById("cont");
      if (cont) cont.disabled = !tokenOk();
      if (tokenOk()) { matchEl.textContent = P.matchOk; matchEl.className = "match ok"; }
      else { matchEl.textContent = P.matchWait; matchEl.className = "match"; }
    };
    inp.oninput = sync;
    sync();
    setTimeout(() => { inp.focus(); inp.setSelectionRange(token.length, token.length); }, 0);
    hint.textContent = P.hints.confirm;
    btns.append(btn("Back", () => { screen = "pick"; draw(); }));
    const cont = btn("Continue", () => { if (tokenOk()) { screen = "method"; draw(); } }, "primary", !tokenOk());
    cont.id = "cont";
    btns.append(cont);
  } else if (screen === "method") {
    let html = `<h1>How thorough</h1>`;
    ["everyday","extra","quick_zero"].forEach(id => {
      const m = P.methods[id];
      const sel = method === id;
      html += `<div class="card pickable${sel ? " sel" : ""}" data-id="${id}" tabindex="0" role="button">
        <div class="row"><span class="radio"></span>
          <div class="grow">
            <div class="title"><span class="chip">${m.key}</span> &nbsp;${m.title}${id === "everyday" ? ` &nbsp;<span class="chip ok">${P.recommended}</span>` : ""}</div>
            <div class="methodblurb">${m.blurb}</div>
            <div class="methodpace">${m.pace}</div>
          </div>
        </div>
      </div>`;
    });
    html += panel("info", ICON_INFO, P.ssd);
    html += `<button class="linkbtn" id="adv">Advanced (technicians)</button>`;
    main.innerHTML = html;
    main.querySelectorAll(".card.pickable").forEach(el => {
      const pick = () => { method = el.dataset.id; draw(); };
      el.onclick = pick;
      el.onkeydown = (e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); pick(); } };
    });
    main.querySelector("#adv").onclick = () => { screen = "advanced"; draw(); };
    hint.textContent = P.hints.method;
    btns.append(btn("Back", () => { screen = "confirm"; draw(); }));
    btns.append(btn("Continue", () => { screen = "last"; tLeft = 5; startCount(); draw(); }, "primary"));
  } else if (screen === "advanced") {
    let html = `<h1>Advanced</h1><p class="muted" style="font-size:18px">${P.advancedLead}</p><div class="card">`;
    ["everyday","extra","quick_zero"].forEach(id => {
      const m = P.methods[id];
      html += `<p class="mono" style="font-size:14px;margin:6px 0">${id}: nwipe --method=${m.nwipe} &nbsp;(${m.docs})</p>`;
    });
    html += `</div><p class="muted small">Log file (never on the target disk): <span class="mono">(no wipe yet)</span></p>
      <p class="muted small">${P.advancedNote}</p>`;
    main.innerHTML = html;
    btns.append(btn("Back", () => { screen = "method"; draw(); }));
    btns.append(btn("Continue", () => { screen = "method"; draw(); }, "primary"));
  } else if (screen === "last") {
    const ready = tLeft <= 0;
    main.innerHTML = `<h1>Last chance</h1>${panel("danger", ICON_WARN_RED, selected.eraseLabel)}
      <div class="countrow"><span class="bigstat" style="${ready ? "color:var(--ok)" : ""}">${ready ? "✓" : tLeft}</span>
      <span class="cap${ready ? " ready" : ""}">${ready ? P.countdownReady : P.countdownCaption}</span></div>`;
    btns.append(btn("Back", () => { if (timer) clearInterval(timer); screen = "method"; draw(); }));
    btns.append(btn("Erase now", () => { if (tLeft<=0) startWork(); }, "danger", tLeft>0));
  } else if (screen === "working") {
    const m = P.methods[method];
    const pct = demoPct === null ? 0 : demoPct;
    main.innerHTML = `<h1>Working</h1>
      <div class="card"><div class="title">${selected.name} &nbsp; ${selected.size}</div>
      <div class="meta"><span class="mono">${selected.path}</span></div></div>
      <div class="bigstat" id="pct" style="margin-top:24px">${pct}%</div>
      <div class="bar"><div class="fill" id="fill" style="width:${Math.max(2, pct)}%"></div></div>
      <p class="muted" style="font-size:18px;margin-top:14px" id="pulse">${m.title}. &nbsp;${P.working}</p>`;
    hint.textContent = P.hints.working;
  } else if (screen === "done") {
    const ok = !fail;
    main.innerHTML = `<div class="status ${ok ? "ok" : "bad"}" style="margin-top:26px">${ok ? "✓" : "✕"}</div>
      <h1>${ok?"Finished":"The wipe did not finish"}</h1>
      <p class="lead ${ok?"ok":"bad"}">${ok?P.doneOk:P.doneFail}</p>
      <p class="muted" style="font-size:18px">${selected.name} &nbsp; ${selected.size}</p>`;
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
    const pctEl = document.getElementById("pct");
    const fill = document.getElementById("fill");
    if (pctEl) pctEl.textContent = Math.min(p,100) + "%";
    if (fill) fill.style.width = Math.min(p,100) + "%";
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
