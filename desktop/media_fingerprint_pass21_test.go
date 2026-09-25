// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"path/filepath"
	"testing"
)

func TestMediaFingerprintSeparatesGuideAndLoaderPass21(t *testing.T) {
	root := mediaFixture(t)
	exe := filepath.Join(root, "app")
	fixtureFile(t, root, "START-HERE.html", "guide")
	fixtureFile(t, root, "EFI/BOOT/BOOTX64.EFI", "MZMZpayload")
	before := inspectMedia(exe)
	if before.Problem != "" || before.Fingerprint == "" {
		t.Fatalf("prepared media was not accepted: %+v", before)
	}
	// Both files change, but their bare concatenation remains identical.
	// The elevated recheck must notice the changed boot loader and guide.
	fixtureFile(t, root, "START-HERE.html", "guideMZ")
	fixtureFile(t, root, "EFI/BOOT/BOOTX64.EFI", "MZpayload")
	after := inspectMedia(exe)
	if after.Problem != "" || after.Fingerprint == before.Fingerprint {
		t.Fatalf("guide/loader boundary shift escaped media fingerprint: before=%+v after=%+v", before, after)
	}
}
