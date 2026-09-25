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
	"strconv"
	"strings"
	"syscall"
	"unicode"
)

type linuxFirmware struct{}

func (linuxFirmware) read(name string) ([]byte, error) {
	b, err := readSmall("/sys/firmware/efi/efivars/"+name+"-"+efiGlobal, 16388)
	if errors.Is(err, os.ErrNotExist) {
		return nil, errAbsent
	}
	if err != nil || len(b) < 4 {
		return nil, errors.New("firmware read failed")
	}
	return b[4:], nil
}
func (linuxFirmware) write(name string, data []byte) (bool, error) {
	if name != "BootNext" || len(data) != 2 {
		return false, errors.New("unsupported firmware write")
	}
	path := "/sys/firmware/efi/efivars/BootNext-" + efiGlobal
	return writeExclusiveFileOwned(path, append([]byte{7, 0, 0, 0}, data...), syscall.O_NOFOLLOW)
}
func (linuxFirmware) remove(name string) error {
	if name != "BootNext" {
		return errors.New("unsupported firmware removal")
	}
	return os.Remove("/sys/firmware/efi/efivars/BootNext-" + efiGlobal)
}

func linuxCommand(ctx context.Context, name string, args ...string) ([]byte, error) {
	cmd := exec.CommandContext(ctx, name, args...)
	cmd.Env = []string{"PATH=/usr/sbin:/usr/bin:/sbin:/bin", "LANG=C.UTF-8", "LC_ALL=C.UTF-8"}
	return boundedOutput(cmd, 1<<20)
}

type linuxNode struct {
	Path     string      `json:"path"`
	Type     string      `json:"type"`
	Tran     string      `json:"tran"`
	Serial   string      `json:"serial"`
	WWN      string      `json:"wwn"`
	Size     json.Number `json:"size"`
	PartUUID string      `json:"partuuid"`
	PTUUID   string      `json:"ptuuid"`
	Start    json.Number `json:"start"`
	MajMin   string      `json:"maj:min"`
	Sector   json.Number `json:"log-sec"`
	Children []linuxNode `json:"children"`
}

// A partition's kernel path must name the disk that lsblk claims is its
// parent. The JSON tree alone can be contradictory, and its ancestry is used
// to authorize a one-time firmware boot entry for the mounted launcher.
func linuxPartitionOfDisk(disk, part string) bool {
	return linuxPartitionNumberOfDisk(disk, part) != 0
}

func linuxPartitionNumberOfDisk(disk, part string) uint64 {
	if !strings.HasPrefix(disk, "/dev/") || !strings.HasPrefix(part, disk) {
		return 0
	}
	suffix := strings.TrimPrefix(part, disk)
	if disk[len(disk)-1] >= '0' && disk[len(disk)-1] <= '9' {
		if !strings.HasPrefix(suffix, "p") {
			return 0
		}
		suffix = suffix[1:]
	}
	number, err := strconv.ParseUint(suffix, 10, 32)
	if err != nil {
		return 0
	}
	return number
}

func linuxMeaningfulHardwareID(value string) string {
	text := strings.ToLower(strings.TrimSpace(value))
	body := strings.TrimPrefix(text, "0x")
	var normalized strings.Builder
	meaningful := false
	for _, char := range body {
		if unicode.IsLetter(char) || unicode.IsDigit(char) {
			normalized.WriteRune(char)
			if char != '0' {
				meaningful = true
			}
		}
	}
	if !meaningful {
		return ""
	}
	switch normalized.String() {
	case "unknown", "none", "na", "notavailable", "notapplicable", "noserial", "null", "unspecified", "notspecified":
		return ""
	}
	return text
}

func linuxMedia(data []byte, source string) (string, []string, error) {
	var inventory struct {
		Devices []linuxNode `json:"blockdevices"`
	}
	if err := json.Unmarshal(data, &inventory); err != nil {
		return "", nil, err
	}
	var found []linuxNode
	var contains func(linuxNode) bool
	contains = func(n linuxNode) bool {
		if n.Path == source {
			return true
		}
		for _, c := range n.Children {
			if contains(c) {
				return true
			}
		}
		return false
	}
	for _, d := range inventory.Devices {
		if contains(d) {
			found = append(found, d)
		}
	}
	if len(found) != 1 {
		return "", nil, errors.New("ambiguous source")
	}
	d := found[0]
	if d.Type != "disk" || d.Tran != "usb" || (linuxMeaningfulHardwareID(d.Serial) == "" && linuxMeaningfulHardwareID(d.WWN) == "") || d.MajMin == "" || !strings.HasPrefix(d.Path, "/dev/") {
		return "", nil, errors.New("unidentified USB")
	}
	diskBytes, sizeErr := strconv.ParseUint(string(d.Size), 10, 64)
	if sizeErr != nil || diskBytes == 0 {
		return "", nil, errors.New("invalid USB disk size")
	}
	sourceParts := 0
	for _, child := range d.Children {
		if child.Type != "part" {
			continue
		}
		if !linuxPartitionOfDisk(d.Path, child.Path) {
			return "", nil, errors.New("contradictory USB partition parent")
		}
		if child.Path == source {
			sourceParts++
		}
	}
	if sourceParts != 1 {
		return "", nil, errors.New("launcher source is not one direct USB partition")
	}
	var parts []string
	counts := map[string]int{}
	var countIDs func(linuxNode)
	countIDs = func(n linuxNode) {
		if n.Type == "part" && n.PartUUID != "" {
			counts[strings.ToLower(n.PartUUID)]++
		}
		for _, c := range n.Children {
			countIDs(c)
		}
	}
	for _, node := range inventory.Devices {
		countIDs(node)
	}
	// An MBR signature identifies the disk, even when its partitions have
	// different numbers. Match Windows' refusal of a duplicate disk signature.
	if len(d.PTUUID) == 8 {
		matches := 0
		for _, node := range inventory.Devices {
			if node.Type == "disk" && strings.EqualFold(node.PTUUID, d.PTUUID) {
				matches++
			}
		}
		if matches != 1 {
			return "", nil, errors.New("ambiguous disk identity")
		}
	}
	for _, p := range d.Children {
		if p.Type != "part" || p.Path != source {
			continue
		}
		startSectors, startErr := strconv.ParseUint(string(p.Start), 10, 64)
		partBytes, partErr := strconv.ParseUint(string(p.Size), 10, 64)
		if startErr != nil || partErr != nil || !partitionWithinDisk(diskBytes, startSectors, partBytes) {
			return "", nil, errors.New("invalid USB partition geometry")
		}
		guid := strings.ToLower(p.PartUUID)
		if counts[guid] != 1 {
			return "", nil, errors.New("ambiguous partition identity")
		}
		if validGUID(guid) {
			sector, sectorErr := strconv.ParseUint(string(d.Sector), 10, 64)
			part := linuxPartitionNumberOfDisk(d.Path, p.Path)
			if sectorErr == nil && (sector == 512 || sector == 4096) && startSectors*512%sector == 0 && partBytes%sector == 0 {
				if route := gptFirmwareRoute(guid, d.PTUUID, uint32(part), startSectors*512/sector, partBytes/sector); route != "" {
					parts = append(parts, route)
				}
			}
			continue
		}
		// lsblk START counts 512-byte sectors. EFI uses logical blocks.
		signature, validSignature := parseMBRSignature(d.PTUUID)
		if !validSignature {
			continue
		}
		start, e1 := p.Start.Int64()
		size, e2 := p.Size.Int64()
		sector, e3 := d.Sector.Int64()
		part := int64(0)
		var e4 error
		if len(guid) == 11 && guid[:8] == strings.ToLower(d.PTUUID) && guid[8] == '-' {
			part, e4 = strconv.ParseInt(guid[9:], 16, 32)
		} else {
			e4 = errors.New("partition identity unavailable")
		}
		if e1 != nil || e2 != nil || e3 != nil || e4 != nil || start <= 0 || size <= 0 || part <= 0 || uint64(part) != linuxPartitionNumberOfDisk(d.Path, p.Path) || (sector != 512 && sector != 4096) || start > 1<<53 || start*512%sector != 0 || size%sector != 0 {
			continue
		}
		parts = append(parts, fmt.Sprintf("mbr:%08x:%d:%d:%d", signature, part, start*512/sector, size/sector))
	}
	id, _ := json.Marshal([]string{d.Path, d.MajMin, d.Serial, d.WWN, string(d.Size), d.PTUUID})
	return string(id), parts, nil
}

func linuxInventory(ctx context.Context) ([]byte, error) {
	// PATH alone does not enable lsblk's JSON children arrays. Explicit tree
	// output preserves the disk ancestry required to identify the mounted USB.
	return linuxCommand(ctx, "/usr/bin/lsblk", "--json", "--tree", "--bytes", "--output", "PATH,TYPE,TRAN,SERIAL,WWN,SIZE,PARTUUID,PTUUID,START,MAJ:MIN,LOG-SEC")
}

func nativeX64() bool {
	var info syscall.Utsname
	if syscall.Uname(&info) != nil {
		return false
	}
	var name []byte
	for _, c := range info.Machine {
		if c == 0 {
			break
		}
		name = append(name, byte(c))
	}
	return string(name) == "x86_64"
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
	if _, err := os.Stat("/sys/firmware/efi"); err != nil {
		s.Problem = "legacy"
		return s
	}
	s.UEFI = true
	if b, err := readSmall("/proc/cmdline", 16384); err == nil {
		for _, arg := range strings.Fields(string(b)) {
			if arg == "boot=live" {
				s.Problem = "live"
				return s
			}
		}
	}
	mediaInfo := inspectMediaContext(ctx, exe)
	s.Layout = mediaInfo.Fingerprint
	var err error
	if mediaInfo.Problem != "" {
		s.Problem = mediaInfo.Problem
		return s
	}
	resolved, err := filepath.EvalSymlinks(exe)
	if err != nil || resolved != exe {
		s.Problem = "media"
		return s
	}
	mount, err := linuxCommand(ctx, "/usr/bin/findmnt", "--json", "--target", exe, "--output", "SOURCE,TARGET")
	if err != nil {
		s.Problem = "media"
		return s
	}
	var mounts struct {
		FS []struct {
			Source string `json:"source"`
			Target string `json:"target"`
		} `json:"filesystems"`
	}
	if json.Unmarshal(mount, &mounts) != nil || len(mounts.FS) != 1 || filepath.Clean(mounts.FS[0].Target) != filepath.Dir(exe) {
		s.Problem = "media"
		return s
	}
	data, err := linuxInventory(ctx)
	if err != nil {
		s.Problem = "media"
		return s
	}
	s.MediaID, s.Partitions, err = linuxMedia(data, mounts.FS[0].Source)
	if err != nil {
		s.Problem = "media"
		return s
	}
	s.Entries, s.Pending, s.SecureBoot, err = readBootEntries(linuxFirmware{})
	if err != nil {
		s.Problem = "firmware"
	}
	return s
}

func platformRestart(want string) error {
	if os.Geteuid() != 0 {
		return errors.New("administrator permission required")
	}
	// /run is root-owned; O_NOFOLLOW prevents following an unexpected lock.
	f, err := os.OpenFile("/run/beamo-wipe-restart.lock", os.O_CREATE|os.O_RDWR|syscall.O_NOFOLLOW, 0600)
	if err != nil {
		return err
	}
	defer f.Close()
	if err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		return errors.New("restart already in progress")
	}
	defer syscall.Flock(int(f.Fd()), syscall.LOCK_UN)
	ctx, cancel := context.WithTimeout(context.Background(), mediaProbeTimeout)
	defer cancel()
	p := inspectPlan(ctx, platformProbe)
	if !p.Direct || p.Fingerprint != want {
		return errors.New("USB or boot settings changed")
	}
	return restartOnce(linuxFirmware{}, p, func() error {
		_, err := linuxCommand(ctx, "/usr/bin/systemctl", "reboot")
		return err
	})
}
func platformElevate(ctx context.Context, fingerprint string) error {
	exe, err := os.Executable()
	if err != nil {
		return err
	}
	if os.Geteuid() == 0 {
		return platformRestart(fingerprint)
	}
	// Never feed a password through our UI or a command line.
	cmd := exec.CommandContext(ctx, "/usr/bin/pkexec", exe, "--restart-helper="+fingerprint)
	return cmd.Run()
}
func openBrowser(url string) error  { return exec.Command("/usr/bin/xdg-open", url).Start() }
func notifyFailure(message string)  { fmt.Fprintln(os.Stderr, message) }
func prepareDesktop() (bool, error) { return false, nil }
