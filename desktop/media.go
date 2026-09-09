// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
)

// Resolve the fixed, bounded marker paths case-insensitively on FAT/NTFS and
// case-sensitive staging filesystems. Never follow links or ambiguous casing.
func mediaFile(root, rel string) (string, error) {
	if !filepath.IsLocal(rel) {
		return "", errors.New("invalid media path")
	}
	path := root
	for _, component := range strings.Split(filepath.ToSlash(rel), "/") {
		entries, err := os.ReadDir(path)
		if err != nil {
			return "", err
		}
		found := ""
		for _, e := range entries {
			if strings.EqualFold(e.Name(), component) {
				if found != "" {
					return "", errors.New("ambiguous media path")
				}
				found = e.Name()
			}
		}
		if found == "" {
			return "", os.ErrNotExist
		}
		path = filepath.Join(path, found)
		st, err := os.Lstat(path)
		if err != nil {
			return "", err
		}
		if st.Mode()&os.ModeSymlink != 0 {
			return "", errors.New("linked media path")
		}
	}
	st, err := os.Stat(path)
	if err != nil {
		return "", err
	}
	if !st.Mode().IsRegular() || st.Size() == 0 {
		return "", errors.New("invalid media file")
	}
	return path, nil
}

type mediaInfo struct{ Fingerprint, Problem string }

func inspectMedia(exe string) mediaInfo {
	m := mediaInfo{Problem: "media"}
	root := filepath.Dir(exe)
	resolved, err := filepath.EvalSymlinks(root)
	if err != nil || resolved != root {
		return m
	}
	guide, err := mediaFile(root, "START-HERE.html")
	if err != nil {
		return m
	}
	if _, err := mediaFile(root, "live/filesystem.squashfs"); err != nil {
		return m
	}
	if _, err := mediaFile(root, "desktop-build.json"); err != nil {
		return m
	}
	has := func(rel string) bool { _, err := mediaFile(root, rel); return err == nil }
	// Recognizable automated installers require the manual boot path, where the
	// operator can review how that media was prepared before proceeding.
	if has("autounattend.xml") || has("unattend.xml") || has("autoinstall.yaml") {
		m.Problem = "unattended"
		return m
	}
	loader, err := mediaFile(root, "EFI/BOOT/BOOTX64.EFI")
	if err != nil {
		return m
	}
	b, err := readSmall(loader, 64<<20)
	if err != nil || len(b) < 2 || string(b[:2]) != "MZ" {
		return m
	}
	raw, err := readSmall(guide, 1<<20)
	if err != nil {
		return m
	}
	// A layout is evidence of compatibility, never authenticity or boot success.
	h := sha256.New()
	h.Write(raw)
	h.Write(b)
	for _, rel := range []string{"live/filesystem.squashfs", "desktop-build.json"} {
		p, err := mediaFile(root, rel)
		if err != nil {
			return m
		}
		st, err := os.Stat(p)
		if err != nil {
			return m
		}
		metadata, _ := json.Marshal([]any{rel, st.Size(), st.ModTime().UnixNano()})
		h.Write(metadata)
	}
	m.Fingerprint = hex.EncodeToString(h.Sum(nil))
	m.Problem = ""
	return m
}

func mediaLayout(exe string) bool { return inspectMedia(exe).Problem == "" }
