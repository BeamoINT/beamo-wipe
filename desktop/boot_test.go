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
	if err != nil || id != "gpt:00000001-0000-0000-0000-000000000000:1:2048:4096" {
		t.Fatalf("%q %v", id, err)
	}
}

func optionWithPrefix(prefix []byte) []byte {
	base := option(1)
	path := append(append([]byte(nil), prefix...), base[8:]...)
	binary.LittleEndian.PutUint16(base[4:], uint16(len(path)))
	return append(base[:8], path...)
}

func TestBootOptionRefusesMalformedHardwarePrefix(t *testing.T) {
	bad := optionWithPrefix([]byte{1, 1, 4, 0}) // PCI nodes are six bytes.
	if _, err := parseBootOption(bad); err == nil {
		t.Fatal("accepted malformed PCI node")
	}
	s := Snapshot{UEFI: true, MediaID: "usb:123", Partitions: []string{"gpt:00000001-0000-0000-0000-000000000000:1:2048:4096"}, Entries: map[uint16][]byte{4: bad}}
	if p := makePlan(s); p.Direct {
		t.Fatalf("malformed firmware path offered direct restart: %+v", p)
	}
}

func TestBootOptionPreservesValidHardwarePrefix(t *testing.T) {
	rootAndPCI := []byte{
		2, 1, 12, 0, 0x41, 0xd0, 0x0a, 0x03, 0, 0, 0, 0, // PciRoot(0)
		1, 1, 6, 0, 0, 0x1f, // Pci(0x1f,0)
	}
	cases := map[string][]byte{
		"USB":  append(append([]byte(nil), rootAndPCI...), 3, 5, 6, 0, 1, 0),
		"SATA": append(append([]byte(nil), rootAndPCI...), 3, 18, 10, 0, 1, 0, 0xff, 0xff, 0, 0),
		"NVMe": append(append([]byte(nil), rootAndPCI...), 3, 23, 16, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
	}
	for name, prefix := range cases {
		t.Run(name, func(t *testing.T) {
			entry := optionWithPrefix(prefix)
			id, err := parseBootOption(entry)
			if err != nil || id != "gpt:00000001-0000-0000-0000-000000000000:1:2048:4096" {
				t.Fatalf("valid %s hardware path rejected: %q %v", name, id, err)
			}
			s := Snapshot{UEFI: true, MediaID: "usb:123", Partitions: []string{id}, Entries: map[uint16][]byte{4: entry}}
			if p := makePlan(s); !p.Direct {
				t.Fatalf("valid %s hardware path lost direct restart: %+v", name, p)
			}
		})
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
	s := Snapshot{UEFI: true, MediaID: "usb:123", Partitions: []string{"gpt:00000001-0000-0000-0000-000000000000:1:2048:4096"}, Entries: map[uint16][]byte{4: option(1)}}
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

func TestWindowsManualRestartPolicy(t *testing.T) {
	s := Snapshot{UEFI: true, MediaID: "usb:123", Partitions: []string{"gpt:00000001-0000-0000-0000-000000000000:1:2048:4096"}, Entries: map[uint16][]byte{4: option(1)}}
	if p := makePlanForHost(s, "linux"); !p.Direct {
		t.Fatalf("Linux guided restart was lost: %+v", p)
	}
	if p := makePlanForHost(s, "windows"); p.Direct || p.Fingerprint != "" || p.Problem != "windows-manual" {
		t.Fatalf("Windows retained a one-shot boot request despite cancelable shutdown: %+v", p)
	}
}

func TestMBRBootOptionMatchesVolumeGeometry(t *testing.T) {
	b := option(1)
	b[48], b[49] = 1, 1
	binary.LittleEndian.PutUint32(b[32:], 0x12345678)
	id, err := parseBootOption(b)
	if err != nil || id != "mbr:12345678:1:2048:4096" {
		t.Fatalf("%s %v", id, err)
	}
	b[36] = 1
	if _, err := parseBootOption(b); err == nil {
		t.Fatal("malformed MBR signature accepted")
	}
}
