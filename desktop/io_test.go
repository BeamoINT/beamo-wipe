// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestExclusiveWriteRemovesIncompleteFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "BootNext")
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}
	err = finishExclusiveWrite(f, path, []byte{7, 0, 0, 0, 4, 0})
	if err == nil {
		t.Fatal("expected write failure after the file was closed")
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatal("incomplete firmware variable left behind")
	}
}

func TestExclusiveWriteKeepsCompleteFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "BootNext")
	if err := writeExclusiveFile(path, []byte{7, 0, 0, 0, 4, 0}, 0); err != nil {
		t.Fatal(err)
	}
	b, err := os.ReadFile(path)
	if err != nil || string(b) != string([]byte{7, 0, 0, 0, 4, 0}) {
		t.Fatalf("%q %v", b, err)
	}
}
