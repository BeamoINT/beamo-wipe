// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestRunningIdentityUsesExecutableLocationInsteadOfArgvZero(t *testing.T) {
	oldArgs, oldCommit := os.Args, sourceCommit
	t.Cleanup(func() { os.Args, sourceCommit = oldArgs, oldCommit })
	sourceCommit = strings.Repeat("a", 40)
	root := mediaFixture(t)
	payload, err := json.Marshal(injectedIdentity{
		SourceCommit: sourceCommit,
		SourceSHA256: strings.Repeat("b", 64),
		BuildID:      "12345678-1234-1234-1234-123456789abc",
	})
	if err != nil {
		t.Fatal(err)
	}
	fixtureFile(t, root, "build-identity.json", string(payload))
	// A PATH launch may receive only a bare program name in argv[0], while
	// os.Executable still identifies the running launcher on the USB.
	os.Args = []string{"Start Beamo Wipe Linux", "--version"}
	identity := runningUSBIdentity(func() (string, error) {
		return filepath.Join(root, "Start Beamo Wipe Linux"), nil
	})
	if !identity.Manufactured || identity.Status != "production" {
		t.Fatalf("valid running USB was mislabeled when argv[0] was relative: %+v", identity)
	}
}

func TestLinkedLauncherCannotClaimManufacturedIdentity(t *testing.T) {
	oldCommit := sourceCommit
	t.Cleanup(func() { sourceCommit = oldCommit })
	sourceCommit = strings.Repeat("a", 40)
	root := mediaFixture(t)
	payload, err := json.Marshal(injectedIdentity{
		SourceCommit: sourceCommit,
		SourceSHA256: strings.Repeat("b", 64),
		BuildID:      "12345678-1234-1234-1234-123456789abc",
	})
	if err != nil {
		t.Fatal(err)
	}
	fixtureFile(t, root, "build-identity.json", string(payload))
	launcher := filepath.Join(root, "app")
	outside := filepath.Join(t.TempDir(), "other-launcher")
	if err := os.WriteFile(outside, []byte("not the USB launcher"), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(launcher); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, launcher); err != nil {
		t.Skip("host does not allow test symlinks")
	}
	if got := loadUSBIdentity(launcher); got.Manufactured || got.Status != "unavailable" {
		t.Fatalf("linked executable claimed manufactured USB identity: %+v", got)
	}
}

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

func TestUSBIdentityRejectsTrailingJSONTokens(t *testing.T) {
	origCommit := sourceCommit
	t.Cleanup(func() { sourceCommit = origCommit })
	sourceCommit = strings.Repeat("a", 40)
	root := mediaFixture(t)
	payload, _ := json.Marshal(injectedIdentity{
		SourceCommit: sourceCommit,
		SourceSHA256: strings.Repeat("b", 64),
		BuildID:      "12345678-1234-1234-1234-123456789abc",
	})
	for _, suffix := range []string{"}", "]", `{"extra":true}`} {
		t.Run(suffix, func(t *testing.T) {
			fixtureFile(t, root, "build-identity.json", string(payload)+suffix)
			got := loadUSBIdentity(filepath.Join(root, "app"))
			if got.Manufactured || got.Status != "unavailable" {
				t.Fatalf("accepted trailing JSON %q: %+v", suffix, got)
			}
		})
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
