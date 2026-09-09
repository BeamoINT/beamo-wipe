"use strict";
const $ = id => document.getElementById(id);
let token = location.hash.slice(1);
try {
  token = token || sessionStorage.getItem("beamo-session") || "";
  if (/^[a-f0-9]{64}$/.test(token)) sessionStorage.setItem("beamo-session", token);
} catch (_) { /* A restricted browser can still use the initial fragment. */ }
history.replaceState(null, "", "/");
let busy = false;
async function api(action, confirm = false) {
  let response;
  try {
    response = await fetch(`/api/${action}`, {method:"POST", headers:{"Content-Type":"application/json","X-Beamo-Token":token}, body:JSON.stringify({confirm}), cache:"no-store", credentials:"omit", redirect:"error"});
  } catch (_) { throw new Error("The launcher is no longer connected. Open Start Beamo Wipe from the USB again."); }
  if (!response.ok) throw new Error(response.status === 403 ? "This session has ended. Open Start Beamo Wipe from the USB again." : await response.text());
  return response.json();
}
function show(v) {
  $("saved").checked=false; $("restart").disabled=true;
  $("preview").hidden = !v.preview;
  $("title").textContent = v.title; $("detail").textContent = v.detail;
  $("version").textContent = `Version ${v.version} · Runs locally on this computer`;
  $("inspect").hidden = v.ready; $("confirm").hidden = !v.ready;
  if (!v.ready) $("help").open = true;
}
async function action(fn, focusId = "title") {
  if (busy) return; busy = true;
  const fromButton = document.activeElement?.tagName === "BUTTON";
  document.querySelectorAll("button").forEach(b => b.disabled = true);
  $("status").className = ""; $("status").textContent = "Checking…";
  try { await fn(); } catch (err) {
    $("title").textContent="The request could not finish";
    $("detail").textContent="Nothing was erased by this launcher. Check again or use the boot instructions below.";
    $("status").className="error"; $("status").textContent=err.message || "The launcher is no longer connected. Open it again from the USB.";
    $("confirm").hidden=true; $("inspect").hidden=false; $("help").open=true;
    focusId="status";
  } finally {
    busy=false; document.querySelectorAll("button").forEach(b => b.disabled=false);
    if ($("restart")) $("restart").disabled=!$("saved").checked;
    // Announce the result without moving focus onto an action that a held key
    // could activate. Preserve focus if the user moved elsewhere while waiting.
    if (fromButton && document.activeElement === document.body) $(focusId)?.focus();
  }
}
$("inspect").onclick=()=>action(async()=>{show(await api("check"));$("status").textContent="";});
$("saved").onchange=()=>{$("restart").disabled=busy||!$("saved").checked;};
$("restart").onclick=()=>action(async()=>{
  if (!$("saved").checked) return;
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
action(async()=>{const state=await api("state");show(state.preview?state:await api("check"));$("status").textContent="";});
setInterval(()=>{if(token&&!busy)api("state").catch(()=>{});},30000);
