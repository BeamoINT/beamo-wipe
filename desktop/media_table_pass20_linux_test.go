//go:build linux

// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"strings"
	"testing"
)

func TestLinuxGPTBootRouteRequiresGPTDiskTablePass20(t *testing.T) {
	const partitionGUID = "11111111-2222-3333-4444-555555555555"
	base := strings.Replace(linuxFixture, `"partuuid":"12345678-01"`, `"partuuid":"`+partitionGUID+`"`, 1)
	for _, tc := range []struct {
		name, tableID string
		wantRoute     bool
	}{
		{"GPT disk", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", true},
		{"MBR disk", "12345678", false},
		{"unknown disk table", "", false},
		{"zero GPT disk UUID", "00000000-0000-0000-0000-000000000000", false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			body := strings.Replace(base, `"ptuuid":"12345678"`, `"ptuuid":"`+tc.tableID+`"`, 1)
			_, routes, err := linuxMedia([]byte(body), "/dev/sdb1")
			if err != nil {
				t.Fatal(err)
			}
			if tc.wantRoute && (len(routes) != 1 || routes[0] != "gpt:"+partitionGUID+":1:2048:4096") {
				t.Fatalf("valid GPT route unavailable: %v", routes)
			}
			if !tc.wantRoute && len(routes) != 0 {
				t.Fatalf("contradictory partition table authorized boot route: %v", routes)
			}
		})
	}
}

func TestLinuxGPTBootRouteUsesLogicalSectorsPass20(t *testing.T) {
	const partitionGUID = "11111111-2222-3333-4444-555555555555"
	body := strings.Replace(linuxFixture, `"ptuuid":"12345678"`, `"ptuuid":"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"`, 1)
	body = strings.Replace(body, `"partuuid":"12345678-01"`, `"partuuid":"`+partitionGUID+`"`, 1)
	for _, tc := range []struct {
		name, sector, start, size, want string
	}{
		{"512 byte", "512", "2048", "2097152", "gpt:" + partitionGUID + ":1:2048:4096"},
		{"4096 byte", "4096", "2048", "2097152", "gpt:" + partitionGUID + ":1:256:512"},
		{"unaligned start", "4096", "2049", "2097152", ""},
		{"unaligned size", "4096", "2048", "2097153", ""},
		{"unknown sector", "0", "2048", "2097152", ""},
	} {
		t.Run(tc.name, func(t *testing.T) {
			fixture := strings.NewReplacer(`"log-sec":512`, `"log-sec":`+tc.sector,
				`"start":2048`, `"start":`+tc.start, `"size":2097152`, `"size":`+tc.size).Replace(body)
			_, routes, err := linuxMedia([]byte(fixture), "/dev/sdb1")
			if err != nil {
				t.Fatal(err)
			}
			if tc.want == "" && len(routes) != 0 {
				t.Fatalf("invalid geometry authorized %v", routes)
			}
			if tc.want != "" && (len(routes) != 1 || routes[0] != tc.want) {
				t.Fatalf("logical sector route %v; want %q", routes, tc.want)
			}
		})
	}
}
