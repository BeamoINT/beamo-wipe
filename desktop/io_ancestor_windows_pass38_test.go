//go:build windows

// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"context"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestWindowsInputPathDriveAndUNC(t *testing.T) {
	wantParts := []string{"EFI", "BOOT", "BOOTX64.EFI"}
	for _, test := range []struct {
		path, root string
	}{
		{`E:\EFI\BOOT\BOOTX64.EFI`, `E:\`},
		{`\\server\share\EFI\BOOT\BOOTX64.EFI`, `\\server\share\`},
		{`\\?\UNC\server\share\EFI\BOOT\BOOTX64.EFI`, `\\?\UNC\server\share\`},
	} {
		root, parts, err := windowsInputPath(test.path)
		if err != nil || root != test.root || !reflect.DeepEqual(parts, wantParts) {
			t.Errorf("windowsInputPath(%q) = %q, %q, %v", test.path, root, parts, err)
		}
	}
}

func TestWindowsMediaReadRejectsReplacedAncestorDirectory(t *testing.T) {
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
	if got, err := readSmall(verified, 1024); err != nil || string(got) != "MZ-original-loader" {
		t.Fatalf("normal loader read: %q, %v", got, err)
	}
	if _, err := mediaDigest(context.Background(), verified, 1024); err != nil {
		t.Fatalf("normal loader digest: %v", err)
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
		// Windows may require Developer Mode or a privilege to create symlinks.
		t.Skipf("directory symlink unavailable: %v", err)
	}
	if got, err := readSmall(verified, 1024); err == nil {
		t.Fatalf("read through replaced ancestor: %q", got)
	}
	if got, err := mediaDigest(context.Background(), verified, 1024); err == nil {
		t.Fatalf("hashed through replaced ancestor: %x", got)
	}
}
