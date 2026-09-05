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

The live image builds nwipe from that tag at the pinned commit
`6082bde060091e66365d852a1877f2ee80c67105`. If the build cannot clone
GitHub after 5 retries, it fails closed (`ERROR: git clone nwipe failed`)
and no ISO is produced. There is no fallback to the Debian `nwipe`
package (bookworm's nwipe is not 0.42). The running image records the
actual version in `/usr/share/doc/beamo-wipe/NWIPE_VERSION` and the
hook refuses to publish an ISO if that version is not `0.42`.

Beamo Wipe talks to nwipe only by executing the `nwipe` binary with
explicit device, method, and `--nogui --autonuke` flags. It does not
link against nwipe. That keeps this wrapper under GPL-3.0-or-later
while nwipe stays GPL-2.0.

Debian `live-boot`, `live-config`, GNU/Linux, Xorg, Python 3, and
Tkinter, GTK, PyGObject, AT-SPI, Orca, Speech Dispatcher, and PulseAudio
in the live image keep their own licenses (GPL, LGPL, MIT,
Apache, and others as shipped by Debian). Offer those sources the
same way Debian does: the live USB `SOURCE.txt` points here, and
Debian source packages are available from `deb.debian.org`.

## Why this is not “Beamo SecureErase Engine”

Do not rename nwipe in the UI, ISO volume label aside, or marketing.
The first wizard screen, this file, `NOTICE`, and `docs/boot-card.md`
must keep saying: the engine is nwipe.
