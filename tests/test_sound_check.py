# SPDX-License-Identifier: GPL-3.0-or-later
"""Backlog #86: discoverable output controls and a speech test for the
screen-reader path.

Baseline (fails before the fix, at 60d827a + #83/#84/#85 WIP): the app
has no audio code at all — no sink listing, no volume/mute, no speech
test, no Orca health check — and the live image ships no output-control
tool. See docs/evidence/sound-check-86/README.md.
"""

from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / "packaging/live/config/package-lists/beamo.list.chroot"

SHORT_SINKS = (
    "0\talsa_output.pci-0000_00_1b.0.analog-stereo\tmodule-alsa-card.c\ts16le 2ch 44100Hz\tSUSPENDED\n"
    "1\talsa_output.usb-Generic_USB_Headset-00.analog-stereo\tmodule-alsa-card.c\ts16le 2ch 48000Hz\tIDLE\n"
    "2\talsa_output.pci-0000_01_00.1.hdmi-stereo\tmodule-alsa-card.c\ts16le 2ch 44100Hz\tSUSPENDED\n"
)
HEADSET = "alsa_output.usb-Generic_USB_Headset-00.analog-stereo"
SPEAKERS = "alsa_output.pci-0000_00_1b.0.analog-stereo"
VOLUME_50 = "Volume: front-left: 32768 /  50% / -18.06 dB,   front-right: 32768 /  50% / -18.06 dB\n"


def _run_ok(stdout=""):
    def fake(argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    return fake


def _fake_pactl(
    monkeypatch,
    calls,
    *,
    sinks=SHORT_SINKS,
    default=HEADSET,
    volume=VOLUME_50,
    mute="Mute: no\n",
):
    from beamo_wipe import sound

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        if argv[1:3] == ["list", "short"]:
            return SimpleNamespace(returncode=0, stdout=sinks, stderr="")
        if argv[1] == "get-default-sink":
            return SimpleNamespace(returncode=0, stdout=default + "\n", stderr="")
        if argv[1] == "get-sink-volume":
            return SimpleNamespace(returncode=0, stdout=volume, stderr="")
        if argv[1] == "get-sink-mute":
            return SimpleNamespace(returncode=0, stdout=mute, stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(sound.subprocess, "run", fake_run)
    monkeypatch.setattr("beamo_wipe.safety.resolve_system_binary", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(sound, "running_on_live_usb", lambda: True)


def test_list_outputs_labels_multiple_sinks_plainly(monkeypatch):
    """Would fail with no audio backend: distinct plain labels + default."""
    from beamo_wipe import sound

    calls = []
    _fake_pactl(monkeypatch, calls)
    state = sound.list_outputs()
    assert state.available
    assert [o.label for o in state.outputs] == ["Speakers", "Headphones", "HDMI sound"]
    assert [o.is_default for o in state.outputs] == [False, True, False]
    assert state.outputs[1].detail == HEADSET
    assert state.volume_percent == 50
    assert state.muted is False
    assert all(call[0] == "/usr/bin/pactl" for call in calls)


def test_list_outputs_with_no_audio_stays_structured(monkeypatch):
    """Would fail with no backend: empty sinks must not raise or mislead."""
    from beamo_wipe import sound

    calls = []
    _fake_pactl(monkeypatch, calls, sinks="")
    state = sound.list_outputs()
    assert not state.available
    assert state.outputs == ()
    assert "No sound output" in state.message


def test_sound_calls_never_touch_non_live_hosts(monkeypatch):
    """Would fail with no live gate: preview must not run audio tools."""
    from beamo_wipe import sound

    calls = []
    monkeypatch.setattr(
        sound.subprocess,
        "run",
        lambda argv, **kw: calls.append(argv) or _run_ok()(argv),
    )
    monkeypatch.setattr(sound, "running_on_live_usb", lambda: False)
    assert not sound.list_outputs().available
    assert not sound.set_output(SPEAKERS).ok
    assert not sound.nudge_volume(SPEAKERS, 10).ok
    assert not sound.set_muted(SPEAKERS, True).ok
    assert not sound.play_speech_test().ok
    assert sound.orca_running() is None
    assert calls == []


def test_output_and_volume_actions_call_pactl_exactly(monkeypatch):
    """Would fail with no backend: exact allowlisted argv, clamped volume."""
    from beamo_wipe import sound

    calls = []
    _fake_pactl(monkeypatch, calls)
    assert sound.set_output(SPEAKERS).ok
    assert calls[-1] == ["/usr/bin/pactl", "set-default-sink", SPEAKERS]
    assert sound.nudge_volume(HEADSET, 10).ok
    assert calls[-1] == ["/usr/bin/pactl", "set-sink-volume", HEADSET, "60%"]
    assert sound.nudge_volume(HEADSET, -200).ok
    assert calls[-1] == ["/usr/bin/pactl", "set-sink-volume", HEADSET, "0%"]
    assert sound.set_muted(HEADSET, True).ok
    assert calls[-1] == ["/usr/bin/pactl", "set-sink-mute", HEADSET, "1"]
    assert not sound.set_output("evil; reboot").ok
    assert not sound.set_output("").ok


def test_malformed_pactl_output_degrades_to_unknown(monkeypatch):
    """Would fail with naive parsing: garbage volume/mute must not crash."""
    from beamo_wipe import sound

    calls = []
    _fake_pactl(monkeypatch, calls, volume="bogus", mute="bogus")
    state = sound.list_outputs()
    assert state.available
    assert state.volume_percent is None
    assert state.muted is None


def test_speech_test_uses_orca_chain_then_falls_back(monkeypatch):
    """Would fail with no speech test: spd-say first, espeak-ng fallback."""
    from beamo_wipe import sound

    calls = []
    monkeypatch.setattr("beamo_wipe.safety.resolve_system_binary", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(sound, "running_on_live_usb", lambda: True)

    def speak_ok(argv, **kwargs):
        calls.append(list(argv))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(sound.subprocess, "run", speak_ok)
    assert sound.play_speech_test().ok
    assert calls == [["/usr/bin/spd-say", "-w", sound.TEST_PHRASE]]

    def speak_fail_then_ok(argv, **kwargs):
        calls.append(list(argv))
        code = 1 if argv[0].endswith("spd-say") else 0
        return SimpleNamespace(returncode=code, stdout="", stderr="")

    calls.clear()
    monkeypatch.setattr(sound.subprocess, "run", speak_fail_then_ok)
    assert sound.play_speech_test().ok
    assert [c[0] for c in calls] == ["/usr/bin/spd-say", "/usr/bin/espeak-ng"]

    monkeypatch.setattr(
        sound.subprocess,
        "run",
        lambda argv, **kw: SimpleNamespace(returncode=1, stdout="", stderr=""),
    )
    result = sound.play_speech_test()
    assert not result.ok and "did not play" in result.message


def test_orca_status_distinguishes_dead_from_unknown(monkeypatch):
    """Would fail with no Orca check: rc 0/1/other map distinctly."""
    from beamo_wipe import sound

    monkeypatch.setattr("beamo_wipe.safety.resolve_system_binary", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(sound, "running_on_live_usb", lambda: True)
    for code, expected in ((0, True), (1, False), (2, None)):
        monkeypatch.setattr(
            sound.subprocess,
            "run",
            lambda argv, **kw: SimpleNamespace(returncode=code, stdout="", stderr=""),
        )
        assert sound.orca_running() is expected


def test_resolve_output_prefers_remembered_then_default(monkeypatch):
    """Would fail with no persistence helper: remembered choice wins."""
    from beamo_wipe import sound
    from beamo_wipe.demo import make_demo_wizard

    calls = []
    _fake_pactl(monkeypatch, calls)
    state = sound.list_outputs()
    assert sound.resolve_output("", state).id == HEADSET
    assert sound.resolve_output(SPEAKERS, state).id == SPEAKERS
    assert sound.resolve_output("gone", state).id == HEADSET
    wizard = make_demo_wizard()
    assert wizard.sound_output == ""
    wizard.set_sound_output(SPEAKERS)
    assert wizard.sound_output == SPEAKERS
    assert sound.apply_remembered_output(wizard).ok
    assert calls[-1] == ["/usr/bin/pactl", "set-default-sink", SPEAKERS]
    wizard.set_sound_output("")
    assert sound.apply_remembered_output(wizard) is None


def test_sound_copy_is_plain_and_offline():
    """Would fail with no sound strings: customer words, no links."""
    from beamo_wipe import copy as C

    assert C.SOUND_CHECK_BUTTON == "Sound check"
    assert "hear" in C.SOUND_TEST_PHRASE.lower()
    assert "http" not in C.SOUND_RECOVERY.lower()
    assert "www." not in C.SOUND_RECOVERY.lower()
    for text in (
        C.SOUND_NO_OUTPUT,
        C.SOUND_OFF_LIVE,
        C.SOUND_ORCA_MISSING,
        C.SOUND_RECOVERY,
    ):
        assert len(text.split()) >= 8
        assert "/dev/" not in text


def test_live_image_ships_output_control_and_speech_tools():
    """Would fail without pulseaudio-utils: pactl provider must be pinned."""
    names = {
        line.strip()
        for line in PACKAGES.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    assert "pulseaudio-utils" in names
    assert "speech-dispatcher" in names
    assert "espeak-ng" in names
    assert "procps" in names


def test_accessible_view_exposes_sound_check(monkeypatch):
    """Would fail with no dialog: button, controls, test, recovery."""
    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parents[1]
        / "src/beamo_wipe/ui/accessible_wizard.py"
    ).read_text()
    assert "SOUND_CHECK_BUTTON" in source
    assert "open_sound_check" in source
    assert "Gtk.Dialog" in source
    assert "SOUND_PLAY_TEST" in source
    assert "SOUND_LOUDER" in source
    assert "SOUND_QUIETER" in source
    assert "SOUND_RECOVERY" in source
    assert "apply_remembered_output" in source


def test_sound_backend_uses_allowlisted_tools_only():
    """Guards: exact binary set, argv lists, timeouts, no shell."""
    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parents[1] / "src/beamo_wipe/sound.py"
    ).read_text()
    assert '"pactl"' in source and '"spd-say"' in source
    assert '"espeak-ng"' in source and '"pgrep"' in source
    assert "shell=True" not in source
    assert "timeout=" in source
