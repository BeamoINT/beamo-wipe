// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"context"
	"encoding/json"
	"os"
	"strings"
	"testing"
)

func TestReadinessExplainsEachCheck(t *testing.T) {
	fixtures := map[string]view{}
	good := Snapshot{UEFI: true, MediaID: "usb:123", Partitions: []string{"gpt:00000001-0000-0000-0000-000000000000"}, Entries: map[uint16][]byte{4: option(1)}}
	for _, tc := range []struct {
		name, problem   string
		media, settings bool
		want            [3]string
	}{
		{"pass", "", true, true, [3]string{"pass", "pass", "pass"}},
		{"partial", "entry", true, true, [3]string{"pass", "pass", "unsupported"}},
		{"fail", "media", false, false, [3]string{"fail", "unverified", "unverified"}},
		{"unsupported", "platform", false, false, [3]string{"unverified", "unverified", "unsupported"}},
		{"legacy", "legacy", false, false, [3]string{"unverified", "unsupported", "unsupported"}},
		{"permission", "firmware", true, false, [3]string{"pass", "unverified", "unverified"}},
		{"pending", "pending", true, true, [3]string{"pass", "pass", "blocked"}},
		{"unattended", "unattended", false, false, [3]string{"fail", "unverified", "blocked"}},
		{"live", "live", false, false, [3]string{"unverified", "unverified", "unsupported"}},
		{"timeout", "timeout", false, false, [3]string{"unverified", "unverified", "unverified"}},
		{"cancelled", "cancelled", false, false, [3]string{"unverified", "unverified", "unverified"}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			s := good
			s.Problem = tc.problem
			if !tc.media {
				s.MediaID = ""
				s.Partitions = nil
			}
			if !tc.settings {
				s.Entries = nil
			}
			p := makePlan(s)
			fixtures[tc.name] = planView(p, false)
			raw, _ := json.Marshal(fixtures[tc.name])
			var result struct {
				Checks    []struct{ ID, State, Label, Detail, Next string }
				Technical string
			}
			if err := json.Unmarshal(raw, &result); err != nil {
				t.Fatal(err)
			}
			if len(result.Checks) != 3 {
				t.Fatalf("want three explained checks, got %s", raw)
			}
			for i, c := range result.Checks {
				if c.State != tc.want[i] || c.Label == "" || c.Detail == "" || c.Next == "" {
					t.Fatalf("check %d: %+v", i, c)
				}
			}
			if result.Technical == "" {
				t.Fatal("technical evidence missing")
			}
			if tc.media && !strings.Contains(result.Technical, "usb:123") {
				t.Fatal("USB identity lost")
			}
			if tc.name == "permission" && !strings.Contains(result.Checks[1].Next, "permission") {
				t.Fatal("permission recovery missing")
			}
			if p.Direct != (tc.name == "pass") {
				t.Fatal("restart contract changed")
			}
		})
	}
	if path := os.Getenv("BEAMO_READINESS_FIXTURES"); path != "" {
		data, err := json.Marshal(fixtures)
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, data, 0600); err != nil {
			t.Fatal(err)
		}
	}
}

func TestCancelledReadinessDoesNotRetainPassedChecks(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	p := inspectPlan(ctx, func(context.Context) Snapshot { return Snapshot{MediaID: "stale"} })
	raw, _ := json.Marshal(planView(p, false))
	if strings.Contains(string(raw), `"state":"pass"`) || strings.Contains(string(raw), "stale") {
		t.Fatal(string(raw))
	}
}

func TestReadinessNeverInfersEarlierPassesFromProblemCode(t *testing.T) {
	for _, problem := range []string{"entry", "pending", "firmware", "timeout", "cancelled", "unknown"} {
		t.Run(problem, func(t *testing.T) {
			v := planView(Plan{Problem: problem}, false)
			if len(v.Checks) != 3 {
				t.Fatal("missing checks")
			}
			for _, c := range v.Checks {
				if c.State == "pass" || c.Next == "" {
					t.Fatalf("unsupported evidence: %+v", c)
				}
			}
		})
	}
}
