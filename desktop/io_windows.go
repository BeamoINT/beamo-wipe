// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
)

func windowsInputPath(path string) (string, []string, error) {
	clean := filepath.Clean(path)
	if !filepath.IsAbs(clean) {
		return "", nil, errors.New("input path is not absolute")
	}
	volume := filepath.VolumeName(clean)
	rest := clean[len(volume):]
	// VolumeName treats the UNC marker as the whole volume for this extended
	// spelling. Keep its server and share in the pinned root as well.
	if strings.EqualFold(volume, `\\?\UNC`) || strings.EqualFold(volume, `\??\UNC`) {
		if len(rest) == 0 || !os.IsPathSeparator(rest[0]) {
			return "", nil, errors.New("input path has no UNC share")
		}
		components := strings.Split(filepath.ToSlash(rest[1:]), "/")
		if len(components) < 3 || components[0] == "" || components[1] == "" {
			return "", nil, errors.New("input path has no UNC share or file name")
		}
		volume += string(filepath.Separator) + components[0] + string(filepath.Separator) + components[1]
		rest = string(filepath.Separator) + strings.Join(components[2:], string(filepath.Separator))
	}
	if volume == "" || len(rest) < 2 || !os.IsPathSeparator(rest[0]) {
		return "", nil, errors.New("input path has no file name")
	}
	parts := strings.Split(filepath.ToSlash(rest[1:]), "/")
	return volume + string(filepath.Separator), parts, nil
}

func openRegularInput(path string) (*os.File, error) {
	volumeRoot, parts, err := windowsInputPath(path)
	if err != nil {
		return nil, err
	}
	// OpenRoot pins the drive or UNC share. Every subsequent operation is
	// relative to a pinned directory handle, including after a rename.
	dir, err := os.OpenRoot(volumeRoot)
	if err != nil {
		return nil, err
	}
	defer func() { _ = dir.Close() }()
	for _, component := range parts[:len(parts)-1] {
		before, err := dir.Lstat(component)
		if err != nil {
			return nil, err
		}
		if !before.IsDir() {
			return nil, errors.New("input ancestor is not a directory")
		}
		next, err := dir.OpenRoot(component)
		if err != nil {
			return nil, err
		}
		opened, openErr := next.Stat(".")
		after, afterErr := dir.Lstat(component)
		if openErr != nil || afterErr != nil || !after.IsDir() || !os.SameFile(before, opened) || !os.SameFile(before, after) {
			_ = next.Close()
			return nil, errors.New("input ancestor changed")
		}
		_ = dir.Close()
		dir = next
	}
	base := parts[len(parts)-1]
	before, err := dir.Lstat(base)
	if err != nil {
		return nil, err
	}
	if !before.Mode().IsRegular() {
		return nil, errors.New("input is not a regular file")
	}
	f, err := dir.Open(base)
	if err != nil {
		return nil, err
	}
	opened, openErr := f.Stat()
	after, afterErr := dir.Lstat(base)
	if openErr != nil || afterErr != nil || !opened.Mode().IsRegular() || !after.Mode().IsRegular() || !os.SameFile(before, opened) || !os.SameFile(before, after) {
		_ = f.Close()
		return nil, errors.New("input changed while opening")
	}
	return f, nil
}
