// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"testing"
)

func TestRestartRefusesPlanReplacedAfterEarlierTabReviewed(t *testing.T) {
	a := testApp()
	previous := a.p.Fingerprint
	a.probe = func(context.Context) Snapshot {
		return Snapshot{
			Layout: "new-layout", UEFI: true, MediaID: "new-usb",
			Partitions: []string{"gpt:00000001-0000-0000-0000-000000000000:1:2048:4096"},
			Entries:    map[uint16][]byte{4: option(1)},
		}
	}
	restarts := 0
	a.restart = func(context.Context, string) error { restarts++; return nil }
	if response := request(a, "/api/check", `{"confirm":false}`); response.Code != 200 {
		t.Fatalf("replacement check failed: %d", response.Code)
	}
	if !a.p.Direct || a.p.Fingerprint == previous || len(a.p.Fingerprint) != 64 {
		t.Fatal("fake second tab did not replace the direct restart plan")
	}
	// The first tab submitted the consent it prepared for the old plan. The
	// launcher must not apply it to the newer check's USB and boot option.
	response := request(a, "/api/restart", `{"confirm":true}`)
	if response.Code < 400 || restarts != 0 {
		t.Fatalf("stale tab restarted a new plan: status=%d calls=%d body=%q",
			response.Code, restarts, strings.TrimSpace(response.Body.String()))
	}
}

func TestRestartConsentIsBoundToTheDisplayedCheck(t *testing.T) {
	a := testApp()
	layout := "first-layout"
	a.probe = func(context.Context) Snapshot {
		return Snapshot{
			Layout: layout, UEFI: true, MediaID: "same-usb",
			Partitions: []string{"gpt:00000001-0000-0000-0000-000000000000:1:2048:4096"},
			Entries:    map[uint16][]byte{4: option(1)},
		}
	}
	check := func() view {
		t.Helper()
		response := request(a, "/api/check", `{"confirm":false}`)
		if response.Code != 200 {
			t.Fatalf("check failed: %d", response.Code)
		}
		var shown view
		if err := json.Unmarshal(response.Body.Bytes(), &shown); err != nil {
			t.Fatal(err)
		}
		if !shown.Ready || shown.Revision == 0 {
			t.Fatalf("ready check lacks a review revision: %+v", shown)
		}
		return shown
	}
	first := check()
	layout = "second-layout"
	second := check()
	if second.Revision == first.Revision {
		t.Fatal("replacement check reused the first review revision")
	}
	restarts := 0
	a.restart = func(context.Context, string) error { restarts++; return nil }
	stale := request(a, "/api/restart", fmt.Sprintf(`{"confirm":true,"revision":%d}`, first.Revision))
	if stale.Code != 409 || restarts != 0 {
		t.Fatalf("first tab restarted a different review: status=%d calls=%d", stale.Code, restarts)
	}
	fresh := request(a, "/api/restart", fmt.Sprintf(`{"confirm":true,"revision":%d}`, second.Revision))
	if fresh.Code != 200 || restarts != 1 {
		t.Fatalf("current tab could not restart its reviewed plan: status=%d calls=%d", fresh.Code, restarts)
	}
}
