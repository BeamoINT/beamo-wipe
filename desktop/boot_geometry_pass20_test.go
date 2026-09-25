// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"encoding/binary"
	"testing"
)

func TestGPTBootRouteRequiresExactPartitionGeometryPass20(t *testing.T) {
	const route = "gpt:00000001-0000-0000-0000-000000000000:1:2048:4096"
	base := option(1)
	for _, tc := range []struct {
		name       string
		edit       func([]byte)
		wantDirect bool
	}{
		{"exact", func([]byte) {}, true},
		{"different partition number", func(b []byte) { binary.LittleEndian.PutUint32(b[12:], 2) }, false},
		{"different start", func(b []byte) { binary.LittleEndian.PutUint64(b[16:], 4096) }, false},
		{"different size", func(b []byte) { binary.LittleEndian.PutUint64(b[24:], 8192) }, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			entry := append([]byte(nil), base...)
			tc.edit(entry)
			s := Snapshot{UEFI: true, MediaID: "usb:test", Partitions: []string{route}, Entries: map[uint16][]byte{4: entry}}
			p := makePlan(s)
			if p.Direct != tc.wantDirect {
				t.Fatalf("same-GUID route with %s was accepted=%t; want=%t", tc.name, p.Direct, tc.wantDirect)
			}
		})
	}
}
