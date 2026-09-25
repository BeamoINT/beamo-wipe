// SPDX-License-Identifier: GPL-3.0-or-later
package main

import "testing"

func TestGPTFirmwareRouteRequiresGPTDiskTablePass20(t *testing.T) {
	const partitionGUID = "11111111-2222-3333-4444-555555555555"
	for _, tc := range []struct {
		name, tableID, want string
	}{
		{"GPT disk", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "gpt:" + partitionGUID + ":1:2048:4096"},
		{"uppercase GPT disk", "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE", "gpt:" + partitionGUID + ":1:2048:4096"},
		{"MBR disk", "12345678", ""},
		{"unknown disk table", "", ""},
		{"zero GPT disk UUID", "00000000-0000-0000-0000-000000000000", ""},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if got := gptFirmwareRoute(partitionGUID, tc.tableID, 1, 2048, 4096); got != tc.want {
				t.Fatalf("table=%q authorized route %q; want %q", tc.tableID, got, tc.want)
			}
		})
	}
	for _, tc := range []struct {
		name        string
		part        uint32
		start, size uint64
	}{
		{"zero partition", 0, 2048, 4096},
		{"zero start", 1, 0, 4096},
		{"zero size", 1, 2048, 0},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if got := gptFirmwareRoute(partitionGUID, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", tc.part, tc.start, tc.size); got != "" {
				t.Fatalf("invalid GPT geometry authorized %q", got)
			}
		})
	}
}
