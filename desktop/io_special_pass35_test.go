//go:build !windows

// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"os"
	"path/filepath"
	"syscall"
	"testing"
	"time"
)

func TestReadSmallRejectsFIFOWithoutBlocking(t *testing.T) {
	path := filepath.Join(t.TempDir(), "identity.json")
	if err := syscall.Mkfifo(path, 0600); err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 1)
	go func() { _, err := readSmall(path, 4096); done <- err }()
	select {
	case err := <-done:
		if err == nil {
			t.Fatal("FIFO was accepted as an identity file")
		}
	case <-time.After(2 * time.Second):
		t.Fatal("identity read blocked on a FIFO")
	}
}

func TestReadSmallRejectsLinkedMediaFile(t *testing.T) {
	dir := t.TempDir()
	outside := filepath.Join(dir, "outside")
	if err := os.WriteFile(outside, []byte("outside bytes"), 0600); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(dir, "identity.json")
	if err := os.Symlink(outside, link); err != nil {
		t.Fatal(err)
	}
	if _, err := readSmall(link, 4096); err == nil {
		t.Fatal("linked identity file was read")
	}
}
