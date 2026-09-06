// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"encoding/json"
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

func TestLinuxWorkerArchitecture(t *testing.T) {
	if !nativeX64() {
		t.Fatal("Linux desktop tests require a native x86_64 worker")
	}
}

func TestLinuxDuplicateMediaIdentitiesRefused(t *testing.T) {
	var inventory struct {
		Devices []linuxNode `json:"blockdevices"`
	}
	if err := json.Unmarshal([]byte(linuxFixture), &inventory); err != nil {
		t.Fatal(err)
	}
	clone := inventory.Devices[0]
	clone.Path = "/dev/sdc"
	clone.Serial = "OTHER"
	clone.MajMin = "8:32"
	clone.Children = append([]linuxNode(nil), clone.Children...)
	clone.Children[0].Path = "/dev/sdc1"
	inventory.Devices = append(inventory.Devices, clone)
	data, err := json.Marshal(inventory)
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := linuxMedia(data, "/dev/sdb1"); err == nil {
		t.Fatal("cloned partition identity accepted")
	}
}
