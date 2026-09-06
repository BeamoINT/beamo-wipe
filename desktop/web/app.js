"use strict";
const $ = id => document.getElementById(id);
let token = location.hash.slice(1);
history.replaceState(null, "", "/");
let busy = false;
async function api(action, confirm = false) {
  const response = await fetch(`/api/${action}`, {method:"POST", headers:{"Content-Type":"application/json","X-Beamo-Token":token}, body:JSON.stringify({confirm}), cache:"no-store", credentials:"omit", redirect:"error"});
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}
function show(v) {
  $("preview").hidden = !v.preview;
  $("title").textContent = v.title; $("detail").textContent = v.detail;
  $("version").textContent = `Version ${v.version} · Runs locally on this computer`;
  $("inspect").hidden = v.ready; $("confirm").hidden = !v.ready;
  if (!v.ready) $("help").open = true;
}
async function action(fn) {
  if (busy) return; busy = true;
  document.querySelectorAll("button").forEach(b => b.disabled = true);
  $("status").className = ""; $("status").textContent = "Checking…";
  try { await fn(); } catch (err) {
    $("status").className="error"; $("status").textContent=err.message || "The launcher is no longer connected. Open it again from the USB.";
    $("confirm").hidden=true; $("inspect").hidden=false; $("help").open=true;
  } finally { busy=false; document.querySelectorAll("button").forEach(b => b.disabled=false); }
}
$("inspect").onclick=()=>action(async()=>{show(await api("check"));$("status").textContent="";});
$("restart").onclick=()=>action(async()=>{
  $("status").textContent="Requesting permission to restart…";
  const result=await api("restart",true);
  $("status").textContent=result.message; $("confirm").hidden=true; $("inspect").hidden=false;
});
$("close").onclick=()=>action(async()=>{await api("close");token="";document.querySelector("main").textContent="Beamo Wipe is closed. You can close this tab. Nothing was erased by the launcher.";});
action(async()=>{const state=await api("state");show(state.preview?state:await api("check"));$("status").textContent="";});
setInterval(()=>{if(token&&!busy)api("state").catch(()=>{});},30000);
