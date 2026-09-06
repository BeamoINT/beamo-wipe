// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
	"unsafe"
)

func TestWindowsNativeReadOnlyPlatform(t *testing.T) {
	if win := windowsDirectory(); win == "" || !filepath.IsAbs(win) {
		t.Fatal("Windows directory API failed")
	}
	if unsafe.Sizeof(shellExecuteInfo{}) != 112 || unsafe.Offsetof(shellExecuteInfo{}.Process) != 104 {
		t.Fatal("SHELLEXECUTEINFOW ABI mismatch")
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
 function Get-Disk { [CmdletBinding()]param($Number); $disk }
 `
	for _, duplicate := range []bool{false, true} {
		ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
		cmd := exec.CommandContext(ctx, filepath.Join(windowsDirectory(), "System32", "WindowsPowerShell", "v1.0", "powershell.exe"), "-NoProfile", "-NonInteractive", "-Command", fixture+windowsInventory)
		cmd.Env = append(os.Environ(), `BEAMO_LAUNCHER_FILE=X:\Start Beamo Wipe.exe`, "BEAMO_DUPLICATE=0")
		if duplicate {
			cmd.Env[len(cmd.Env)-1] = "BEAMO_DUPLICATE=1"
		}
		out, err := cmd.Output()
		cancel()
		if duplicate {
			if err == nil {
				t.Fatal("duplicate GUID accepted")
			}
			continue
		}
		if err != nil {
			t.Fatalf("PowerShell inventory runtime: %v", err)
		}
		var got struct {
			Media      string   `json:"media"`
			Partitions []string `json:"partitions"`
		}
		if json.Unmarshal(out, &got) != nil || len(got.Partitions) != 1 || got.Partitions[0] != "gpt:11111111-2222-3333-4444-555555555555" || !strings.Contains(got.Media, "TESTONLY") {
			t.Fatalf("invalid fixture result: %s", out)
		}
	}
}
