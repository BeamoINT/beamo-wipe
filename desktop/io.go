// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"bytes"
	"errors"
	"io"
	"os"
	"os/exec"
	"regexp"
)

var guidPattern = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)

func validGUID(s string) bool {
	return guidPattern.MatchString(s) && s != "00000000-0000-0000-0000-000000000000"
}
func readSmall(path string, max int64) ([]byte, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	b, err := io.ReadAll(io.LimitReader(f, max+1))
	if err != nil {
		return nil, err
	}
	if int64(len(b)) > max {
		return nil, errors.New("input too large")
	}
	return b, nil
}

type limitedBuffer struct {
	bytes.Buffer
	max int
}

func (b *limitedBuffer) Write(p []byte) (int, error) {
	if b.Len()+len(p) > b.max {
		return 0, errors.New("output too large")
	}
	return b.Buffer.Write(p)
}
func boundedOutput(cmd *exec.Cmd, max int) ([]byte, error) {
	b := &limitedBuffer{max: max}
	cmd.Stdout = b
	cmd.Stderr = io.Discard
	err := cmd.Run()
	return b.Bytes(), err
}
