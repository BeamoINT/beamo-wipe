// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestCopiedLauncherMetadataCannotClaimManufacturedUSB(t *testing.T) {
	previous := sourceCommit
	t.Cleanup(func() { sourceCommit = previous })
	sourceCommit = strings.Repeat("a", 40)
	root := t.TempDir()
	exe := filepath.Join(root, "Start Beamo Wipe Linux")
	if err := os.WriteFile(exe, []byte("copied launcher"), 0700); err != nil {
		t.Fatal(err)
	}
	metadata, err := json.Marshal(injectedIdentity{
		SourceCommit: sourceCommit,
		SourceSHA256: strings.Repeat("b", 64),
		BuildID:      "12345678-1234-1234-1234-123456789abc",
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "build-identity.json"), metadata, 0600); err != nil {
		t.Fatal(err)
	}
	if inspectMedia(exe).Problem != "media" {
		t.Fatal("fixture unexpectedly passes USB layout inspection")
	}
	identity := loadUSBIdentity(exe)
	if identity.Manufactured || identity.Status == "production" {
		t.Fatalf("copied files claim to be a manufactured USB: %+v", identity)
	}
}
