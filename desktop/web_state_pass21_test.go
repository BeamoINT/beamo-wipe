// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"os"
	"os/exec"
	"strings"
	"testing"
)

func TestBrowserPollDisarmsStaleReadinessPass21(t *testing.T) {
	node, err := exec.LookPath("node")
	if err != nil {
		t.Skip("Node.js unavailable for browser behavior")
	}
	source, err := os.ReadFile("web/app.js")
	if err != nil {
		t.Fatal(err)
	}
	start := strings.LastIndex(string(source), "function disarmStaleReadiness(")
	if start < 0 {
		t.Fatal("browser readiness poll unavailable")
	}
	program := `
let busy = false, ready = true, reviewedRevision = 7;
const token = 'session-token';
const elements = {status:{textContent:''}, inspect:{hidden:true}, help:{open:false}};
const $ = id => elements[id];
let tick, response, failed, calls = 0, deferResponse = false, deliver;
function setInterval(callback, milliseconds) {
  if (milliseconds !== 30000) throw Error('unexpected poll interval');
  tick = callback;
}
function clearChecks(message) { calls++; ready = false; reviewedRevision = 0; elements.message = message; }
async function api(action) {
  if (action !== 'state') throw Error('unexpected action');
  if (failed) throw Error('connection lost');
  if (deferResponse) return new Promise(resolve => { deliver = resolve; });
  return response;
}
` + string(source[start:]) + `
(async () => {
  response = {ready:true, revision:7};
  await tick();
  if (calls !== 0 || !ready) throw Error('unchanged readiness was cleared');
  response = {ready:true, revision:8};
  await tick();
  if (calls !== 1 || ready || reviewedRevision !== 0 || elements.inspect.hidden)
    throw Error('a second tab changed the check, but stale readiness remained');
  ready = true; reviewedRevision = 8;
  response = {ready:false, revision:8};
  await tick();
  if (calls !== 2 || ready) throw Error('consumed plan remained ready');
  ready = true; reviewedRevision = 8; failed = true;
  await tick();
  if (calls !== 3 || ready) throw Error('lost server connection left restart enabled');
  // A delayed poll must not erase a later local check that this tab showed.
  ready = true; reviewedRevision = 9; failed = false; deferResponse = true;
  const inFlight = tick();
  ready = false; reviewedRevision = 0;
  ready = true; reviewedRevision = 10;
  deliver({ready:true, revision:9});
  await inFlight;
  if (calls !== 3 || !ready || reviewedRevision !== 10)
    throw Error('old poll response erased a newer local check');
})().catch(error => { console.error(error); process.exitCode = 1; });
`
	output, err := exec.Command(node, "-e", program).CombinedOutput()
	if err != nil {
		t.Fatalf("browser kept stale readiness: %v\n%s", err, output)
	}
}
