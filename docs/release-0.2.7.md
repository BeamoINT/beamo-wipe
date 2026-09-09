# Beamo Wipe 0.2.7

This release fails closed when a leftover `BEAMO_WIPE` USB could be mistaken
for the live stick, and when a mounted RAID or multipath volume leaves sibling
disks selectable. Disk size labels use integer half-up decimal GB so 2.5 GB is
not shown as 2 GB. Tk Enter activates the focused enabled control; last-chance
Erase still requires the countdown, and unsaved-report shutdown still keeps
the session on Enter.

Pinned nwipe 0.42 remains the only erase engine. Virtual tests include
enrolled Secure Boot firmware; physical USB/controller and firmware-trust
coverage remain incomplete. SHA-256 detects corruption but does not
authenticate the publisher.

Download the `.img` for the desktop-readable USB layout, or the `.iso` for
traditional ISO workflows, together with their SHA-256 sidecars. The GCS
publisher writes `RELEASE_COMPLETE.txt` last. The GitHub release exposes the
matching image, ISO, provenance, and checksums.
