// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"path/filepath"
	"regexp"
)

var (
	commitRe  = regexp.MustCompile(`^[0-9a-f]{40}$`)
	sha256Re  = regexp.MustCompile(`^[0-9a-f]{64}$`)
	buildIDRe = regexp.MustCompile(`^(?:[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}|local)$`)
)

type identityInfo struct {
	Label        string
	BuildID      string
	Commit       string
	Status       string
	Manufactured bool
}

type injectedIdentity struct {
	SourceCommit string `json:"source_commit"`
	SourceSHA256 string `json:"source_sha256"`
	BuildID      string `json:"build_id"`
	SourceDirty  bool   `json:"source_dirty"`
}

var usbIdentity = stubIdentity()

func stubIdentity() identityInfo {
	return identityInfo{
		Label:  "This launcher is not from a manufactured USB image.",
		Status: "unavailable",
	}
}

func previewIdentity() identityInfo {
	return identityInfo{
		Label:  "This launcher is a preview. It is not a manufactured USB image.",
		Status: "unavailable",
	}
}

func formatIdentity(info identityInfo) string {
	buildID, commit := info.BuildID, info.Commit
	if buildID == "" {
		buildID = "not packaged"
	}
	if commit == "" {
		commit = "not packaged"
	}
	return fmt.Sprintf("%s\nRelease build: %s\nSource: %s\nBuild status: %s\n", info.Label, buildID, commit, info.Status)
}

func loadUSBIdentity(exe string) identityInfo {
	stub := stubIdentity()
	root := filepath.Dir(exe)
	path, err := mediaFile(root, "build-identity.json")
	if err != nil {
		return stub
	}
	raw, err := readSmall(path, 4096)
	if err != nil {
		return stub
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	var injected injectedIdentity
	if err := dec.Decode(&injected); err != nil {
		return stub
	}
	if dec.More() {
		return stub
	}
	if !commitRe.MatchString(injected.SourceCommit) || !sha256Re.MatchString(injected.SourceSHA256) || !buildIDRe.MatchString(injected.BuildID) {
		return stub
	}
	status := "production"
	switch {
	case injected.SourceCommit != sourceCommit:
		status = "source mismatch"
	case injected.SourceDirty:
		status = "dirty"
	case injected.BuildID == "local":
		status = "development"
	}
	info := identityInfo{BuildID: injected.BuildID, Commit: injected.SourceCommit, Status: status}
	switch status {
	case "production":
		info.Label = "This USB is a manufactured Beamo Wipe image."
		info.Manufactured = true
	case "development":
		info.Label = "This USB is a development image, not a manufactured release."
	case "dirty":
		info.Label = "This USB was built from changed source. It is not a manufactured release."
	default:
		info.Label = "This launcher does not match the USB image identity."
	}
	return info
}
