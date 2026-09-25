// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"strings"
	"testing"
)

func TestLinuxMediaRefusesPartitionNumberContradictionPass19(t *testing.T) {
	// The mounted launcher is /dev/sdb1, but stale or contradictory lsblk
	// metadata claims it has the identity of partition 2. That identity must
	// not authorize BootNext to a different partition on the USB.
	bad := strings.Replace(linuxFixture, `"partuuid":"12345678-01"`, `"partuuid":"12345678-02"`, 1)
	_, parts, err := linuxMedia([]byte(bad), "/dev/sdb1")
	if err == nil && len(parts) != 0 {
		t.Fatalf("contradictory MBR partition identity offered a restart route: %v", parts)
	}
}
