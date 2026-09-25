//go:build !windows

// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"syscall"
)

// A media marker or any of its ancestors can be replaced after the media
// directory check. Pin each directory before opening the next component, and
// reject a link substituted for any component.
func openRegularInput(path string) (*os.File, error) {
	if !filepath.IsAbs(path) {
		return nil, errors.New("input path is not absolute")
	}
	parts := strings.Split(strings.TrimPrefix(filepath.Clean(path), string(filepath.Separator)), string(filepath.Separator))
	if len(parts) == 0 || parts[0] == "" {
		return nil, errors.New("input path has no file name")
	}
	dir, err := os.OpenRoot(string(filepath.Separator))
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
	f, err := dir.OpenFile(base, os.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0)
	if err != nil {
		return nil, err
	}
	opened, openErr := f.Stat()
	after, afterErr := dir.Lstat(base)
	if openErr != nil || afterErr != nil || !opened.Mode().IsRegular() || !after.Mode().IsRegular() || !os.SameFile(before, opened) || !os.SameFile(before, after) {
		_ = f.Close()
		return nil, errors.New("input is not a regular file")
	}
	return f, nil
}
