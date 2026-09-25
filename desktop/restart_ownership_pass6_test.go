// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

// A second firmware writer can create the same next-boot entry after our
// initial absence check. An exclusive-create failure never gives us ownership
// of that writer's request, even when its bytes equal the entry we wanted.
type competingFirmware struct {
	fakeFirmware
}

func (f *competingFirmware) write(name string, want []byte) (bool, error) {
	f.writes++
	f.values[name] = append([]byte(nil), want...)
	return false, os.ErrExist
}

func TestRestartDoesNotRemoveConcurrentSameEntry(t *testing.T) {
	f := &competingFirmware{fakeFirmware{values: map[string][]byte{}}}
	reboots := 0
	err := restartOnce(f, Plan{Direct: true, Entry: 4}, func() error {
		reboots++
		return nil
	})
	if err == nil || reboots != 0 {
		t.Fatalf("concurrent write was accepted: err=%v reboots=%d", err, reboots)
	}
	if f.removes != 0 || !bytes.Equal(f.values["BootNext"], []byte{4, 0}) {
		t.Fatalf("removed another writer's BootNext: removes=%d value=%x", f.removes, f.values["BootNext"])
	}
}

func TestExclusiveFirmwareWriteReportsCreation(t *testing.T) {
	path := filepath.Join(t.TempDir(), "BootNext")
	if err := os.WriteFile(path, []byte{4, 0}, 0600); err != nil {
		t.Fatal(err)
	}
	created, err := writeExclusiveFileOwned(path, []byte{4, 0}, 0)
	if created || !os.IsExist(err) {
		t.Fatalf("foreign path reported as owned: created=%t err=%v", created, err)
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	created, err = writeExclusiveFileOwned(path, []byte{7, 0, 0, 0, 4, 0}, 0)
	if !created || err != nil {
		t.Fatalf("exclusive creation not reported: created=%t err=%v", created, err)
	}
}
