// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLauncherBytesAreBoundToMediaFingerprintPass22(t *testing.T) {
	root := mediaFixture(t)
	exe := filepath.Join(root, "app")
	before := inspectMedia(exe)
	if before.Problem != "" || before.Fingerprint == "" {
		t.Fatalf("prepared media was not accepted: %+v", before)
	}
	initial, err := os.Stat(exe)
	if err != nil {
		t.Fatal(err)
	}
	fixtureFile(t, root, "app", "changed! fixture") // Same length as original.
	if err := os.Chtimes(exe, initial.ModTime(), initial.ModTime()); err != nil {
		t.Fatal(err)
	}
	after, err := os.Stat(exe)
	if err != nil {
		t.Fatal(err)
	}
	if after.Size() != initial.Size() {
		t.Fatalf("fixture did not preserve launcher size: before=%d after=%d", initial.Size(), after.Size())
	}
	changed := inspectMedia(exe)
	if changed.Problem != "" || changed.Fingerprint == before.Fingerprint {
		t.Fatalf("changed launcher retained restart fingerprint: before=%+v after=%+v", before, changed)
	}
}
