// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"encoding/binary"
	"testing"
)

func option(guid byte) []byte {
	// Active load option, empty description, one GPT HD path, file path, end.
	hd := make([]byte, 42)
	hd[0], hd[1] = 4, 1
	binary.LittleEndian.PutUint16(hd[2:], 42)
	binary.LittleEndian.PutUint32(hd[4:], 1)
	binary.LittleEndian.PutUint64(hd[8:], 2048)
	binary.LittleEndian.PutUint64(hd[16:], 4096)
	hd[24], hd[40], hd[41] = guid, 2, 2
	file := []byte{4, 4, 0, 0}
	for _, r := range `\EFI\BOOT\BOOTX64.EFI` {
		file = append(file, byte(r), 0)
	}
	file = append(file, 0, 0)
	binary.LittleEndian.PutUint16(file[2:], uint16(len(file)))
	path := append(hd, file...)
	path = append(path, 0x7f, 0xff, 4, 0)
	data := make([]byte, 8)
	data[0] = 1
	binary.LittleEndian.PutUint16(data[4:], uint16(len(path)))
	return append(data, path...)
}

func TestExactBootOption(t *testing.T) {
	id, err := parseBootOption(option(1))
	if err != nil || id != "gpt:00000001-0000-0000-0000-000000000000" {
		t.Fatalf("%q %v", id, err)
	}
}

func TestMalformedOptionsRefused(t *testing.T) {
	valid := option(1)
	for n := 0; n < len(valid); n++ {
		if _, err := parseBootOption(valid[:n]); err == nil {
			t.Fatalf("accepted truncation %d", n)
		}
	}
	for _, change := range []func([]byte){
		func(b []byte) { b[0] = 0 },
		func(b []byte) { b[10] = 0; b[11] = 0 },
		func(b []byte) { b[49] = 0 },
		func(b []byte) { b[32] = 0 },
		func(b []byte) { b[len(b)-3] = 1 },
	} {
		bad := append([]byte(nil), valid...)
		change(bad)
		if _, err := parseBootOption(bad); err == nil {
			t.Fatal("accepted malformed option")
		}
	}
}

func TestPlanningRequiresOneExactUSBEntry(t *testing.T) {
	s := Snapshot{UEFI: true, MediaID: "usb:123", Partitions: []string{"gpt:00000001-0000-0000-0000-000000000000"}, Entries: map[uint16][]byte{4: option(1)}}
	p := makePlan(s)
	if !p.Direct || p.Entry != 4 || len(p.Fingerprint) != 64 {
		t.Fatalf("%+v", p)
	}
	s.Entries[5] = option(2)
	if !makePlan(s).Direct {
		t.Fatal("unrelated entry interfered")
	}
	s.Entries[5] = option(1)
	if makePlan(s).Direct {
		t.Fatal("ambiguous entry accepted")
	}
	delete(s.Entries, 5)
	s.Pending = true
	if makePlan(s).Direct {
		t.Fatal("pending BootNext overwritten")
	}
	s.Pending = false
	s.MediaID = ""
	if makePlan(s).Direct {
		t.Fatal("unidentified media accepted")
	}
}
