// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"context"
	"strings"
	"testing"
)

func TestReadinessResponseDoesNotExposeDeviceIdentifiers(t *testing.T) {
	const serial = "PRIVATE-SERIAL-12345"
	const guid = "00000001-0000-0000-0000-000000000000"
	for _, pending := range []bool{false, true} {
		s := Snapshot{
			UEFI:       true,
			MediaID:    `[/dev/sdb,"` + serial + `"]`,
			Partitions: []string{"gpt:" + guid + ":1:2048:4096"},
			Entries:    map[uint16][]byte{4: option(1)},
			Pending:    pending,
		}
		a := testApp()
		a.probe = func(context.Context) Snapshot { return s }
		response := request(a, "/api/check", `{}`)
		if response.Code != 200 {
			t.Fatalf("pending=%t readiness request failed: %d", pending, response.Code)
		}
		for _, secret := range []string{serial, guid, "/dev/sdb"} {
			if strings.Contains(response.Body.String(), secret) {
				t.Fatalf("pending=%t exposed device identifier %q: %s", pending, secret, response.Body.String())
			}
		}
	}
}
