// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"encoding/json"
	"path/filepath"
	"strings"
	"testing"
)

func TestDirtyLauncherCannotUseCleanUSBIdentity(t *testing.T) {
	oldCommit, oldDirty := sourceCommit, sourceDirty
	t.Cleanup(func() { sourceCommit, sourceDirty = oldCommit, oldDirty })
	sourceCommit = strings.Repeat("a", 40)
	sourceDirty = "true"
	root := mediaFixture(t)
	metadata, err := json.Marshal(injectedIdentity{
		SourceCommit: sourceCommit,
		SourceSHA256: strings.Repeat("b", 64),
		BuildID:      "12345678-1234-1234-1234-123456789abc",
		SourceDirty:  false,
	})
	if err != nil {
		t.Fatal(err)
	}
	fixtureFile(t, root, "build-identity.json", string(metadata))
	identity := loadUSBIdentity(filepath.Join(root, "Start Beamo Wipe Linux"))
	if identity.Manufactured || identity.Status == "production" {
		t.Fatalf("dirty launcher accepted clean metadata: %+v", identity)
	}
	// Matching dirty metadata must remain legible as a development build.
	metadata, err = json.Marshal(injectedIdentity{
		SourceCommit: sourceCommit,
		SourceSHA256: strings.Repeat("b", 64),
		BuildID:      "12345678-1234-1234-1234-123456789abc",
		SourceDirty:  true,
	})
	if err != nil {
		t.Fatal(err)
	}
	fixtureFile(t, root, "build-identity.json", string(metadata))
	identity = loadUSBIdentity(filepath.Join(root, "Start Beamo Wipe Linux"))
	if identity.Manufactured || identity.Status != "dirty" {
		t.Fatalf("matching dirty metadata was not recognized: %+v", identity)
	}
}
