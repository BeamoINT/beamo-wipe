# Beamo Wipe 0.2.9

This release bounds automatic kiosk startup retries. Repeated failures leave a
stable recovery screen with readable details and explicit retry, console,
restart, and shutdown choices. An earlier erase may still be active or
incomplete; recovery never claims otherwise or starts erasure automatically.
Power choices retain the engine-process check and typed confirmation.

Developer tooling adds isolated Python setup, environment checks, WSL routing
for Windows Python development, native Go checks, and portable launcher builds.
Concurrent launcher builds cannot mix executable bytes and checksum metadata.
See [development](development.md) for commands and platform limits.

The erasure engine remains pinned nwipe 0.42. Disk exclusions, identity checks,
authorization, verification and report boundaries are unchanged. Windows and
macOS remain development/helper hosts; they are not live erasure environments.
Virtual testing does not certify every physical machine, firmware or USB device.

The release manifest and publisher signature identify the exact source, build,
artifact hashes and measured gate results. Use the matching signed download
metadata and checksum sidecars. Production artifacts are published only after
the full hosted gate and independent artifact verification succeed.
