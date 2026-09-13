# Beamo Wipe 0.2.8

Beamo Wipe 0.2.8 adds a screen-reader boot entry: press S at the BIOS or UEFI boot menu to start the accessible wizard. It retains the guided confirmation steps and boot-USB protection.

This release also strengthens disk exclusion for leftover Beamo USB media and mounted RAID/multipath volumes, corrects rounded disk-size labels, and improves keyboard focus behavior. Pinned nwipe 0.42 remains the only erase engine.

For the desktop-readable USB layout, download the `.img.gz` and its checksum; decompress it first if your flasher does not support gzip. The `.iso` supports traditional ISO workflows. Writing either image erases the destination USB.

Release provenance, checksums, and the detached manifest signature accompany the images. Verify the signature against the independently confirmed public-key fingerprint; SHA-256 alone detects corruption but does not authenticate the publisher.

Automated qualification uses disposable virtual disks. It does not certify every physical USB controller, firmware, sound device, or Windows desktop.
