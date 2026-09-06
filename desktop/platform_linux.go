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
	"time"
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
func (linuxFirmware) write(name string, data []byte) error {
	if name != "BootNext" || len(data) != 2 {
		return errors.New("unsupported firmware write")
	}
	path := "/sys/firmware/efi/efivars/BootNext-" + efiGlobal
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL|syscall.O_NOFOLLOW, 0600)
	if err != nil {
		return err
	}
	b := append([]byte{7, 0, 0, 0}, data...)
	n, writeErr := f.Write(b)
	closeErr := f.Close()
	if writeErr != nil {
		return writeErr
	}
	if n != len(b) {
		return errors.New("short firmware write")
	}
	return closeErr
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
	if d.Type != "disk" || d.Tran != "usb" || (d.Serial == "" && d.WWN == "") || d.MajMin == "" || !strings.HasPrefix(d.Path, "/dev/") {
		return "", nil, errors.New("unidentified USB")
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
	for _, p := range d.Children {
		if p.Type != "part" {
			continue
		}
		guid := strings.ToLower(p.PartUUID)
		if counts[guid] != 1 {
			return "", nil, errors.New("ambiguous partition identity")
		}
		if validGUID(guid) {
			parts = append(parts, "gpt:"+guid)
			continue
		}
		// lsblk START counts 512-byte sectors. EFI uses logical blocks.
		var signature uint32
		if len(d.PTUUID) != 8 {
			continue
		}
		if _, err := fmt.Sscanf(d.PTUUID, "%08x", &signature); err != nil || signature == 0 {
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
		if e1 != nil || e2 != nil || e3 != nil || e4 != nil || start <= 0 || size <= 0 || part <= 0 || (sector != 512 && sector != 4096) || start > 1<<53 || start*512%sector != 0 || size%sector != 0 {
			continue
		}
		parts = append(parts, fmt.Sprintf("mbr:%08x:%d:%d:%d", signature, part, start*512/sector, size/sector))
	}
	id, _ := json.Marshal([]string{d.Path, d.MajMin, d.Serial, d.WWN, string(d.Size), d.PTUUID})
	return string(id), parts, nil
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
	exe, err := os.Executable()
	if err != nil || !mediaLayout(exe) {
		s.Problem = "media"
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
	data, err := linuxCommand(ctx, "/usr/bin/lsblk", "--json", "--bytes", "--output", "PATH,TYPE,TRAN,SERIAL,WWN,SIZE,PARTUUID,PTUUID,START,MAJ:MIN,LOG-SEC")
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
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	p := makePlan(platformProbe(ctx))
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
