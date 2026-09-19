# Connection type on disk cards

Observed lsblk transport is labeled on every disk card without Show more.
SATA/NVMe/SAS plus hotplug may be a USB enclosure; copy must not guess
internal vs external. Missing TRAN stays “Connection unknown”; named but
unmapped buses stay “Other”. Selection and nwipe flags are unchanged.

Fake lsblk / DryRunRunner only.
