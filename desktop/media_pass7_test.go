// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestLinkedUnattendedFileStillBlocksGuidedRestart(t *testing.T) {
	root := mediaFixture(t)
	target := filepath.Join(root, "unattended-content.xml")
	if err := os.WriteFile(target, []byte("automated setup"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, filepath.Join(root, "Autounattend.xml")); err != nil {
		t.Skipf("host cannot create test symlink: %v", err)
	}
	if got := inspectMedia(filepath.Join(root, "app")); got.Problem != "unattended" {
		t.Fatalf("linked unattended file was ignored: %+v", got)
	}
}

func TestAmbiguousUnattendedNameStillBlocksGuidedRestart(t *testing.T) {
	root := mediaFixture(t)
	first := filepath.Join(root, "autounattend.xml")
	second := filepath.Join(root, "Autounattend.xml")
	if err := os.WriteFile(first, []byte("first"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(second, []byte("second"), 0600); err != nil {
		t.Fatal(err)
	}
	firstInfo, firstErr := os.Stat(first)
	secondInfo, secondErr := os.Stat(second)
	if firstErr != nil || secondErr != nil {
		t.Fatalf("stat unattended fixtures: %v, %v", firstErr, secondErr)
	}
	if os.SameFile(firstInfo, secondInfo) {
		t.Skip("host filesystem is case insensitive")
	}
	if got := inspectMedia(filepath.Join(root, "app")); got.Problem != "unattended" {
		t.Fatalf("ambiguous unattended name was ignored: %+v", got)
	}
}

func TestSameSizeMediaEditsInvalidateRestartFingerprint(t *testing.T) {
	for _, tc := range []struct{ name, rel, changed string }{
		{"boot payload", "live/filesystem.squashfs", "squosh"},
		{"build metadata", "desktop-build.json", `{"version":"best"}`},
	} {
		t.Run(tc.name, func(t *testing.T) {
			root := mediaFixture(t)
			exe := filepath.Join(root, "app")
			before := inspectMedia(exe)
			if before.Problem != "" {
				t.Fatal(before)
			}
			path := filepath.Join(root, filepath.FromSlash(tc.rel))
			initial, err := os.Stat(path)
			if err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(path, []byte(tc.changed), 0600); err != nil {
				t.Fatal(err)
			}
			if err := os.Chtimes(path, initial.ModTime(), initial.ModTime()); err != nil {
				t.Fatal(err)
			}
			modified, err := os.Stat(path)
			if err != nil {
				t.Fatal(err)
			}
			if modified.Size() != initial.Size() || !modified.ModTime().Equal(initial.ModTime()) {
				t.Skip("host could not preserve media size and modification time")
			}
			after := inspectMedia(exe)
			if after.Problem != "" || after.Fingerprint == before.Fingerprint {
				t.Fatalf("same-size edit escaped restart recheck: before=%+v after=%+v", before, after)
			}
		})
	}
}

func TestMediaInspectionDoesNotAcceptCancelledOrExpiredChecks(t *testing.T) {
	root := mediaFixture(t)
	exe := filepath.Join(root, "app")
	cancelled, cancel := context.WithCancel(context.Background())
	cancel()
	expired, stop := context.WithDeadline(context.Background(), time.Now().Add(-time.Second))
	defer stop()
	for _, tc := range []struct {
		ctx  context.Context
		want string
	}{{cancelled, "cancelled"}, {expired, "timeout"}} {
		got := inspectMediaContext(tc.ctx, exe)
		if got.Problem != tc.want || got.Fingerprint != "" {
			t.Fatalf("incomplete media inspection was accepted: %+v", got)
		}
	}
}
