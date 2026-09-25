// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"context"
	"testing"
	"time"
)

func TestBackgroundStatePollDoesNotPreventIdleShutdownPass22(t *testing.T) {
	a := testApp()
	idleSince := time.Now().Add(-6 * time.Minute)
	a.lastSeen = idleSince
	if response := request(a, "/api/state", `{}`); response.Code != 200 {
		t.Fatalf("state poll failed: %d", response.Code)
	}
	if !a.lastSeen.Equal(idleSince) {
		t.Fatal("background polling refreshed user activity and prevented idle shutdown")
	}

	a.probe = func(context.Context) Snapshot { return Snapshot{Problem: "entry"} }
	if response := request(a, "/api/check", `{}`); response.Code != 200 {
		t.Fatalf("explicit recheck failed: %d", response.Code)
	}
	if !a.lastSeen.After(idleSince) {
		t.Fatal("explicit recheck did not refresh user activity")
	}
}
