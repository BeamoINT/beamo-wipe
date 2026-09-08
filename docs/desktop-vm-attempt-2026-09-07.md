# Additional Google Cloud desktop validation: blocked before testing

Follow-up: the user subsequently approved the transfers, and the
[desktop validation was completed](gcp-desktop-validation-2026-09-07.md).
This note preserves the initial blocked attempt.

Source: `f7b6490036d62281e2133da642557cee6710f081`, branch
`codex/desktop-entry`. This attempt does not add application acceptance results
or supersede the passing [quality review](quality-review-2026-09-07.md).

The user requested Google Cloud VMs for comprehensive testing and explicitly
asked to remember this preference. That preference was recorded in the local
memory extension notes. No application code was changed or published.

## Prepared and provisioned

Two private `n2-standard-4` VMs were created in project `beamo-wipe`, zone
`us-central1-a`, each with a 60 GB auto-delete boot disk, no external IP or
service account, and a three-hour automatic deletion deadline:

- `beamo-desktop-lab-0907-linux`, ID `4063738264240231002`, official image
  `debian-12-bookworm-v20260902`.
- `beamo-desktop-lab-0907-windows`, ID `2266220796470071888`, official image
  `windows-server-2025-dc-v20260814`.

A dedicated VPC/subnet/router/NAT supplied outbound package access. SSH was
restricted to IAP; RDP was restricted to the private lab subnet. Linux desktop
package installation was observed through SSH. Windows and Linux launchers
were built with Go 1.26.5, together with a Windows native test executable.

Windows Server is not Windows 10/11 acceptance. Google's documented Windows
Desktop path requires an eligible license and sole-tenant hosting; neither
was established in this attempt. See [Google's licensing FAQ](https://docs.cloud.google.com/compute/docs/instances/windows/ms-licensing-faq).

## Exact blocker and pending approval

Automatic approval review rejected the required upload twice:

1. An archive including a randomly generated password used only for local
   accounts on these newly created test VMs was rejected as credential export.
2. After that password was removed, the source/executable archive was also
   rejected because review required explicit authorization for that payload
   and destination.

Neither rejected transfer executed. No browser, UAC, polkit, native suite,
USB, or restart acceptance test ran on these new VMs. Provisioning success is
not application test success. Existing boot/erase evidence remains in the
prior reports and was not repeated here.

The prepared credential-free archive is
`/private/tmp/beamo-desktop-vms-0907/input-public.tgz`, SHA-256
`050f66035d2b69750be4d7ba1fbe30ee236198e3dfa73f82e19c4c96d787323e`.
It contains the desktop/helper source archive, both launchers, build identities,
Windows native tests, and Windows/Linux desktop test scripts. The next step
requires explicit approval to transfer these files and a fresh disposable
VM-only login password between the task's temporary VMs in project
`beamo-wipe`. No pre-existing account credentials are needed.

## Cleanup

Both VMs and auto-delete disks, both firewall rules, Cloud NAT, router, subnet,
and VPC were deleted. Independent list queries confirmed no owned resources
remained at `2026-09-07T03:21:57.675532+00:00`. The task-only password and its
local startup metadata were removed. See the [machine-readable receipt](evidence/desktop-vm-attempt-20260907.json).
