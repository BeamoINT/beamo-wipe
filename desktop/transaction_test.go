// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"bytes"
	"errors"
	"testing"
)

type fakeFirmware struct {
	values                  map[string][]byte
	writes, removes         int
	writeError, removeError bool
	changed                 bool
}

func (f *fakeFirmware) read(name string) ([]byte, error) {
	b, ok := f.values[name]
	if !ok {
		return nil, errAbsent
	}
	return append([]byte(nil), b...), nil
}
func (f *fakeFirmware) write(name string, b []byte) error {
	f.writes++
	f.values[name] = append([]byte(nil), b...)
	if f.changed {
		f.values[name] = []byte{9, 0}
	}
	if f.writeError {
		return errors.New("write failed after writing")
	}
	return nil
}
func (f *fakeFirmware) remove(name string) error {
	f.removes++
	if f.removeError {
		return errors.New("remove failed")
	}
	delete(f.values, name)
	return nil
}
func TestRestartTransaction(t *testing.T) {
	for _, mode := range []string{"success", "pending", "write_failure", "reboot_failure", "changed", "cleanup_failure", "no_plan"} {
		t.Run(mode, func(t *testing.T) {
			f := &fakeFirmware{values: map[string][]byte{}}
			p := Plan{Direct: true, Entry: 4}
			calls := 0
			if mode == "pending" {
				f.values["BootNext"] = []byte{8, 0}
			}
			f.writeError = mode == "write_failure"
			f.changed = mode == "changed"
			f.removeError = mode == "cleanup_failure"
			if mode == "no_plan" {
				p.Direct = false
			}
			err := restartOnce(f, p, func() error {
				calls++
				if mode == "reboot_failure" || mode == "cleanup_failure" {
					return errors.New("veto")
				}
				return nil
			})
			if mode == "success" {
				if err != nil || calls != 1 || !bytes.Equal(f.values["BootNext"], []byte{4, 0}) {
					t.Fatalf("%v %+v", err, f)
				}
				return
			}
			if err == nil {
				t.Fatal("failure reported as success")
			}
			if mode == "pending" || mode == "no_plan" {
				if f.writes != 0 || calls != 0 {
					t.Fatal("mutated without plan")
				}
			}
			if mode == "changed" {
				if f.removes != 0 || calls != 0 {
					t.Fatal("changed another application's request")
				}
			}
			if mode == "write_failure" || mode == "reboot_failure" {
				if _, ok := f.values["BootNext"]; ok {
					t.Fatal("left stale boot request")
				}
			}
		})
	}
}

func TestFingerprintChangesWithIdentity(t *testing.T) {
	s := Snapshot{UEFI: true, MediaID: "usb:123", Partitions: []string{"gpt:00000001-0000-0000-0000-000000000000"}, Entries: map[uint16][]byte{4: option(1)}}
	a := makePlan(s)
	s.MediaID = "usb:456"
	b := makePlan(s)
	if a.Fingerprint == b.Fingerprint {
		t.Fatal("media identity not bound")
	}
	s.MediaID = "usb:123"
	s.SecureBoot = "enabled"
	b = makePlan(s)
	if a.Fingerprint == b.Fingerprint {
		t.Fatal("firmware state not bound")
	}
}

func TestBootInventoryRefusesUnreadableOrDuplicate(t *testing.T) {
	for _, order := range [][]byte{nil, {1}, {1, 0, 1, 0}, make([]byte, 514)} {
		f := &fakeFirmware{values: map[string][]byte{"BootOrder": order, "Boot0001": option(1)}}
		if _, _, _, err := readBootEntries(f); err == nil {
			t.Fatal("accepted malformed inventory")
		}
	}
}

func FuzzBootOption(f *testing.F) {
	f.Add(option(1))
	f.Add([]byte{})
	f.Add([]byte{1, 2, 3, 4})
	f.Fuzz(func(t *testing.T, b []byte) {
		id, err := parseBootOption(b)
		if err == nil && id == "" {
			t.Fatal("empty identity accepted")
		}
	})
}
