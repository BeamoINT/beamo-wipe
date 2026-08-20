# Third-party software

Beamo Wipe does not include a custom wipe algorithm. The only erasure
engine is **nwipe**, invoked as a separate program.

## nwipe

| Field | Value |
| --- | --- |
| Project | nwipe |
| Version (pinned) | **v0.42** (git tag `v0.42`) |
| Source | https://github.com/martijnvanbrummelen/nwipe |
| License | GNU General Public License v2.0 (GPL-2.0) |
| Authors | Martijn van Brummelen, Nick Law (@PartialVolume), and contributors |

The live image builds nwipe from that tag. If the build cannot clone
GitHub, it may fall back to the Debian `nwipe` package; the running
image then records the actual version in `/usr/share/doc/beamo-wipe/NWIPE_VERSION`.

Beamo Wipe talks to nwipe only by executing the `nwipe` binary with
explicit device, method, and `--nogui --autonuke` flags. It does not
link against nwipe. That keeps this wrapper under GPL-3.0-or-later
while nwipe stays GPL-2.0.

Debian `live-boot`, `live-config`, GNU/Linux, Xorg, Python 3, and
Tkinter in the live image keep their own licenses (GPL, LGPL, MIT,
Apache, and others as shipped by Debian). Offer those sources the
same way Debian does: the live USB `SOURCE.txt` points here, and
Debian source packages are available from `deb.debian.org`.

## Why this is not “Beamo SecureErase Engine”

Do not rename nwipe in the UI, ISO volume label aside, or marketing.
The first wizard screen, this file, `NOTICE`, and `docs/boot-card.md`
must keep saying: the engine is nwipe.
