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
	"time"
	"unsafe"
)

var kernel = syscall.NewLazyDLL("kernel32.dll")
var advapi = syscall.NewLazyDLL("advapi32.dll")
var shell = syscall.NewLazyDLL("shell32.dll")
var user = syscall.NewLazyDLL("user32.dll")

func wide(s string) *uint16 { p, _ := syscall.UTF16PtrFromString(s); return p }
func administrator() bool   { r, _, _ := shell.NewProc("IsUserAnAdmin").Call(); return r != 0 }
func privilege(name string) error {
	var token syscall.Token
	process, err := syscall.GetCurrentProcess()
	if err != nil {
		return err
	}
	if err := syscall.OpenProcessToken(process, syscall.TOKEN_ADJUST_PRIVILEGES|syscall.TOKEN_QUERY, &token); err != nil {
		return err
	}
	defer token.Close()
	var luid struct {
		Low  uint32
		High int32
	}
	r, _, err := advapi.NewProc("LookupPrivilegeValueW").Call(0, uintptr(unsafe.Pointer(wide(name))), uintptr(unsafe.Pointer(&luid)))
	if r == 0 {
		return err
	}
	state := struct {
		Count      uint32
		Low        uint32
		High       int32
		Attributes uint32
	}{1, luid.Low, luid.High, 2}
	r, _, err = advapi.NewProc("AdjustTokenPrivileges").Call(uintptr(token), 0, uintptr(unsafe.Pointer(&state)), 0, 0, 0)
	if r == 0 || err == syscall.Errno(1300) {
		return errors.New("required permission unavailable")
	}
	return nil
}

type windowsFirmware struct{}

func (windowsFirmware) read(name string) ([]byte, error) {
	b := make([]byte, 16384)
	var attrs uint32
	n, _, err := kernel.NewProc("GetFirmwareEnvironmentVariableExW").Call(uintptr(unsafe.Pointer(wide(name))), uintptr(unsafe.Pointer(wide("{"+efiGlobal+"}"))), uintptr(unsafe.Pointer(&b[0])), uintptr(len(b)), uintptr(unsafe.Pointer(&attrs)))
	if n == 0 {
		if err == syscall.Errno(203) {
			return nil, errAbsent
		}
		return nil, err
	}
	return b[:n], nil
}
func (windowsFirmware) write(name string, b []byte) error {
	if name != "BootNext" || len(b) != 2 {
		return errors.New("unsupported firmware write")
	}
	r, _, err := kernel.NewProc("SetFirmwareEnvironmentVariableExW").Call(uintptr(unsafe.Pointer(wide(name))), uintptr(unsafe.Pointer(wide("{"+efiGlobal+"}"))), uintptr(unsafe.Pointer(&b[0])), uintptr(len(b)), 7)
	if r == 0 {
		return err
	}
	return nil
}
func (windowsFirmware) remove(name string) error {
	if name != "BootNext" {
		return errors.New("unsupported firmware removal")
	}
	r, _, err := kernel.NewProc("SetFirmwareEnvironmentVariableExW").Call(uintptr(unsafe.Pointer(wide(name))), uintptr(unsafe.Pointer(wide("{"+efiGlobal+"}"))), 0, 0, 7)
	if r == 0 {
		return err
	}
	return nil
}
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
$parts=@(Get-Partition -DriveLetter $root.Substring(0,1) -ErrorAction Stop)
if ($parts.Count -ne 1) { throw 'media' }
$disk=Get-Disk -Number $parts[0].DiskNumber -ErrorAction Stop
if ([string]$disk.BusType -ne 'USB' -or $disk.IsBoot -or $disk.IsSystem -or ([string]::IsNullOrWhiteSpace($disk.SerialNumber) -and [string]::IsNullOrWhiteSpace($disk.UniqueId))) { throw 'media' }
$ids=@()
$allDisks=@(Get-Disk -ErrorAction Stop)
$allParts=@(Get-Partition -ErrorAction Stop)
foreach ($part in @(Get-Partition -DiskNumber $disk.Number -ErrorAction Stop)) {
 if ([string]$disk.PartitionStyle -eq 'GPT') {
  if (@($allParts | Where-Object { $_.Guid -eq $part.Guid }).Count -ne 1) { throw 'ambiguous partition' }
  $ids+= 'gpt:' + ([string]$part.Guid).Trim('{}').ToLowerInvariant()
 } elseif ([string]$disk.PartitionStyle -eq 'MBR' -and $disk.Signature -ne 0) {
  if (@($allDisks | Where-Object { $_.Signature -eq $disk.Signature }).Count -ne 1) { throw 'ambiguous disk' }
  $sector=[long]$disk.LogicalSectorSize
  if (($sector -eq 512 -or $sector -eq 4096) -and $part.Offset % $sector -eq 0 -and $part.Size % $sector -eq 0) {
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
	mediaInfo := inspectMedia(exe)
	s.Layout = mediaInfo.Fingerprint
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
	if privilege("SeSystemEnvironmentPrivilege") != nil {
		s.Problem = "firmware"
		return s
	}
	s.Entries, s.Pending, s.SecureBoot, err = readBootEntries(windowsFirmware{})
	if err != nil {
		s.Problem = "firmware"
	}
	return s
}

func platformRestart(want string) error {
	if !administrator() {
		return errors.New("administrator permission required")
	}
	h, _, err := kernel.NewProc("CreateMutexW").Call(0, 0, uintptr(unsafe.Pointer(wide(`Local\BeamoWipeRestart`))))
	if h == 0 {
		return err
	}
	defer syscall.CloseHandle(syscall.Handle(h))
	r, _, _ := kernel.NewProc("WaitForSingleObject").Call(h, 0)
	if r != 0 && r != 0x80 {
		return errors.New("restart already in progress")
	}
	defer kernel.NewProc("ReleaseMutex").Call(h)
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	p := inspectPlan(ctx, platformProbe)
	if !p.Direct || p.Fingerprint != want {
		return errors.New("USB or boot settings changed")
	}
	if err := privilege("SeShutdownPrivilege"); err != nil {
		return err
	}
	return restartOnce(windowsFirmware{}, p, func() error {
		// No FORCE/FORCEIFHUNG: applications may preserve unsaved work.
		r, _, err := user.NewProc("ExitWindowsEx").Call(2, 0x80040000)
		if r == 0 {
			return err
		}
		return nil
	})
}

type shellExecuteInfo struct {
	Size       uint32
	Mask       uint32
	Window     uintptr
	Verb       *uint16
	File       *uint16
	Parameters *uint16
	Directory  *uint16
	Show       int32
	Instance   uintptr
	IDList     uintptr
	Class      *uint16
	ClassKey   uintptr
	HotKey     uint32
	Icon       uintptr
	Process    syscall.Handle
}

func elevated(exe, args string) (syscall.Handle, error) {
	info := shellExecuteInfo{Mask: 0x40 | 0x100, Verb: wide("runas"), File: wide(exe), Parameters: wide(args), Show: 1}
	info.Size = uint32(unsafe.Sizeof(info))
	r, _, err := shell.NewProc("ShellExecuteExW").Call(uintptr(unsafe.Pointer(&info)))
	if r == 0 {
		return 0, err
	}
	return info.Process, nil
}
func prepareDesktop() (bool, error) {
	if !nativeX64() || administrator() {
		return false, nil
	}
	exe, err := os.Executable()
	if err != nil {
		return false, err
	}
	h, err := elevated(exe, "")
	if err != nil {
		return false, err
	}
	_ = syscall.CloseHandle(h)
	return true, nil
}
func platformElevate(ctx context.Context, fingerprint string) error {
	if administrator() {
		return platformRestart(fingerprint)
	}
	exe, err := os.Executable()
	if err != nil {
		return err
	}
	h, err := elevated(exe, "--restart-helper="+fingerprint)
	if err != nil {
		return err
	}
	defer syscall.CloseHandle(h)
	for {
		r, _, _ := kernel.NewProc("WaitForSingleObject").Call(uintptr(h), 250)
		if r == 0 {
			var code uint32
			ok, _, _ := kernel.NewProc("GetExitCodeProcess").Call(uintptr(h), uintptr(unsafe.Pointer(&code)))
			if ok == 0 || code != 0 {
				return errors.New("restart not confirmed")
			}
			return nil
		}
		if r != 0x102 {
			return errors.New("helper status unavailable")
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}
	}
}
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
