// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"os"
	"os/exec"
	"strings"
	"testing"
)

func TestBrowserBootstrapSurvivesDeniedHistoryMutationPass19(t *testing.T) {
	node, err := exec.LookPath("node")
	if err != nil {
		t.Skip("Node.js unavailable for browser bootstrap test")
	}
	source, err := os.ReadFile("web/app.js")
	if err != nil {
		t.Fatal(err)
	}
	end := strings.Index(string(source), "let busy = false;")
	if end < 0 {
		t.Fatal("browser bootstrap boundary unavailable")
	}
	program := `
const tokenValue = 'a'.repeat(64);
const location = {hash: '#' + tokenValue};
const sessionStorage = {getItem: () => null, setItem: () => {}};
const history = {state: null, replaceState: () => {throw Error('history denied');}};
const window = {addEventListener: () => {}};
` + string(source[:end]) + `
if (token !== tokenValue) throw Error('session token lost');
`
	output, err := exec.Command(node, "-e", program).CombinedOutput()
	if err != nil {
		t.Fatalf("history denial interrupted launcher bootstrap: %v\n%s", err, output)
	}
}
