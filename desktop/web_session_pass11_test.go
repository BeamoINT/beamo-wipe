// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"os"
	"os/exec"
	"strings"
	"testing"
)

func TestBrowserRestartSendsRevisionShownBeforeClearingReadiness(t *testing.T) {
	node, err := exec.LookPath("node")
	if err != nil {
		t.Skip("Node.js unavailable for browser request behavior")
	}
	source, err := os.ReadFile("web/app.js")
	if err != nil {
		t.Fatal(err)
	}
	js := string(source)
	start := strings.Index(js, `$("restart").onclick=()=>action(`)
	if start < 0 {
		t.Fatal("restart browser handler unavailable")
	}
	endRelative := strings.Index(js[start:], `$("close").onclick=`)
	if endRelative < 0 {
		t.Fatal("restart browser handler has no end marker")
	}
	end := start + endRelative
	program := `
let ready = true, reviewedRevision = 7, sent = null;
const elements = {saved:{checked:true}, restart:{}, status:{}, confirm:{}, inspect:{}};
const $ = id => elements[id];
function clearChecks() { ready = false; reviewedRevision = 0; }
function action(fn) { return fn(); }
async function api(action, confirm, revision) {
  sent = {action, confirm, revision}; return {message:'requested'};
}
` + js[start:end] + `
Promise.resolve(elements.restart.onclick()).then(() => {
  if (!sent || sent.action !== 'restart' || !sent.confirm || sent.revision !== 7)
    throw Error('restart did not use the displayed review revision');
}).catch(error => { console.error(error); process.exitCode = 1; });
`
	output, err := exec.Command(node, "-e", program).CombinedOutput()
	if err != nil {
		t.Fatalf("browser restart regression failed: %v\n%s", err, output)
	}
}

func TestBrowserAPISerializesReviewRevision(t *testing.T) {
	node, err := exec.LookPath("node")
	if err != nil {
		t.Skip("Node.js unavailable for browser request behavior")
	}
	source, err := os.ReadFile("web/app.js")
	if err != nil {
		t.Fatal(err)
	}
	js := string(source)
	start := strings.Index(js, "async function api(")
	end := strings.Index(js, "function show(")
	if start < 0 || end <= start {
		t.Fatal("browser API function unavailable")
	}
	program := `
const token = 'session-token';
let sent;
async function fetch(url, options) {
  sent = {url, options}; return {ok:true, json:async () => ({})};
}
` + js[start:end] + `
api('restart', true, 7).then(() => {
  const body = JSON.parse(sent.options.body);
  if (sent.url !== '/api/restart' || body.confirm !== true || body.revision !== 7)
    throw Error('browser omitted the reviewed revision from its request');
}).catch(error => { console.error(error); process.exitCode = 1; });
`
	output, err := exec.Command(node, "-e", program).CombinedOutput()
	if err != nil {
		t.Fatalf("browser request serialization failed: %v\n%s", err, output)
	}
}
