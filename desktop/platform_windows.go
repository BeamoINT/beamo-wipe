// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"unsafe"
)

var kernel = syscall.NewLazyDLL("kernel32.dll")
var user = syscall.NewLazyDLL("user32.dll")

func wide(s string) *uint16 { p, _ := syscall.UTF16PtrFromString(s); return p }
func windowsDirectory() string {
	b := make([]uint16, 32768)
	n, _, _ := kernel.NewProc("GetWindowsDirectoryW").Call(uintptr(unsafe.Pointer(&b[0])), uintptr(len(b)))
	if n == 0 || n >= uintptr(len(b)) {
		return ""
	}
	return syscall.UTF16ToString(b[:n])
}

const windowsInventory = `$ErrorActionPreference='Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$p=$env:BEAMO_LAUNCHER_FILE
$root=[IO.Path]::GetPathRoot($p)
if ($root -notmatch '^[A-Za-z]:\\$' -or [IO.Path]::GetDirectoryName($p) -ne $root) { throw 'media' }
function Has-MeaningfulHardwareId([string]$value) {
 $body=([string]$value).Trim()
 if ($body.StartsWith('0x',[StringComparison]::OrdinalIgnoreCase)) { $body=$body.Substring(2) }
 $normalized=($body -replace '[^\p{L}\p{N}]','').ToLowerInvariant()
 if ($normalized -in @('unknown','none','na','notavailable','notapplicable','noserial','null','unspecified','notspecified')) { return $false }
 foreach ($char in $body.ToCharArray()) {
  if ([char]::IsLetterOrDigit($char) -and $char -ne '0') { return $true }
 }
 return $false
}
$parts=@(Get-Partition -DriveLetter $root.Substring(0,1) -ErrorAction Stop)
if ($parts.Count -ne 1) { throw 'media' }
$disk=Get-Disk -Number $parts[0].DiskNumber -ErrorAction Stop
if ([string]$disk.BusType -ne 'USB' -or $disk.IsBoot -or $disk.IsSystem -or (-not (Has-MeaningfulHardwareId $disk.SerialNumber) -and -not (Has-MeaningfulHardwareId $disk.UniqueId))) { throw 'media' }
$ids=@()
$allDisks=@(Get-Disk -ErrorAction Stop)
$allParts=@(Get-Partition -ErrorAction Stop)
foreach ($part in $parts) {
 if ([string]$disk.PartitionStyle -eq 'GPT') {
  if (@($allParts | Where-Object { $_.Guid -eq $part.Guid }).Count -ne 1) { throw 'ambiguous partition' }
  $sector=[long]$disk.LogicalSectorSize
  if (($sector -eq 512 -or $sector -eq 4096) -and $part.PartitionNumber -gt 0 -and $part.Offset -gt 0 -and $part.Size -gt 0 -and $part.Offset -le $disk.Size -and $part.Size -le ($disk.Size - $part.Offset) -and $part.Offset % $sector -eq 0 -and $part.Size % $sector -eq 0) {
   $ids+= 'gpt:{0}:{1}:{2}:{3}' -f ([string]$part.Guid).Trim('{}').ToLowerInvariant(),$part.PartitionNumber,([long]$part.Offset/$sector),([long]$part.Size/$sector)
  }
 } elseif ([string]$disk.PartitionStyle -eq 'MBR' -and $disk.Signature -ne 0) {
  if (@($allDisks | Where-Object { $_.Signature -eq $disk.Signature }).Count -ne 1) { throw 'ambiguous disk' }
  $sector=[long]$disk.LogicalSectorSize
  if (($sector -eq 512 -or $sector -eq 4096) -and $part.PartitionNumber -gt 0 -and $part.Offset -gt 0 -and $part.Size -gt 0 -and $part.Offset -le $disk.Size -and $part.Size -le ($disk.Size - $part.Offset) -and $part.Offset % $sector -eq 0 -and $part.Size % $sector -eq 0) {
   $ids+= 'mbr:{0:x8}:{1}:{2}:{3}' -f [uint32]$disk.Signature,$part.PartitionNumber,([long]$part.Offset/$sector),([long]$part.Size/$sector)
  }
 }
}
@{media=(@([string]$disk.Number,[string]$disk.UniqueId,[string]$disk.SerialNumber,[string]$disk.Size) | ConvertTo-Json -Compress);partitions=$ids} | ConvertTo-Json -Compress
`

// The compiled architecture alone does not detect x64 emulation on ARM PCs.
func nativeX64() bool {
	proc := kernel.NewProc("IsWow64Process2")
	if proc.Find() != nil {
		return false
	}
	process, err := syscall.GetCurrentProcess()
	if err != nil {
		return false
	}
	var emulated, native uint16
	ok, _, _ := proc.Call(uintptr(process), uintptr(unsafe.Pointer(&emulated)), uintptr(unsafe.Pointer(&native)))
	return ok != 0 && native == 0x8664
}

func platformProbe(ctx context.Context) Snapshot {
	s := Snapshot{}
	exe, exeErr := os.Executable()
	if exeErr != nil {
		s.Problem = "media"
		return s
	}
	if !nativeX64() {
		s.Problem = "platform"
		return s
	}
	var kind uint32
	r, _, _ := kernel.NewProc("GetFirmwareType").Call(uintptr(unsafe.Pointer(&kind)))
	if r == 0 || kind != 2 {
		s.Problem = "legacy"
		return s
	}
	s.UEFI = true
	mediaInfo := inspectMediaContext(ctx, exe)
	s.Layout = mediaInfo.Fingerprint
	var err error
	if mediaInfo.Problem != "" {
		s.Problem = mediaInfo.Problem
		return s
	}
	win := windowsDirectory()
	if win == "" {
		s.Problem = "platform"
		return s
	}
	ps := filepath.Join(win, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
	cmd := exec.CommandContext(ctx, ps, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", windowsInventory)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	// The executable path is a data value, never interpolated into script text.
	cmd.Env = append(os.Environ(), "BEAMO_LAUNCHER_FILE="+exe)
	data, err := boundedOutput(cmd, 1<<20)
	if err != nil {
		s.Problem = "media"
		return s
	}
	var media struct {
		Media      string   `json:"media"`
		Partitions []string `json:"partitions"`
	}
	if json.Unmarshal(data, &media) != nil || media.Media == "" {
		s.Problem = "media"
		return s
	}
	s.MediaID, s.Partitions = media.Media, media.Partitions
	// A successful ExitWindowsEx call does not guarantee a reboot. The user or
	// another application may cancel it, leaving BootNext armed for a later boot.
	s.Problem = "windows-manual"
	return s
}

var errWindowsManual = errors.New("Windows guided restart is unavailable; use the boot menu")

func platformRestart(string) error                  { return errWindowsManual }
func prepareDesktop() (bool, error)                 { return false, nil }
func platformElevate(context.Context, string) error { return errWindowsManual }
func openBrowser(url string) error {
	if !strings.HasPrefix(url, "http://127.0.0.1:") {
		return errors.New("invalid local URL")
	}
	win := windowsDirectory()
	if win == "" {
		return errors.New("Windows directory unavailable")
	}
	// Delegate browser opening to the existing desktop shell.
	return exec.Command(filepath.Join(win, "explorer.exe"), url).Start()
}
func notifyFailure(message string) {
	if len(os.Args) > 1 {
		fmt.Fprintln(os.Stderr, message)
		return
	}
	_, _, _ = user.NewProc("MessageBoxW").Call(0, uintptr(unsafe.Pointer(wide(message))), uintptr(unsafe.Pointer(wide("Beamo Wipe"))), 0x10)
}
