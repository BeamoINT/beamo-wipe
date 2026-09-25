// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"os"
	"path/filepath"
	"testing"
)

func mediaFixture(t *testing.T) string {
	t.Helper()
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	fixtureFile(t, root, "START-HERE.html", "guide")
	fixtureFile(t, root, "live/filesystem.squashfs", "squash")
	fixtureFile(t, root, "desktop-build.json", `{"version":"test"}`)
	fixtureFile(t, root, "EFI/BOOT/BOOTX64.EFI", "MZfixture-not-executable")
	fixtureFile(t, root, "Start Beamo Wipe Linux", "launcher fixture")
	fixtureFile(t, root, "app", "launcher fixture")
	return root
}
func fixtureFile(t *testing.T, root, rel, content string) {
	t.Helper()
	path := filepath.Join(root, filepath.FromSlash(rel))
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0600); err != nil {
		t.Fatal(err)
	}
}
func TestPreparedWipeMediaAccepted(t *testing.T) {
	root := mediaFixture(t)
	got := inspectMedia(filepath.Join(root, "Start Beamo Wipe Linux"))
	if got.Problem != "" || len(got.Fingerprint) != 64 {
		t.Fatalf("%+v", got)
	}
}
func TestUnpreparedOrMismatchedMediaRefused(t *testing.T) {
	for _, rel := range []string{"START-HERE.html", "live/filesystem.squashfs", "desktop-build.json", "EFI/BOOT/BOOTX64.EFI"} {
		root := mediaFixture(t)
		if err := os.Remove(filepath.Join(root, filepath.FromSlash(rel))); err != nil {
			t.Fatal(err)
		}
		if mediaLayout(filepath.Join(root, "app")) {
			t.Fatal("accepted missing", rel)
		}
	}
}
func TestInvalidLoaderRefused(t *testing.T) {
	root := mediaFixture(t)
	fixtureFile(t, root, "EFI/BOOT/BOOTX64.EFI", "not a PE image")
	if mediaLayout(filepath.Join(root, "app")) {
		t.Fatal("accepted non-PE loader")
	}
}
func TestUnattendedInstallRequiresManualReview(t *testing.T) {
	for _, rel := range []string{"autounattend.xml", "unattend.xml", "autoinstall.yaml"} {
		root := mediaFixture(t)
		fixtureFile(t, root, rel, "automated install")
		m := inspectMedia(filepath.Join(root, "app"))
		if m.Problem != "unattended" {
			t.Fatalf("%+v", m)
		}
	}
}
func TestEmptyUnattendedInstallRequiresManualReview(t *testing.T) {
	root := mediaFixture(t)
	fixtureFile(t, root, "autounattend.xml", "")
	m := inspectMedia(filepath.Join(root, "app"))
	if m.Problem != "unattended" {
		t.Fatalf("%+v", m)
	}
}
func TestCaseInsensitiveMarkers(t *testing.T) {
	root := mediaFixture(t)
	if err := os.Rename(filepath.Join(root, "START-HERE.html"), filepath.Join(root, "start-here.html")); err != nil {
		t.Fatal(err)
	}
	if m := inspectMedia(filepath.Join(root, "app")); m.Problem != "" || len(m.Fingerprint) != 64 {
		t.Fatalf("%+v", m)
	}
}
func TestLinkedMarkerRefused(t *testing.T) {
	root := mediaFixture(t)
	path := filepath.Join(root, "START-HERE.html")
	if err := os.Rename(path, path+".real"); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(path+".real", path); err != nil {
		t.Skip("host does not allow test symlinks")
	}
	if mediaLayout(filepath.Join(root, "app")) {
		t.Fatal("followed linked marker")
	}
}

func TestLinkedLauncherRefusedEvenWhenUSBMarkersArePresent(t *testing.T) {
	root := mediaFixture(t)
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
	if got := inspectMedia(launcher); got.Problem != "media" {
		t.Fatalf("linked launcher was accepted as USB media: %+v", got)
	}
}
func TestMediaChangesInvalidateRestartFingerprint(t *testing.T) {
	root := mediaFixture(t)
	exe := filepath.Join(root, "app")
	original := inspectMedia(exe)
	fixtureFile(t, root, "EFI/BOOT/BOOTX64.EFI", "MZchanged-loader")
	changed := inspectMedia(exe)
	if original.Fingerprint == changed.Fingerprint {
		t.Fatal("loader not bound to plan")
	}
	s := Snapshot{UEFI: true, MediaID: "usb", Partitions: []string{"gpt:00000001-0000-0000-0000-000000000000:1:2048:4096"}, Entries: map[uint16][]byte{4: option(1)}, Layout: original.Fingerprint}
	p := makePlan(s)
	s.Layout = changed.Fingerprint
	if !p.Direct || makePlan(s).Fingerprint == p.Fingerprint {
		t.Fatal("layout omitted from plan")
	}
}
