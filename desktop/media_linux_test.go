// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"context"
	"encoding/json"
	"os"
	"strings"
	"testing"
	"time"
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

// Exercise the actual installed utility, not a hand-authored JSON fixture.
// This catches loss of parent relationships when changing lsblk columns.
func TestLinuxInventoryRetainsPartitionParents(t *testing.T) {
	if os.Getenv("BEAMO_DESKTOP_NATIVE_INVENTORY_TEST") != "1" {
		t.Skip("native disk inventory requires an explicitly opted-in isolated worker")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	data, err := linuxInventory(ctx)
	if err != nil {
		t.Fatalf("native lsblk inventory failed: %v", err)
	}
	var inventory struct {
		Devices []linuxNode `json:"blockdevices"`
	}
	if err := json.Unmarshal(data, &inventory); err != nil {
		t.Fatal(err)
	}
	partitions := 0
	var inspect func(linuxNode, bool)
	inspect = func(node linuxNode, hasParent bool) {
		if node.Type == "part" {
			partitions++
			if !hasParent {
				t.Error("partition lost its parent in actual lsblk output")
			}
		}
		for _, child := range node.Children {
			inspect(child, true)
		}
	}
	for _, node := range inventory.Devices {
		inspect(node, false)
	}
	if partitions == 0 {
		t.Skip("worker exposes no partitions; virtual USB handoff coverage is required")
	}
}

func TestLinuxDuplicateMBRSignatureWithDifferentPartitionNumbers(t *testing.T) {
	var inventory struct {
		Devices []linuxNode `json:"blockdevices"`
	}
	if err := json.Unmarshal([]byte(linuxFixture), &inventory); err != nil {
		t.Fatal(err)
	}
	clone := inventory.Devices[0]
	clone.Path, clone.Serial, clone.MajMin = "/dev/sdc", "OTHER", "8:32"
	clone.Children = append([]linuxNode(nil), clone.Children...)
	clone.Children[0].Path = "/dev/sdc2"
	clone.Children[0].PartUUID = "12345678-02"
	inventory.Devices = append(inventory.Devices, clone)
	data, err := json.Marshal(inventory)
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := linuxMedia(data, "/dev/sdb1"); err == nil {
		t.Fatal("duplicate MBR signature accepted because partition numbers differ")
	}
	inventory.Devices[1].PTUUID = "87654321"
	inventory.Devices[1].Children[0].PartUUID = "87654321-02"
	data, err = json.Marshal(inventory)
	if err != nil {
		t.Fatal(err)
	}
	if _, parts, err := linuxMedia(data, "/dev/sdb1"); err != nil || len(parts) != 1 {
		t.Fatalf("distinct disk identity refused: %v %v", parts, err)
	}
}

func TestLinuxMBRLogicalSectorGeometry(t *testing.T) {
	for _, tc := range []struct{ name, sector, start, size, want string }{
		{"512", "512", "2048", "2097152", "mbr:12345678:1:2048:4096"},
		{"4k", "4096", "2048", "2097152", "mbr:12345678:1:256:512"},
		{"unaligned-start", "4096", "2049", "2097152", ""},
		{"unaligned-size", "4096", "2048", "2097153", ""},
		{"unknown-sector", "0", "2048", "2097152", ""},
	} {
		t.Run(tc.name, func(t *testing.T) {
			body := strings.NewReplacer(`"log-sec":512`, `"log-sec":`+tc.sector,
				`"start":2048`, `"start":`+tc.start, `"size":2097152`, `"size":`+tc.size).Replace(linuxFixture)
			_, parts, err := linuxMedia([]byte(body), "/dev/sdb1")
			if err != nil {
				t.Fatal(err)
			}
			if tc.want == "" {
				if len(parts) != 0 {
					t.Fatal(parts)
				}
				return
			}
			if len(parts) != 1 || parts[0] != tc.want {
				t.Fatal(parts)
			}
		})
	}
}
