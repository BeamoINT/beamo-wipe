// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"encoding/binary"
	"testing"
)

func TestUSBWWIDPrefixRequiresNonemptySerialPass13(t *testing.T) {
	// USB WWID must contain part of the device serial number. A zero-only
	// UTF-16 payload identifies no serial and must not authorize BootNext.
	empty := []byte{3, 16, 12, 0, 1, 0, 0x34, 0x12, 0x78, 0x56, 0, 0}
	if id, err := parseBootOption(optionWithPrefix(empty)); err == nil {
		t.Fatalf("accepted USB WWID with no serial: %s", id)
	}
	valid := append([]byte(nil), empty...)
	valid[10] = 'A'
	if id, err := parseBootOption(optionWithPrefix(valid)); err != nil || id == "" {
		t.Fatalf("valid one-character USB WWID refused: %q %v", id, err)
	}
}

func TestUSBWWIDPrefixRequiresValidUTF16Pass13(t *testing.T) {
	// A lone surrogate is not a UTF-16 character and cannot identify a
	// serial, while a proper surrogate pair may occur in a serial.
	invalid := []byte{3, 16, 12, 0, 1, 0, 0x34, 0x12, 0x78, 0x56, 0x00, 0xd8}
	if id, err := parseBootOption(optionWithPrefix(invalid)); err == nil {
		t.Fatalf("accepted malformed UTF-16 USB WWID: %s", id)
	}
	valid := []byte{3, 16, 14, 0, 1, 0, 0x34, 0x12, 0x78, 0x56, 0x3d, 0xd8, 0x80, 0xde}
	if id, err := parseBootOption(optionWithPrefix(valid)); err != nil || id == "" {
		t.Fatalf("valid UTF-16 USB WWID refused: %q %v", id, err)
	}
}

func TestBootOptionRefusesReservedAttributesPass13(t *testing.T) {
	for _, reserved := range []uint32{0x00000004, 0x80000000} {
		entry := option(1)
		binary.LittleEndian.PutUint32(entry, 1|reserved)
		if id, err := parseBootOption(entry); err == nil {
			t.Fatalf("accepted boot option with reserved attribute %#x: %s", reserved, id)
		}
	}
	valid := option(1)
	binary.LittleEndian.PutUint32(valid, 1|2|8)
	if id, err := parseBootOption(valid); err != nil || id == "" {
		t.Fatalf("defined boot attributes were refused: %q %v", id, err)
	}
}
