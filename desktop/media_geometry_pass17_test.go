// SPDX-License-Identifier: GPL-3.0-or-later
package main

import "testing"

func TestPartitionWithinDiskPass17(t *testing.T) {
	for _, tc := range []struct {
		name                string
		disk, start, length uint64
		want                bool
	}{
		{"normal", 8000000000, 2048, 2097152, true},
		{"zero disk", 0, 2048, 2097152, false},
		{"zero start", 8000000000, 0, 2097152, false},
		{"zero partition", 8000000000, 2048, 0, false},
		{"partition exceeds disk", 8000000000, 2048, 9000000000, false},
		{"start exceeds disk", 8000000000, 20000000, 2097152, false},
		{"exact end", 8000000000, 2048, 7998951424, true},
		{"overflowing start", ^uint64(0), ^uint64(0), 1, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if got := partitionWithinDisk(tc.disk, tc.start, tc.length); got != tc.want {
				t.Fatalf("disk=%d start=%d length=%d: got %t, want %t", tc.disk, tc.start, tc.length, got, tc.want)
			}
		})
	}
}

func TestParseMBRSignatureRequiresEightHexDigitsPass17(t *testing.T) {
	for _, tc := range []struct {
		text  string
		want  uint32
		valid bool
	}{
		{"12345678", 0x12345678, true},
		{"ABCDEF12", 0xabcdef12, true},
		{"12zz5678", 0, false},
		{"1234567g", 0, false},
		{"1234567", 0, false},
		{"00000000", 0, false},
	} {
		got, valid := parseMBRSignature(tc.text)
		if valid != tc.valid || (valid && got != tc.want) {
			t.Errorf("%q: got %08x valid=%t, want %08x valid=%t", tc.text, got, valid, tc.want, tc.valid)
		}
	}
}
