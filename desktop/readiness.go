// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"fmt"
	"strings"
)

type readinessCheck struct {
	ID     string `json:"id"`
	Label  string `json:"label"`
	State  string `json:"state"`
	Detail string `json:"detail"`
	Next   string `json:"next"`
}

// Explain evidence without changing the plan or probing again. In particular,
// an early return must not make a later check look successful.
func explainReadiness(s Snapshot, p Plan) ([]readinessCheck, string) {
	checks := []readinessCheck{
		{"usb", "Original USB detection", "unverified", "Not verified. The check did not establish the original USB's identity.", "Keep the original USB connected and choose Check again, or close this window and open START-HERE.html on the USB."},
		{"settings", "Startup-settings readability", "unverified", "Not verified. The check did not establish that startup settings could be read.", "Resolve the earlier check, then choose Check again. You can also use the boot instructions below."},
		{"route", "Supported restart route", "unverified", "Not verified. A guided restart is not available from these results.", "Use the boot instructions below, or resolve the other checks and choose Check again."},
	}
	usb, settings, route := &checks[0], &checks[1], &checks[2]
	if p.Direct || (s.MediaID != "" && len(s.Partitions) > 0) {
		usb.State = "pass"
		usb.Detail = "Found. The launcher is on the identified Beamo USB."
		usb.Next = "Keep this USB connected. This check does not select a disk to erase."
	}
	if p.Direct || (s.Entries != nil && s.Problem != "firmware") {
		settings.State = "pass"
		settings.Detail = "Readable. The computer's startup entries were read."
		settings.Next = "No settings were changed by this check. Review the restart-route check next."
	}
	if p.Direct {
		route.State = "pass"
		route.Detail = "Available. One startup entry matches this USB."
		route.Next = "Save your work, confirm below, then request a restart. Administrator permission may still be required; a successful boot is not guaranteed."
	}
	switch p.Problem {
	case "media", "unattended":
		usb.State = "fail"
		usb.Detail = "Not confirmed. The original USB could not be safely accepted."
		usb.Next = "Open the launcher from the original Beamo USB, not a copied application. Try a direct USB port, then choose Check again."
		if p.Problem == "unattended" {
			usb.Detail = "Blocked. Automated installation files were found on this USB."
			usb.Next = "Review those files before using the USB. Close this window if you are unsure."
			route.State = "blocked"
			route.Detail = "Blocked. Beamo will not request a guided restart with automated installation files present."
			route.Next = usb.Next
		}
	case "firmware":
		settings.State = "unverified"
		settings.Detail = "Could not read. The cause may be a permission restriction or unavailable startup settings."
		settings.Next = "Administrator permission may be required. Ask the computer's administrator for help, or use the boot instructions below. Then choose Check again."
	case "legacy":
		settings.State = "unsupported"
		settings.Detail = "Unavailable. This computer did not report the supported startup-settings interface."
		settings.Next = "Use the computer's boot menu and the instructions below."
		fallthrough
	case "platform", "live":
		route.State = "unsupported"
		route.Detail = "Unsupported here. This launcher cannot offer a guided restart in this environment."
		route.Next = "Use the boot instructions below for supported Intel/AMD 64-bit Windows or Linux PCs. Apple Silicon and Chromebooks are not supported."
		if p.Problem == "live" {
			route.Next = "You are already in the Beamo USB environment. Close this launcher and use the Beamo Wipe window to choose and confirm a disk."
		}
	case "entry":
		route.State = "unsupported"
		route.Detail = "No exact route. The computer did not provide one unambiguous startup entry for this USB."
		route.Next = "Save your work and use the computer's boot menu to choose the USB. See the instructions below."
	case "windows-manual":
		route.State = "unsupported"
		route.Detail = "Use the boot menu. Windows may cancel a requested restart after accepting it, so the launcher cannot safely set a one-time startup entry."
		route.Next = "Save your work, use Windows Restart, then choose the Beamo USB from the computer's boot menu."
	case "pending":
		route.State = "blocked"
		route.Detail = "Already scheduled. Another special startup request is present; Beamo will not replace it."
		route.Next = "Complete that startup before checking again. If it is unexpected, ask the computer's administrator before restarting."
	case "timeout", "cancelled":
		for i := range checks {
			checks[i].State = "unverified"
			checks[i].Detail = "Not verified. The check did not finish."
			checks[i].Next = "Wait a moment and choose Check again, or close this window and use START-HERE.html on the USB."
		}
	}
	value := func(v string) string {
		if v == "" {
			return "not established"
		}
		return v
	}
	technical := fmt.Sprintf("Check result: %s\nUSB identity: %s\nUSB partitions: %s\nSecure Boot: %s", value(p.Problem), value(s.MediaID), value(strings.Join(s.Partitions, ", ")), value(s.SecureBoot))
	if p.Direct {
		technical = strings.Replace(technical, "Check result: not established", "Check result: ready", 1)
		technical = fmt.Sprintf("Matched startup entry: Boot%04X\n", p.Entry) + technical
	}
	return checks, technical
}
