// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestWindowsGuidedRestartIsAlwaysRefused(t *testing.T) {
	if err := platformRestart(strings.Repeat("a", 64)); !errors.Is(err, errWindowsManual) {
		t.Fatalf("restart helper did not refuse Windows BootNext: %v", err)
	}
	if err := platformElevate(context.Background(), strings.Repeat("a", 64)); !errors.Is(err, errWindowsManual) {
		t.Fatalf("browser route did not refuse Windows BootNext: %v", err)
	}
	if relaunched, err := prepareDesktop(); relaunched || err != nil {
		t.Fatalf("manual boot instructions should not demand elevation: relaunched=%v err=%v", relaunched, err)
	}
}

func TestWindowsNativeReadOnlyPlatform(t *testing.T) {
	if !nativeX64() {
		t.Fatal("expected native AMD64 Windows test worker")
	}
	if win := windowsDirectory(); win == "" || !filepath.IsAbs(win) {
		t.Fatal("Windows directory API failed")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	s := platformProbe(ctx)
	if makePlan(s).Direct || (s.Problem != "media" && s.Problem != "legacy") {
		t.Fatalf("non-USB test executable was accepted: %s", s.Problem)
	}
}

func TestWindowsInventoryPowerShellRuntime(t *testing.T) {
	fixture := `$part=[pscustomobject]@{DiskNumber=5;Guid='{11111111-2222-3333-4444-555555555555}';PartitionNumber=1;Offset=1048576;Size=1073741824}
 $disk=[pscustomobject]@{Number=5;BusType='USB';IsBoot=$false;IsSystem=$false;SerialNumber='TESTONLY';UniqueId='TESTONLY';Size=2147483648;PartitionStyle='GPT';Signature=0;LogicalSectorSize=512}
 function Get-Partition { [CmdletBinding()]param($DriveLetter,$DiskNumber); if ($env:BEAMO_DUPLICATE -eq '1' -and !$DriveLetter -and $null -eq $DiskNumber) { @($part,$part) } else { $part } }
 function Get-Disk { [CmdletBinding()]param($Number); if ($env:BEAMO_DUPLICATE -eq '1' -and $null -eq $Number) { @($disk,$disk) } else { $disk } }
 `

	for _, tc := range []struct {
		name, extra, want string
		duplicate         bool
	}{
		{"gpt", "", "gpt:11111111-2222-3333-4444-555555555555:1:2048:2097152", false},
		{"gpt-4k", "$disk.LogicalSectorSize=4096;", "gpt:11111111-2222-3333-4444-555555555555:1:256:262144", false},
		{"unicode", "$disk.SerialNumber='TESTONLY-é-磁盘';$disk.UniqueId='TESTONLY-é-磁盘';", "gpt:11111111-2222-3333-4444-555555555555:1:2048:2097152", false},
		{"mbr-4k", "$disk.PartitionStyle='MBR';$disk.Signature=0x1234abcd;$disk.LogicalSectorSize=4096;", "mbr:1234abcd:1:256:262144", false},
		{"duplicate-gpt", "", "", true},
		{"mbr", "$disk.PartitionStyle='MBR';$disk.Signature=0x1234abcd;", "mbr:1234abcd:1:2048:2097152", false},
		{"duplicate-mbr", "$disk.PartitionStyle='MBR';$disk.Signature=0x1234abcd;", "", true},
		{"running-system", "$disk.IsSystem=$true;", "", false},
		{"non-usb", "$disk.BusType='SATA';", "", false},
		{"unidentified", "$disk.SerialNumber='';$disk.UniqueId='';", "", false},
		{"zero-identifiers", "$disk.SerialNumber='00000000';$disk.UniqueId='0x00000000';", "", false},
		{"separator-zero-identifiers", "$disk.SerialNumber='00:00-00';$disk.UniqueId='{00000000-0000-0000}';", "", false},
		{"placeholder-identifiers", "$disk.SerialNumber='UNKNOWN';$disk.UniqueId='N/A';", "", false},
		{"none-identifiers", "$disk.SerialNumber='NONE';$disk.UniqueId='not available';", "", false},
		{"real-unique-id-after-placeholder", "$disk.SerialNumber='UNKNOWN';$disk.UniqueId='USB-1234';", "gpt:11111111-2222-3333-4444-555555555555:1:2048:2097152", false},
		{"real-unique-id", "$disk.SerialNumber='00000000';$disk.UniqueId='USB-1234';", "gpt:11111111-2222-3333-4444-555555555555:1:2048:2097152", false},
		{"real-serial", "$disk.SerialNumber='USB-1234';$disk.UniqueId='0x00000000';", "gpt:11111111-2222-3333-4444-555555555555:1:2048:2097152", false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
			cmd := exec.CommandContext(ctx, filepath.Join(windowsDirectory(), "System32", "WindowsPowerShell", "v1.0", "powershell.exe"), "-NoProfile", "-NonInteractive", "-Command", fixture+tc.extra+windowsInventory)
			cmd.Env = append(os.Environ(), `BEAMO_LAUNCHER_FILE=X:\Start Beamo Wipe.exe`, "BEAMO_DUPLICATE=0")
			if tc.duplicate {
				cmd.Env[len(cmd.Env)-1] = "BEAMO_DUPLICATE=1"
			}
			out, err := cmd.Output()
			cancel()
			if tc.want == "" {
				if err == nil {
					t.Fatal("unsupported inventory accepted")
				}
				return
			}
			if err != nil {
				t.Fatalf("PowerShell inventory runtime: %v", err)
			}
			var got struct {
				Media      string   `json:"media"`
				Partitions []string `json:"partitions"`
			}
			if tc.name == "unicode" && !strings.Contains(string(out), "TESTONLY-é-磁盘") {
				t.Fatalf("inventory identity lost Unicode: %s", out)
			}
			var mediaFields []string
			if json.Unmarshal(out, &got) != nil || json.Unmarshal([]byte(got.Media), &mediaFields) != nil || len(mediaFields) != 4 || mediaFields[0] != "5" || mediaFields[3] != "2147483648" || len(got.Partitions) != 1 || got.Partitions[0] != tc.want {
				t.Fatalf("invalid fixture result: %s", out)
			}
		})
	}
}
