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

func TestLinuxMediaRequiresMeaningfulHardwareIdentifier(t *testing.T) {
	for _, tc := range []struct {
		name, serial, wwn string
		valid             bool
	}{
		{"blank serial", " ", "", false},
		{"zero serial", "0000000000000000", "", false},
		{"prefixed zero serial", "0x00000000", "", false},
		{"separator-padded zero serial", "00:00:00:00", "", false},
		{"zero WWN", "", "0x0000000000000000", false},
		{"separator-padded zero WWN", "", "00:00:00:00", false},
		{"bare zero WWN", "", "0000000000000000", false},
		{"unknown serial", " UNKNOWN ", "", false},
		{"not-applicable serial", "N/A", "", false},
		{"none WWN", "", "NONE", false},
		{"not available WWN", "", "not available", false},
		{"placeholder pair", "UNKNOWN", "N/A", false},
		{"placeholder serial with real WWN", "NONE", "0x5000c500aabbccdd", true},
		{"zero serial with real WWN", "0000000000000000", "0x5000c500aabbccdd", true},
		{"nonzero serial", "0000000000000001", "", true},
		{"real WWN", "", "0x5000c500aabbccdd", true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			body := strings.Replace(linuxFixture, `"serial":"BEAMO123"`,
				`"serial":"`+tc.serial+`","wwn":"`+tc.wwn+`"`, 1)
			_, _, err := linuxMedia([]byte(body), "/dev/sdb1")
			if (err == nil) != tc.valid {
				t.Fatalf("serial=%q wwn=%q: err=%v, want valid=%t", tc.serial, tc.wwn, err, tc.valid)
			}
		})
	}
}

func TestLinuxMediaRefusesContradictoryPartitionParent(t *testing.T) {
	// findmnt reports the launcher on /dev/sdb1, but a contradictory lsblk
	// tree attaches that path to the USB /dev/sda instead of SATA /dev/sdb.
	// Guided restart must not treat the internal source as the Beamo USB.
	inventory := `{"blockdevices":[
		{"path":"/dev/sda","type":"disk","tran":"usb","serial":"BEAMO123","size":8000000000,"maj:min":"8:0","ptuuid":"12345678","log-sec":512,
		 "children":[{"path":"/dev/sdb1","type":"part","partuuid":"12345678-01","start":2048,"size":2097152}]},
		{"path":"/dev/sdb","type":"disk","tran":"sata","serial":"INTERNAL","size":500000000000,"maj:min":"8:16","ptuuid":"87654321","log-sec":512}
	]}`
	if id, parts, err := linuxMedia([]byte(inventory), "/dev/sdb1"); err == nil {
		t.Fatalf("accepted internal /dev/sdb1 as USB /dev/sda: id=%s parts=%v", id, parts)
	}
}

func TestLinuxPartitionPathShapes(t *testing.T) {
	for _, tc := range []struct {
		disk, part string
		valid      bool
	}{
		{"/dev/sda", "/dev/sda1", true},
		{"/dev/sda", "/dev/sda10", true},
		{"/dev/nvme0n1", "/dev/nvme0n1p1", true},
		{"/dev/mmcblk0", "/dev/mmcblk0p2", true},
		{"/dev/sda", "/dev/sdb1", false},
		{"/dev/sda", "/dev/sdaa1", false},
		{"/dev/nvme0n1", "/dev/nvme0n11", false},
		{"/dev/sda", "/dev/sda0", false},
	} {
		if got := linuxPartitionOfDisk(tc.disk, tc.part); got != tc.valid {
			t.Errorf("disk=%q part=%q: got %t, want %t", tc.disk, tc.part, got, tc.valid)
		}
	}
}

func TestLinuxMediaReturnsOnlyMountedBootPartition(t *testing.T) {
	// The launcher and verified EFI loader are on /dev/sdb1. A firmware entry
	// for a different loader on /dev/sdb2 must not become a guided boot route.
	inventory := `{"blockdevices":[{"path":"/dev/sdb","type":"disk","tran":"usb","serial":"BEAMO123","size":8000000000,"maj:min":"8:16","ptuuid":"12345678","log-sec":512,
	 "children":[
	  {"path":"/dev/sdb1","type":"part","partuuid":"12345678-01","start":2048,"size":2097152},
	  {"path":"/dev/sdb2","type":"part","partuuid":"12345678-02","start":8192,"size":2097152}
	 ]}]}`
	_, parts, err := linuxMedia([]byte(inventory), "/dev/sdb1")
	if err != nil || len(parts) != 1 || parts[0] != "mbr:12345678:1:2048:4096" {
		t.Fatalf("unverified sibling partition became a boot route: %v %v", parts, err)
	}
	_, parts, err = linuxMedia([]byte(inventory), "/dev/sdb2")
	if err != nil || len(parts) != 1 || parts[0] != "mbr:12345678:2:8192:4096" {
		t.Fatalf("mounted second partition lost its own route: %v %v", parts, err)
	}
	if _, _, err := linuxMedia([]byte(inventory), "/dev/sdb"); err == nil {
		t.Fatal("whole-disk source inherited an unverified partition boot route")
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
