// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"encoding/json"
	"path/filepath"
	"strings"
	"testing"
)

func TestMissingBuildIdentityDoesNotRefuseMedia(t *testing.T) {
	root := mediaFixture(t)
	got := inspectMedia(filepath.Join(root, "Start Beamo Wipe Linux"))
	if got.Problem != "" || len(got.Fingerprint) != 64 {
		t.Fatalf("older media without identity JSON must still be recognized: %+v", got)
	}
	ident := loadUSBIdentity(filepath.Join(root, "Start Beamo Wipe Linux"))
	if ident.Manufactured || ident.Status != "unavailable" || !strings.Contains(ident.Label, "not from a manufactured USB image") {
		t.Fatalf("%+v", ident)
	}
}

func TestUSBIdentityMatchesInjectedJSON(t *testing.T) {
	origCommit := sourceCommit
	t.Cleanup(func() { sourceCommit = origCommit })
	commit := strings.Repeat("a", 40)
	sourceCommit = commit
	root := mediaFixture(t)
	payload, _ := json.Marshal(injectedIdentity{
		SourceCommit: commit,
		SourceSHA256: strings.Repeat("b", 64),
		BuildID:      "12345678-1234-1234-1234-123456789abc",
		SourceDirty:  false,
	})
	fixtureFile(t, root, "build-identity.json", string(payload)+"\n")
	ident := loadUSBIdentity(filepath.Join(root, "Start Beamo Wipe Linux"))
	if !ident.Manufactured || ident.Status != "production" || ident.BuildID != "12345678-1234-1234-1234-123456789abc" {
		t.Fatalf("%+v", ident)
	}
	if ident.Label != "This USB is a manufactured Beamo Wipe image." {
		t.Fatalf("%+v", ident)
	}
}

func TestUSBIdentityMismatchIsLabeledNotRefused(t *testing.T) {
	origCommit := sourceCommit
	t.Cleanup(func() { sourceCommit = origCommit })
	sourceCommit = strings.Repeat("c", 40)
	root := mediaFixture(t)
	payload, _ := json.Marshal(injectedIdentity{
		SourceCommit: strings.Repeat("a", 40),
		SourceSHA256: strings.Repeat("b", 64),
		BuildID:      "12345678-1234-1234-1234-123456789abc",
		SourceDirty:  false,
	})
	fixtureFile(t, root, "build-identity.json", string(payload)+"\n")
	if inspectMedia(filepath.Join(root, "app")).Problem != "" {
		t.Fatal("identity mismatch must not fail-close media recognition")
	}
	ident := loadUSBIdentity(filepath.Join(root, "app"))
	if ident.Manufactured || ident.Status != "source mismatch" {
		t.Fatalf("%+v", ident)
	}
}

func TestInvalidIdentityJSONIsUnavailable(t *testing.T) {
	root := mediaFixture(t)
	fixtureFile(t, root, "build-identity.json", `{"source_commit":"`+strings.Repeat("a", 40)+`","hostname":"secret"}`)
	ident := loadUSBIdentity(filepath.Join(root, "app"))
	if ident.Status != "unavailable" || ident.BuildID != "" || ident.Manufactured {
		t.Fatalf("%+v", ident)
	}
}

func TestPlanViewAlwaysIncludesIdentity(t *testing.T) {
	v := planView(Plan{Direct: true}, false)
	if v.IdentityLabel == "" || v.BuildStatus == "" || v.Version == "" {
		t.Fatalf("%+v", v)
	}
	preview := planView(Plan{Direct: true}, true)
	if preview.Manufactured || !strings.Contains(preview.IdentityLabel, "preview") {
		t.Fatalf("%+v", preview)
	}
}
