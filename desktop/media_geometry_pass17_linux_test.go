// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"strings"
	"testing"
)

func TestLinuxMediaRefusesImpossibleDiskGeometryPass17(t *testing.T) {
	for _, tc := range []struct {
		name, body string
	}{
		{"zero disk", strings.Replace(linuxFixture, `"size":8000000000`, `"size":0`, 1)},
		{"negative disk", strings.Replace(linuxFixture, `"size":8000000000`, `"size":-1`, 1)},
		{"partition exceeds disk", strings.Replace(linuxFixture, `"size":2097152`, `"size":9000000000`, 1)},
		{"partition starts beyond disk", strings.Replace(linuxFixture, `"start":2048`, `"start":20000000`, 1)},
	} {
		t.Run(tc.name, func(t *testing.T) {
			_, parts, err := linuxMedia([]byte(tc.body), "/dev/sdb1")
			if err == nil && len(parts) != 0 {
				t.Fatalf("impossible USB geometry authorized firmware route: %v", parts)
			}
		})
	}
	_, parts, err := linuxMedia([]byte(linuxFixture), "/dev/sdb1")
	if err != nil || len(parts) != 1 {
		t.Fatalf("valid USB geometry lost its firmware route: %v, %v", parts, err)
	}
}

func TestLinuxMediaRefusesMalformedMBRSignaturePass17(t *testing.T) {
	body := strings.Replace(linuxFixture, `"ptuuid":"12345678"`, `"ptuuid":"12zz5678"`, 1)
	body = strings.Replace(body, `"partuuid":"12345678-01"`, `"partuuid":"12zz5678-01"`, 1)
	_, parts, err := linuxMedia([]byte(body), "/dev/sdb1")
	if err == nil && len(parts) != 0 {
		t.Fatalf("malformed signature authorized firmware route: %v", parts)
	}
}

func TestLinuxGPTMediaGeometryPass17(t *testing.T) {
	guid := "11111111-2222-3333-4444-555555555555"
	body := strings.Replace(linuxFixture, `"ptuuid":"12345678"`, `"ptuuid":"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"`, 1)
	body = strings.Replace(body, `"partuuid":"12345678-01"`, `"partuuid":"`+guid+`"`, 1)
	_, parts, err := linuxMedia([]byte(body), "/dev/sdb1")
	if err != nil || len(parts) != 1 || parts[0] != "gpt:"+guid+":1:2048:4096" {
		t.Fatalf("valid GPT route lost: %v, %v", parts, err)
	}
	tooLarge := strings.Replace(body, `"size":2097152`, `"size":9000000000`, 1)
	_, parts, err = linuxMedia([]byte(tooLarge), "/dev/sdb1")
	if err == nil && len(parts) != 0 {
		t.Fatalf("out-of-range GPT partition authorized route: %v", parts)
	}
}
