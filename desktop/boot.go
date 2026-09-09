// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"
	"unicode/utf16"
)

const efiGlobal = "8be4df61-93ca-11d2-aa0d-00e098032b8c"

type Snapshot struct {
	Layout     string
	UEFI       bool
	MediaID    string
	Partitions []string
	Entries    map[uint16][]byte
	Pending    bool
	SecureBoot string
	Problem    string
}

type Plan struct {
	Direct      bool
	Entry       uint16
	Fingerprint string
	Problem     string
}

func guidString(b []byte) string {
	return fmt.Sprintf("%08x-%04x-%04x-%x-%x", binary.LittleEndian.Uint32(b), binary.LittleEndian.Uint16(b[4:]), binary.LittleEndian.Uint16(b[6:]), b[8:10], b[10:16])
}

// EFI structures are untrusted firmware data. Accept one complete, active,
// unambiguous disk/file path to the shipped removable-media loader only.
func parseBootOption(data []byte) (string, error) {
	bad := errors.New("unsupported boot option")
	if len(data) < 12 || len(data) > 16384 {
		return "", bad
	}
	attrs := binary.LittleEndian.Uint32(data)
	if attrs&1 == 0 || attrs&0x1f00 != 0 {
		return "", bad
	}
	n := int(binary.LittleEndian.Uint16(data[4:]))
	pos := 6
	for pos+1 < len(data) && pos < 1030 && (data[pos] != 0 || data[pos+1] != 0) {
		pos += 2
	}
	if pos+1 >= len(data) || data[pos] != 0 || data[pos+1] != 0 {
		return "", bad
	}
	pos += 2
	if n < 4 || pos+n != len(data) {
		return "", bad
	}
	path := data[pos:]
	id, file, ended := "", "", false
	for len(path) >= 4 {
		length := int(binary.LittleEndian.Uint16(path[2:]))
		if length < 4 || length > len(path) {
			return "", bad
		}
		node := path[:length]
		path = path[length:]
		switch {
		case node[0] == 4 && node[1] == 1:
			if length != 42 || id != "" || file != "" {
				return "", bad
			}
			part := binary.LittleEndian.Uint32(node[4:])
			start, size := binary.LittleEndian.Uint64(node[8:]), binary.LittleEndian.Uint64(node[16:])
			if part == 0 || size == 0 || start == 0 {
				return "", bad
			}
			if node[40] == 2 && node[41] == 2 && !bytes.Equal(node[24:40], make([]byte, 16)) {
				id = "gpt:" + guidString(node[24:40])
			} else if node[40] == 1 && node[41] == 1 && binary.LittleEndian.Uint32(node[24:]) != 0 && bytes.Equal(node[28:40], make([]byte, 12)) {
				id = fmt.Sprintf("mbr:%08x:%d:%d:%d", binary.LittleEndian.Uint32(node[24:]), part, start, size)
			} else {
				return "", bad
			}
		case node[0] == 4 && node[1] == 4:
			if id == "" || file != "" || length < 8 || length%2 != 0 || node[length-2] != 0 || node[length-1] != 0 {
				return "", bad
			}
			var chars []uint16
			for i := 4; i < length-2; i += 2 {
				v := binary.LittleEndian.Uint16(node[i:])
				if v < 32 || v > 126 {
					return "", bad
				}
				chars = append(chars, v)
			}
			file = strings.ToUpper(string(utf16.Decode(chars)))
			if file != `\EFI\BOOT\BOOTX64.EFI` {
				return "", bad
			}
		case node[0] == 0x7f && node[1] == 0xff && length == 4:
			if len(path) != 0 || id == "" || file == "" {
				return "", bad
			}
			ended = true
		default:
			// Hardware, ACPI and messaging nodes may precede the disk path.
			if id != "" || node[0] < 1 || node[0] > 3 {
				return "", bad
			}
		}
	}
	if !ended || len(path) != 0 {
		return "", bad
	}
	return id, nil
}

func makePlan(s Snapshot) Plan {
	p := Plan{Problem: s.Problem}
	if p.Problem != "" {
		return p
	}
	if !s.UEFI {
		p.Problem = "legacy"
		return p
	}
	if s.MediaID == "" || len(s.Partitions) == 0 {
		p.Problem = "media"
		return p
	}
	if s.Pending {
		p.Problem = "pending"
		return p
	}
	var matches []uint16
	for num, raw := range s.Entries {
		id, err := parseBootOption(raw)
		if err != nil {
			continue
		}
		for _, part := range s.Partitions {
			if part == id {
				matches = append(matches, num)
				break
			}
		}
	}
	if len(matches) != 1 {
		p.Problem = "entry"
		return p
	}
	parts := append([]string(nil), s.Partitions...)
	sort.Strings(parts)
	entry := matches[0]
	blob, _ := json.Marshal(struct {
		Layout string
		Media  string
		Parts  []string
		Entry  uint16
		Raw    []byte
		Secure string
	}{s.Layout, s.MediaID, parts, entry, s.Entries[entry], s.SecureBoot})
	sum := sha256.Sum256(blob)
	return Plan{Direct: true, Entry: entry, Fingerprint: hex.EncodeToString(sum[:])}
}

type firmware interface {
	read(string) ([]byte, error)
	write(string, []byte) error
	remove(string) error
}

var errAbsent = errors.New("firmware variable absent")

// A failed restart must not leave an unattended restart armed. Never remove a
// pending request that was not ours or was changed by another application.
func restartOnce(f firmware, p Plan, reboot func() error) error {
	if !p.Direct {
		return errors.New("no verified restart plan")
	}
	if _, err := f.read("BootNext"); !errors.Is(err, errAbsent) {
		return errors.New("next boot already set or unreadable")
	}
	want := []byte{byte(p.Entry), byte(p.Entry >> 8)}
	rollback := func() error {
		got, err := f.read("BootNext")
		if errors.Is(err, errAbsent) {
			return nil
		}
		if err != nil || !bytes.Equal(got, want) {
			return errors.New("restart request changed; cleanup not confirmed")
		}
		if err := f.remove("BootNext"); err != nil {
			return errors.New("restart request cleanup failed")
		}
		if _, err := f.read("BootNext"); !errors.Is(err, errAbsent) {
			return errors.New("restart request cleanup not confirmed")
		}
		return nil
	}
	if err := f.write("BootNext", want); err != nil {
		if undo := rollback(); undo != nil {
			return undo
		}
		return errors.New("restart request could not be written")
	}
	got, err := f.read("BootNext")
	if err != nil || !bytes.Equal(got, want) {
		if undo := rollback(); undo != nil {
			return undo
		}
		return errors.New("restart request could not be verified")
	}
	if err := reboot(); err != nil {
		if undo := rollback(); undo != nil {
			return undo
		}
		return errors.New("restart was declined; save work and try again")
	}
	return nil
}

func readBootEntries(f firmware) (map[uint16][]byte, bool, string, error) {
	order, err := f.read("BootOrder")
	if err != nil || len(order) == 0 || len(order)%2 != 0 || len(order) > 512 {
		return nil, false, "", errors.New("boot inventory unavailable")
	}
	entries := map[uint16][]byte{}
	for i := 0; i < len(order); i += 2 {
		n := binary.LittleEndian.Uint16(order[i:])
		if _, exists := entries[n]; exists {
			return nil, false, "", errors.New("duplicate boot inventory")
		}
		b, e := f.read(fmt.Sprintf("Boot%04X", n))
		if e != nil {
			return nil, false, "", e
		}
		entries[n] = b
	}
	_, err = f.read("BootNext")
	if err != nil && !errors.Is(err, errAbsent) {
		return nil, false, "", err
	}
	pending := err == nil
	secure := "unknown"
	if b, e := f.read("SecureBoot"); e == nil && len(b) == 1 {
		if b[0] == 1 {
			secure = "enabled"
		} else if b[0] == 0 {
			secure = "disabled"
		}
	}
	return entries, pending, secure, nil
}
