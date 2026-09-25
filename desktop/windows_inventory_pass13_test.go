// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"encoding/json"
	"os"
	"os/exec"
	"strings"
	"testing"
)

// Run the inventory body with fake PowerShell disk commands. The real
// Windows-only script lives in platform_windows.go, so this also exercises its
// partition-selection behavior on non-Windows test workers with pwsh.
func TestWindowsInventoryReportsOnlyLauncherPartitionPass13(t *testing.T) {
	pwsh, err := exec.LookPath("pwsh")
	if err != nil {
		pwsh, err = exec.LookPath("powershell.exe")
		if err != nil {
			t.Skip("PowerShell unavailable")
		}
	}
	source, err := os.ReadFile("platform_windows.go")
	if err != nil {
		t.Fatal(err)
	}
	start := strings.Index(string(source), "function Has-MeaningfulHardwareId")
	if start < 0 {
		t.Fatal("Windows inventory script unavailable")
	}
	end := strings.Index(string(source[start:]), "\n`")
	if end < 0 {
		t.Fatal("Windows inventory script unavailable")
	}
	script := string(source[start : start+end])
	fixture := `$ErrorActionPreference='Stop'
$root='X:\'
$launcher=[pscustomobject]@{DiskNumber=5;Guid='{11111111-2222-3333-4444-555555555555}';PartitionNumber=1;Offset=1048576;Size=1073741824}
$sibling=[pscustomobject]@{DiskNumber=5;Guid='{aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee}';PartitionNumber=2;Offset=1074790400;Size=1073741824}
$disk=[pscustomobject]@{Number=5;BusType='USB';IsBoot=$false;IsSystem=$false;SerialNumber='TESTONLY';UniqueId='TESTONLY';Size=2147483648;PartitionStyle='GPT';Signature=0;LogicalSectorSize=512}
function Get-Partition { [CmdletBinding()]param($DriveLetter,$DiskNumber); if ($DriveLetter) { $launcher } else { $launcher; $sibling } }
function Get-Disk { [CmdletBinding()]param($Number); $disk }
`
	mbrFixture := strings.Replace(fixture, "PartitionStyle='GPT';Signature=0", "PartitionStyle='MBR';Signature=305441741", 1)
	for _, tc := range []struct {
		name, script, want string
	}{
		{"512-byte sectors", fixture, "gpt:11111111-2222-3333-4444-555555555555:1:2048:2097152"},
		{"4096-byte sectors", strings.Replace(fixture, "LogicalSectorSize=512", "LogicalSectorSize=4096", 1), "gpt:11111111-2222-3333-4444-555555555555:1:256:262144"},
		{"unaligned 4096-byte sector", strings.NewReplacer("LogicalSectorSize=512", "LogicalSectorSize=4096", "Offset=1048576", "Offset=1048577").Replace(fixture), ""},
		{"MBR valid", mbrFixture, "mbr:1234abcd:1:2048:2097152"},
		{"MBR zero start", strings.Replace(mbrFixture, "Offset=1048576", "Offset=0", 1), ""},
		{"MBR partition exceeds disk", strings.Replace(mbrFixture, "Size=1073741824", "Size=3221225472", 1), ""},
		{"MBR zero partition number", strings.Replace(mbrFixture, "PartitionNumber=1", "PartitionNumber=0", 1), ""},
	} {
		t.Run(tc.name, func(t *testing.T) {
			output, err := exec.Command(pwsh, "-NoProfile", "-NonInteractive", "-Command", tc.script+script).CombinedOutput()
			if err != nil {
				t.Fatalf("fake Windows inventory failed: %v\n%s", err, output)
			}
			var result struct {
				Partitions []string `json:"partitions"`
			}
			if err := json.Unmarshal(output, &result); err != nil {
				t.Fatalf("invalid inventory output: %v\n%s", err, output)
			}
			if tc.want == "" && len(result.Partitions) == 0 {
				return
			}
			if len(result.Partitions) != 1 || result.Partitions[0] != tc.want {
				t.Fatalf("unverified sibling partition was offered as a boot route: %v", result.Partitions)
			}
		})
	}
}
