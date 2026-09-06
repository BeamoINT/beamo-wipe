// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"strings"
	"testing"
)

const linuxFixture = `{"blockdevices":[{"path":"/dev/sdb","type":"disk","tran":"usb","serial":"BEAMO123","size":8000000000,"maj:min":"8:16","ptuuid":"12345678","log-sec":512,"children":[{"path":"/dev/sdb1","type":"part","partuuid":"12345678-01","start":2048,"size":2097152}]}]}`

func TestLinuxMediaIdentity(t *testing.T) {
	id, parts, err := linuxMedia([]byte(linuxFixture), "/dev/sdb1")
	if err != nil || id == "" || len(parts) != 1 || parts[0] != "mbr:12345678:1:2048:4096" {
		t.Fatalf("%s %v %v", id, parts, err)
	}
	for _, body := range []string{strings.ReplaceAll(linuxFixture, `"usb"`, `"sata"`), strings.ReplaceAll(linuxFixture, `"BEAMO123"`, `""`), `{"blockdevices":[]}`, `{"blockdevices":null}`} {
		if _, _, err := linuxMedia([]byte(body), "/dev/sdb1"); err == nil {
			t.Fatal("unidentified media accepted")
		}
	}
	if _, _, err := linuxMedia([]byte(linuxFixture), "/dev/sdc1"); err == nil {
		t.Fatal("different USB accepted")
	}
}
