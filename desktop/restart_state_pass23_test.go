// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"context"
	"encoding/json"
	"testing"
)

func TestRestartDisarmsPublishedReadinessBeforeHelperReturnsPass23(t *testing.T) {
	a := testApp()
	a.revision = 7
	a.current = planView(a.p, false)
	a.current.Revision = a.revision
	started := make(chan struct{})
	release := make(chan struct{})
	a.restart = func(context.Context, string) error {
		close(started)
		<-release
		return nil
	}
	finished := make(chan int, 1)
	go func() { finished <- request(a, "/api/restart", `{"confirm":true,"revision":7}`).Code }()
	<-started
	state := request(a, "/api/state", `{}`)
	var published view
	if err := json.Unmarshal(state.Body.Bytes(), &published); err != nil {
		t.Fatal(err)
	}
	close(release)
	if status := <-finished; status != 200 {
		t.Fatalf("fake restart failed: %d", status)
	}
	if state.Code != 200 || published.Ready || published.Revision <= 7 {
		t.Fatalf("consumed plan remained published during restart: status=%d state=%+v", state.Code, published)
	}
	settled := request(a, "/api/state", `{}`)
	var after view
	if err := json.Unmarshal(settled.Body.Bytes(), &after); err != nil {
		t.Fatal(err)
	}
	if after.Ready || after.Revision != published.Revision {
		t.Fatalf("restart completion changed consumed readiness: %+v", after)
	}
}
