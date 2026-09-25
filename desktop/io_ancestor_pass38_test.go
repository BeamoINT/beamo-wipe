//go:build !windows

// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"context"
	"os"
	"path/filepath"
	"testing"
)

func TestMediaReadRejectsReplacedAncestorDirectory(t *testing.T) {
	root := t.TempDir()
	boot := filepath.Join(root, "EFI", "BOOT")
	if err := os.MkdirAll(boot, 0700); err != nil {
		t.Fatal(err)
	}
	loader := filepath.Join(boot, "BOOTX64.EFI")
	if err := os.WriteFile(loader, []byte("MZ-original-loader"), 0600); err != nil {
		t.Fatal(err)
	}
	verified, err := mediaFile(root, "EFI/BOOT/BOOTX64.EFI")
	if err != nil {
		t.Fatal(err)
	}
	outside := filepath.Join(root, "outside")
	if err := os.Mkdir(outside, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(outside, "BOOTX64.EFI"), []byte("MZ-outside-loader"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(boot, boot+".saved"); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, boot); err != nil {
		t.Fatal(err)
	}
	if got, err := readSmall(verified, 1024); err == nil {
		t.Fatalf("read through replaced ancestor: %q", got)
	}
	if got, err := mediaDigest(context.Background(), verified, 1024); err == nil {
		t.Fatalf("hashed through replaced ancestor: %x", got)
	}
}
