// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"path/filepath"
	"strings"
	"testing"
)

func TestUSBIdentityRejectsDuplicateDirtyField(t *testing.T) {
	oldCommit, oldDirty := sourceCommit, sourceDirty
	t.Cleanup(func() { sourceCommit, sourceDirty = oldCommit, oldDirty })
	sourceCommit = strings.Repeat("a", 40)
	sourceDirty = "false"
	root := mediaFixture(t)
	fixtureFile(t, root, "build-identity.json", `{"source_commit":"`+sourceCommit+`","source_sha256":"`+strings.Repeat("b", 64)+`","build_id":"12345678-1234-1234-1234-123456789abc","source_dirty":true,"source_dirty":false}`)
	got := loadUSBIdentity(filepath.Join(root, "Start Beamo Wipe Linux"))
	if got.Manufactured || got.Status != "unavailable" {
		t.Fatalf("accepted ambiguous source status as manufactured: %+v", got)
	}
}

func TestUSBIdentityRequiresExplicitDirtyField(t *testing.T) {
	oldCommit, oldDirty := sourceCommit, sourceDirty
	t.Cleanup(func() { sourceCommit, sourceDirty = oldCommit, oldDirty })
	sourceCommit = strings.Repeat("a", 40)
	sourceDirty = "false"
	root := mediaFixture(t)
	fixtureFile(t, root, "build-identity.json", `{"source_commit":"`+sourceCommit+`","source_sha256":"`+strings.Repeat("b", 64)+`","build_id":"12345678-1234-1234-1234-123456789abc"}`)
	got := loadUSBIdentity(filepath.Join(root, "Start Beamo Wipe Linux"))
	if got.Manufactured || got.Status != "unavailable" {
		t.Fatalf("accepted identity without source_dirty: %+v", got)
	}
}
