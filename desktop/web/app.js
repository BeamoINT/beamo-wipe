"use strict";
const $ = id => document.getElementById(id);
let token = location.hash.slice(1);
try {
  token = token || sessionStorage.getItem("beamo-session") || "";
  if (/^[a-f0-9]{64}$/.test(token)) sessionStorage.setItem("beamo-session", token);
} catch (_) { /* A restricted browser can still use the initial fragment. */ }
history.replaceState(null, "", "/");
let busy = false;
let ready = false;
function clearChecks(message) {
  ready = false;
  $("saved").checked = false; $("restart").disabled = true; $("confirm").hidden = true;
  $("checks").replaceChildren();
  const item = document.createElement("li"); item.textContent = message; $("checks").append(item);
  $("technical").hidden = true; $("technical-detail").textContent = "";
}
async function api(action, confirm = false) {
  let response;
  try {
    response = await fetch(`/api/${action}`, {method:"POST", headers:{"Content-Type":"application/json","X-Beamo-Token":token}, body:JSON.stringify({confirm}), cache:"no-store", credentials:"omit", redirect:"error"});
  } catch (_) { throw new Error("The launcher is no longer connected. Open Start Beamo Wipe from the USB again."); }
  if (!response.ok) throw new Error(response.status === 403 ? "This session has ended. Open Start Beamo Wipe from the USB again." : await response.text());
  return response.json();
}
function show(v) {
  if (!v || typeof v.ready !== "boolean" || !Array.isArray(v.checks) || v.checks.length !== 3 ||
      v.checks.some((c, i) => !c || c.id !== ["usb", "settings", "route"][i] ||
        !["pass", "fail", "unverified", "unsupported", "blocked"].includes(c.state) ||
        [c.label, c.detail, c.next].some(text => typeof text !== "string" || !text)) ||
      typeof v.technical !== "string" || !v.technical ||
      typeof v.identity_label !== "string" || !v.identity_label ||
      typeof v.build_status !== "string" || !v.build_status ||
      typeof v.version !== "string" || !v.version ||
      typeof v.build_id !== "string" || typeof v.source_commit !== "string" ||
      typeof v.manufactured !== "boolean" ||
      (v.ready && v.checks.some(c => c.state !== "pass"))) {
    throw new Error("The readiness results were incomplete. Choose Check again or reopen the launcher from the USB.");
  }
  ready = v.ready;
  $("checks").replaceChildren();
  for (const check of v.checks) {
    const item = document.createElement("li");
    const label = document.createElement("h3"); label.textContent = check.label;
    const detail = document.createElement("p"); detail.textContent = check.detail;
    const next = document.createElement("p"); next.className = "muted"; next.textContent = check.next;
    item.append(label, detail, next); $("checks").append(item);
  }
  $("technical-detail").textContent = v.technical; $("technical").hidden = false;
  $("saved").checked=false; $("restart").disabled=true;
  $("preview").hidden = !v.preview;
  $("title").textContent = v.title; $("detail").textContent = v.detail;
  const buildId = v.build_id || "not packaged";
  const commit = v.source_commit || "not packaged";
  $("identity-label").textContent = v.identity_label;
  $("identity-version").textContent = v.version;
  $("identity-build-id").textContent = buildId;
  $("identity-commit").textContent = commit;
  $("identity-status").textContent = v.build_status;
  $("identity-footer").textContent = v.identity_label;
  $("version").textContent = `Version ${v.version} · Release build ${buildId} · Runs locally on this computer`;
  $("inspect").hidden = v.ready; $("confirm").hidden = !v.ready;
  if (!v.ready) $("help").open = true;
}
async function action(fn, focusId = "title") {
  if (busy) return; busy = true;
  const fromButton = document.activeElement?.tagName === "BUTTON";
  document.querySelectorAll("button").forEach(b => b.disabled = true);
  $("readiness").setAttribute("aria-busy", "true");
  $("status").className = ""; $("status").textContent = "Checking…";
  try { await fn(); } catch (err) {
    clearChecks("Not verified. The request did not finish. Check again before requesting a restart.");
    $("title").textContent="The request could not finish";
    $("detail").textContent="Nothing was erased by this launcher. Check again or use the boot instructions below.";
    $("status").className="error"; $("status").textContent=err.message || "The launcher is no longer connected. Open it again from the USB.";
    $("confirm").hidden=true; $("inspect").hidden=false; $("help").open=true;
    focusId="status";
  } finally {
    $("readiness")?.setAttribute("aria-busy", "false");
    busy=false; document.querySelectorAll("button").forEach(b => b.disabled=false);
    if ($("restart")) $("restart").disabled=!ready||!$("saved").checked;
    // Announce the result without moving focus onto an action that a held key
    // could activate. Preserve focus if the user moved elsewhere while waiting.
    if (fromButton && document.activeElement === document.body) $(focusId)?.focus();
  }
}
$("inspect").onclick=()=>action(async()=>{clearChecks("Checking the original USB, startup settings, and restart route…");show(await api("check"));$("status").textContent="Readiness checks updated.";});
$("saved").onchange=()=>{$("restart").disabled=busy||!ready||!$("saved").checked;};
$("restart").onclick=()=>action(async()=>{
  if (!ready || !$("saved").checked) return;
  clearChecks("Restart requested. Check readiness again before making another request.");
  $("status").textContent="Requesting permission to restart…";
  const result=await api("restart",true);
  $("status").textContent=result.message; $("confirm").hidden=true; $("inspect").hidden=false;
}, "status");
$("close").onclick=()=>action(async()=>{
  await api("close"); token="";
  try { sessionStorage.removeItem("beamo-session"); } catch (_) {}
  $("close").remove();
  const main=document.querySelector("main");
  main.textContent="Beamo Wipe is closed. You can close this tab. Nothing was erased by the launcher.";
  main.tabIndex=-1; main.focus();
});
action(async()=>{const state=await api("state");show(state.preview?state:await api("check"));$("status").textContent="Readiness checks complete.";});
setInterval(()=>{if(token&&!busy)api("state").catch(()=>{});},30000);
