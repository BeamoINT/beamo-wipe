# Audio results — PHY-AUD

Packaged: `pulseaudio`, `orca`, `espeak-ng`, `speech-dispatcher` (`packaging/live/config/package-lists/beamo.list.chroot`). Policy: [`docs/screen-reader.md`](../../../screen-reader.md).

QEMU selecting the speech boot entry is **not** a speaker Pass. `./preview --accessible` starts no host audio.

BIOS menu: no beep (expected). UEFI menu: two short beeps only if the machine has a speaker.

Every Result below is **NOT TESTED**.

| ID | Variant | Expected (physical) | Output device (fill) | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| PHY-AUD-01 | UEFI Beamo menu beep | Two short beeps on a PC with a speaker; silence on many laptops is allowed — record which | | NOT TESTED | `logs/PHY-AUD-01-*` |
| PHY-AUD-02 | BIOS Beamo menu | No beep (expected). Not a Fail. | | NOT TESTED | `logs/PHY-AUD-02-*` |
| PHY-AUD-03 | Speech entry (S) with working speakers | Spoken startup; Orca speaks the accessible view | | NOT TESTED | `logs/PHY-AUD-03-*` |
| PHY-AUD-04 | Audio or Orca failure | View stays usable; diagnostic records `pulseaudio_failed` or `orca_failed` | | NOT TESTED | `logs/PHY-AUD-04-*` |
| PHY-AUD-05 | HDMI / DisplayPort audio only (internal speaker mute or absent) | Record whether speech is audible on the display. Silence here is Fail for PHY-AUD-03 if you claimed speakers, else Excluded. | | NOT TESTED | `logs/PHY-AUD-05-*` |
| PHY-AUD-06 | Headphones | Record jack vs USB headset. Not an advertised requirement. | | NOT TESTED | `logs/PHY-AUD-06-*` |

Notes:
