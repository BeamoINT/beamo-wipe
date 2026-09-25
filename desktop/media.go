// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// A slow or unreadable USB falls back to manual boot. Both the browser check
// and elevated recheck use the same bound, so neither can accept stale bytes.
const mediaProbeTimeout = 60 * time.Second

const maxSquashfsBytes int64 = (4 << 30) - 1 // The shipped USB is FAT32.

// lsblk START is in 512-byte sectors and SIZE is in bytes. A partition used
// to identify the USB must fit inside its reported disk; impossible geometry
// cannot establish an exact firmware boot route.
func partitionWithinDisk(diskBytes, startSectors, partBytes uint64) bool {
	if diskBytes == 0 || startSectors == 0 || partBytes == 0 || startSectors > diskBytes/512 {
		return false
	}
	startBytes := startSectors * 512
	return partBytes <= diskBytes-startBytes
}

func parseMBRSignature(text string) (uint32, bool) {
	if len(text) != 8 {
		return 0, false
	}
	for _, c := range text {
		if !((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F')) {
			return 0, false
		}
	}
	n, err := strconv.ParseUint(text, 16, 32)
	return uint32(n), err == nil && n != 0
}

func gptFirmwareRoute(partUUID, tableUUID string, partition uint32, start, size uint64) string {
	// A GUID-shaped partition identifier on an MBR or unidentified disk is
	// contradictory inventory, not evidence for a GPT HD() boot path.
	if validGUID(strings.ToLower(partUUID)) && validGUID(strings.ToLower(tableUUID)) && partition != 0 && start != 0 && size != 0 {
		return fmt.Sprintf("gpt:%s:%d:%d:%d", strings.ToLower(partUUID), partition, start, size)
	}
	return ""
}

type contextReader struct {
	ctx context.Context
	r   io.Reader
}

func (r contextReader) Read(p []byte) (int, error) {
	if err := r.ctx.Err(); err != nil {
		return 0, err
	}
	return r.r.Read(p)
}

// Hash an opened regular file rather than trusting timestamps. FAT timestamps
// are coarse enough that a same-size edit may retain the old timestamp.
func mediaDigest(ctx context.Context, path string, max int64) ([]byte, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	before, err := os.Lstat(path)
	if err != nil || !before.Mode().IsRegular() || before.Size() <= 0 || before.Size() > max {
		return nil, errors.New("invalid media file")
	}
	f, err := openRegularInput(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	opened, err := f.Stat()
	if err != nil || !os.SameFile(before, opened) {
		return nil, errors.New("media file changed")
	}
	h := sha256.New()
	n, err := io.CopyBuffer(h, contextReader{ctx, io.LimitReader(f, max+1)}, make([]byte, 1<<20))
	if err != nil {
		return nil, err
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	after, err := os.Lstat(path)
	if err != nil || !os.SameFile(opened, after) || n != before.Size() {
		return nil, errors.New("media file changed")
	}
	return h.Sum(nil), nil
}

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
	st, err := os.Lstat(path)
	if err != nil {
		return "", err
	}
	if !st.Mode().IsRegular() || st.Size() == 0 {
		return "", errors.New("invalid media file")
	}
	return path, nil
}

type mediaInfo struct{ Fingerprint, Problem string }

func mediaContextProblem(err error) string {
	if errors.Is(err, context.DeadlineExceeded) {
		return "timeout"
	}
	return "cancelled"
}

func inspectMedia(exe string) mediaInfo {
	return inspectMediaWithContext(context.Background(), exe, true)
}

func inspectMediaContext(ctx context.Context, exe string) mediaInfo {
	return inspectMediaWithContext(ctx, exe, true)
}

func inspectMediaWithContext(ctx context.Context, exe string, fingerprint bool) mediaInfo {
	m := mediaInfo{Problem: "media"}
	if err := ctx.Err(); err != nil {
		m.Problem = mediaContextProblem(err)
		return m
	}
	// Inspect the executable itself as well as the surrounding USB files. A
	// link beside valid markers must not identify bytes loaded from elsewhere.
	exeInfo, err := os.Lstat(exe)
	if err != nil || !exeInfo.Mode().IsRegular() {
		return m
	}
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
	// Recognizable automated installers require the manual boot path, where the
	// operator can review how that media was prepared before proceeding. A
	// matching name blocks even if it is a link or has ambiguous casing: the
	// regular-file resolver must not make a present installer look absent.
	entries, err := os.ReadDir(root)
	if err != nil {
		return m
	}
	for _, entry := range entries {
		for _, name := range []string{"autounattend.xml", "unattend.xml", "autoinstall.yaml"} {
			if strings.EqualFold(entry.Name(), name) {
				m.Problem = "unattended"
				return m
			}
		}
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
	if !fingerprint {
		m.Problem = ""
		return m
	}
	// A layout is evidence of compatibility, never authenticity or boot success.
	h := sha256.New()
	// Frame each file with its path and fixed-size digest. Concatenating the
	// guide and loader bytes lets edits move bytes across their boundary while
	// leaving the restart fingerprint unchanged.
	guideDigest := sha256.Sum256(raw)
	loaderDigest := sha256.Sum256(b)
	h.Write([]byte("START-HERE.html\x00"))
	h.Write(guideDigest[:])
	h.Write([]byte("EFI/BOOT/BOOTX64.EFI\x00"))
	h.Write(loaderDigest[:])
	// The elevated helper is executed from this path after the browser check.
	// Bind its bytes to the plan so a replaced launcher cannot reuse a prior
	// media fingerprint while the surrounding USB files remain unchanged.
	exeDigest, err := mediaDigest(ctx, exe, 64<<20)
	if err != nil {
		if ctxErr := ctx.Err(); ctxErr != nil {
			m.Problem = mediaContextProblem(ctxErr)
		}
		return m
	}
	h.Write([]byte("launcher\x00"))
	h.Write(exeDigest)
	for _, rel := range []string{"live/filesystem.squashfs", "desktop-build.json"} {
		p, err := mediaFile(root, rel)
		if err != nil {
			return m
		}
		max := int64(1 << 20)
		if rel == "live/filesystem.squashfs" {
			max = maxSquashfsBytes
		}
		digest, err := mediaDigest(ctx, p, max)
		if err != nil {
			if ctxErr := ctx.Err(); ctxErr != nil {
				m.Problem = mediaContextProblem(ctxErr)
			}
			return m
		}
		h.Write([]byte(rel))
		h.Write([]byte{0})
		h.Write(digest)
	}
	m.Fingerprint = hex.EncodeToString(h.Sum(nil))
	m.Problem = ""
	return m
}

func mediaLayout(exe string) bool {
	return inspectMediaWithContext(context.Background(), exe, false).Problem == ""
}
