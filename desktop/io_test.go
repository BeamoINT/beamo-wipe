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
	f, err := os.OpenFile(path, os.O_RDONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		t.Fatal(err)
	}
	err = finishExclusiveWrite(f, path, []byte{7, 0, 0, 0, 4, 0})
	if err == nil {
		t.Fatal("expected write failure on a read-only descriptor")
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatal("incomplete firmware variable left behind")
	}
}

func TestExclusiveWriteDoesNotRemoveAnotherOwnersReplacement(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "BootNext")
	f, err := os.OpenFile(path, os.O_RDONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(path, path+".old"); err != nil {
		t.Fatal(err)
	}
	other := []byte{7, 0, 0, 0, 9, 0}
	if err := os.WriteFile(path, other, 0600); err != nil {
		t.Fatal(err)
	}
	if err := finishExclusiveWrite(f, path, []byte{7, 0, 0, 0, 4, 0}); err == nil {
		t.Fatal("expected write failure")
	}
	got, err := os.ReadFile(path)
	if err != nil || string(got) != string(other) {
		t.Fatalf("another owner's BootNext was removed or changed: %q %v", got, err)
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
