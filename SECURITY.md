# Security

This tool permanently erases disks. Treat selection bugs as safety bugs.

## How to report a wipe-safety bug

If Beamo Wipe can list the boot USB as a target, skip the confirm token, start
a wipe on boot, write logs to the target disk, or report success when nwipe
failed, **do not file a public issue with a full exploit write-up**.

Email or use GitHub Security Advisories on
[BeamoINT/beamo-wipe](https://github.com/BeamoINT/beamo-wipe).

Include:

- What you saw (which disk was listed / wiped)
- How you booted (VM, brand of PC)
- Beamo Wipe version / git commit
- nwipe version (`nwipe -V`)

Do not send a “bypass so I can wipe faster” request. We will not add `--force`,
hidden partitions, or in-OS wiping of the running system disk.

UI bugs that are not selection/wipe related can use the public issue templates.
