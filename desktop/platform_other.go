// SPDX-License-Identifier: GPL-3.0-or-later
//go:build !linux && !windows

package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
)

func platformProbe(context.Context) Snapshot        { return Snapshot{Problem: "platform"} }
func platformRestart(string) error                  { return errors.New("unsupported platform") }
func platformElevate(context.Context, string) error { return errors.New("unsupported platform") }
func openBrowser(url string) error                  { return exec.Command("/usr/bin/open", url).Start() }
func notifyFailure(message string)                  { fmt.Fprintln(os.Stderr, message) }
func prepareDesktop() (bool, error)                 { return false, nil }
