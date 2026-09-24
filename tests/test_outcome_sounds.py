# SPDX-License-Identifier: GPL-3.0-or-later
"""#93: distinct offline outcome sounds with silent defaults.

Fake processes and controllable state only; never touches host audio.
"""

from __future__ import annotations

import subprocess
import wave
from pathlib import Path

from beamo_wipe import copy as C
from beamo_wipe import sound
from beamo_wipe.outcomes import VIEWS

ROOT = Path(__file__).resolve().parent.parent
SOUNDS_DIR = ROOT / "packaging/sounds"


class Proc:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


def fake_live(monkeypatch, live=True):
    monkeypatch.setattr(sound, "_on_live", lambda: live)


def fake_outputs(monkeypatch, available=True, muted=False):
    state = sound.SoundState(
        available,
        "" if available else C.SOUND_NO_OUTPUT,
        ((sound.SoundOutput("alsa", "Speakers", "alsa", True),) if available else ()),
        60 if available else None,
        muted if available else None,
    )
    monkeypatch.setattr(sound, "list_outputs", lambda: state)
    return state


def test_verified_maps_to_finished_and_everything_else_to_attention():
    assert sound.kind_for_code("verified") == sound.KIND_FINISHED
    for code in VIEWS:
        if code == "verified":
            continue
        assert sound.kind_for_code(code) == sound.KIND_ATTENTION, code
    assert sound.kind_for_code("bogus-code") == sound.KIND_ATTENTION
    assert sound.kind_for_code("") == sound.KIND_ATTENTION


def test_unverified_completion_never_sounds_like_success():
    assert VIEWS["unverified"].success is True  # why the code key matters
    assert sound.kind_for_code("unverified") == sound.KIND_ATTENTION
    assert sound.kind_for_code("unverified") != sound.kind_for_code("verified")


def test_interruption_maps_to_attention():
    assert sound.kind_for_code("cancelled") == sound.KIND_ATTENTION
    assert sound.kind_for_code("interrupted") == sound.KIND_ATTENTION


def test_unknown_kind_is_rejected_without_spawning(monkeypatch):
    fake_live(monkeypatch, True)
    calls = []
    monkeypatch.setattr(sound, "_run", lambda *a: calls.append(a))
    result = sound.play_test("bogus")
    assert result.ok is False
    assert calls == []


def test_off_live_test_reports_and_spawns_nothing(monkeypatch):
    fake_live(monkeypatch, False)
    calls = []
    monkeypatch.setattr(sound, "_run", lambda *a: calls.append(a))
    result = sound.play_test(sound.KIND_FINISHED)
    assert result.ok is False
    assert result.message == C.SOUND_OUTCOME_OFF_LIVE
    assert calls == []


def test_muted_output_is_not_played(monkeypatch):
    fake_live(monkeypatch, True)
    fake_outputs(monkeypatch, muted=True)
    calls = []
    monkeypatch.setattr(sound, "_run", lambda *a: calls.append(a))
    result = sound.play_test(sound.KIND_ATTENTION)
    assert result.ok is False
    assert result.message == C.SOUND_MUTED_SKIP
    assert [c for c in calls if c[0] == "paplay"] == []


def test_missing_output_is_not_played(monkeypatch):
    fake_live(monkeypatch, True)
    fake_outputs(monkeypatch, available=False)
    calls = []
    monkeypatch.setattr(sound, "_run", lambda *a: calls.append(a))
    result = sound.play_test(sound.KIND_FINISHED)
    assert result.ok is False
    assert result.message == C.SOUND_NO_OUTPUT_PLAY
    assert [c for c in calls if c[0] == "paplay"] == []


def test_test_plays_the_matching_shipped_asset(monkeypatch):
    fake_live(monkeypatch, True)
    fake_outputs(monkeypatch)
    calls = []
    monkeypatch.setattr(sound, "_run", lambda *a: calls.append(a) or Proc(0, ""))
    result = sound.play_test(sound.KIND_FINISHED)
    assert result.ok is True
    paplay = [c for c in calls if c[0] == "paplay"]
    assert len(paplay) == 1
    assert paplay[0][1][0].endswith("finished.wav")
    assert result.message == C.SOUND_PLAYING_FINISHED
    calls.clear()
    result = sound.play_test(sound.KIND_ATTENTION)
    assert result.ok is True
    paplay = [c for c in calls if c[0] == "paplay"]
    assert len(paplay) == 1
    assert paplay[0][1][0].endswith("attention.wav")
    assert result.message == C.SOUND_PLAYING_ATTENTION


def test_failed_playback_reports_plainly(monkeypatch):
    fake_live(monkeypatch, True)
    fake_outputs(monkeypatch)
    monkeypatch.setattr(sound, "_run", lambda *a: Proc(1, ""))
    result = sound.play_test(sound.KIND_FINISHED)
    assert result.ok is False
    assert result.message == C.SOUND_PLAY_FAILED


def test_outcome_play_is_fire_and_forget(monkeypatch):
    fake_live(monkeypatch, True)
    fake_outputs(monkeypatch)
    monkeypatch.setattr(sound, "_run", lambda *a: Proc(0, ""))
    launched = []
    waited = []

    class FakePopen:
        def __init__(self, argv, **kwargs):
            launched.append(argv)

        def wait(self, timeout=None):
            waited.append(True)
            return 0

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setattr(
        "beamo_wipe.safety.resolve_system_binary", lambda name: f"/usr/bin/{name}"
    )
    result = sound.play_outcome(sound.KIND_ATTENTION)
    assert result.ok is True
    assert len(launched) == 1
    assert "paplay" in launched[0][0]
    assert any(a.endswith("attention.wav") for a in launched[0])


def test_outcome_play_off_live_spawns_nothing(monkeypatch):
    fake_live(monkeypatch, False)
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("spawned")),
    )
    result = sound.play_outcome(sound.KIND_FINISHED)
    assert result.ok is False


def test_ensure_audio_only_runs_on_live(monkeypatch):
    fake_live(monkeypatch, False)
    calls = []
    monkeypatch.setattr(sound, "_run", lambda *a: calls.append(a))
    assert sound.ensure_audio() is False
    assert calls == []
    fake_live(monkeypatch, True)
    monkeypatch.setattr(sound, "_run", lambda *a: calls.append(a) or Proc(0, ""))
    assert sound.ensure_audio() is True
    assert calls[0][0] == "pulseaudio"


def _demo_wizard():
    from beamo_wipe.demo import make_demo_wizard

    w = make_demo_wizard()
    w.preview = False
    return w


def test_sounds_default_off_and_toggle_reports_state():
    w = _demo_wizard()
    assert w.sounds_enabled is False
    w.toggle_sounds()
    assert w.sounds_enabled is True
    assert w.sound_message == C.SOUND_TOGGLE_ON
    w.toggle_sounds()
    assert w.sounds_enabled is False
    assert w.sound_message == C.SOUND_TOGGLE_OFF


def test_set_sounds_enabled_rejects_non_bool():
    w = _demo_wizard()
    w.set_sounds_enabled("yes")
    assert w.sounds_enabled is False
    w.set_sounds_enabled(True)
    assert w.sounds_enabled is True


def test_no_sound_before_the_outcome_is_final(monkeypatch):
    from beamo_wipe.models import Screen
    from beamo_wipe.wizard import Wizard

    w = _demo_wizard()
    w.set_sounds_enabled(True)
    calls = []
    monkeypatch.setattr(sound, "play_outcome", lambda kind: calls.append(kind))
    for screen in (
        Screen.WORKING,
        Screen.STOPPING,
        Screen.CHECKING,
        Screen.LAST_CHANCE,
        Screen.METHOD,
    ):
        w.screen = screen
        assert w.maybe_play_outcome_sound() is None
    w.screen = Screen.DONE
    w.wipe_result = None
    assert w.maybe_play_outcome_sound() is None
    assert isinstance(w, Wizard)
    assert calls == []


def test_disabled_or_preview_done_stays_silent(monkeypatch):
    from beamo_wipe.models import Screen, WipeResult

    w = _demo_wizard()
    w.screen = Screen.DONE
    w.wipe_result = WipeResult(True, 0, "ok", "/tmp/x.log")
    calls = []
    monkeypatch.setattr(sound, "play_outcome", lambda kind: calls.append(kind))
    assert w.maybe_play_outcome_sound() is None
    w.set_sounds_enabled(True)
    w.preview = True
    assert w.maybe_play_outcome_sound() is None
    assert calls == []


def test_auto_play_fires_once_per_outcome(monkeypatch):
    from unittest.mock import PropertyMock, patch

    from beamo_wipe.models import Screen, WipeResult
    from beamo_wipe.wizard import Wizard

    w = _demo_wizard()
    w.screen = Screen.DONE
    w.wipe_result = WipeResult(True, 0, "Erase completed", "/tmp/x.log")
    w.set_sounds_enabled(True)
    calls = []
    monkeypatch.setattr(
        sound,
        "play_outcome",
        lambda kind: calls.append(kind) or sound.SoundResult(True, ""),
    )
    with patch.object(Wizard, "result_view", new_callable=PropertyMock) as view:
        view.return_value = VIEWS["verified"]
        assert w.maybe_play_outcome_sound() is not None
        assert w.maybe_play_outcome_sound() is None
        assert w.maybe_play_outcome_sound() is None
    assert calls == [sound.KIND_FINISHED]
    w.wipe_result = WipeResult(False, 1, "failed", "/tmp/y.log")
    with patch.object(Wizard, "result_view", new_callable=PropertyMock) as view:
        view.return_value = VIEWS["process_failed"]
        assert w.maybe_play_outcome_sound() is not None
    assert calls == [sound.KIND_FINISHED, sound.KIND_ATTENTION]


def test_silent_attempt_still_marks_the_outcome_played(monkeypatch):
    from unittest.mock import PropertyMock, patch

    from beamo_wipe.models import Screen, WipeResult
    from beamo_wipe.wizard import Wizard

    w = _demo_wizard()
    w.screen = Screen.DONE
    w.wipe_result = WipeResult(True, 0, "Erase completed", "/tmp/x.log")
    w.set_sounds_enabled(True)
    calls = []
    monkeypatch.setattr(
        sound,
        "play_outcome",
        lambda kind: calls.append(kind) or sound.SoundResult(False, C.SOUND_MUTED_SKIP),
    )
    with patch.object(Wizard, "result_view", new_callable=PropertyMock) as view:
        view.return_value = VIEWS["verified"]
        assert w.maybe_play_outcome_sound() is not None
        assert w.maybe_play_outcome_sound() is None
    assert calls == [sound.KIND_FINISHED]
    assert w.sound_message == ""


def test_hear_both_reports_first_failure_once(monkeypatch):
    w = _demo_wizard()
    calls = []
    monkeypatch.setattr(
        sound,
        "play_test",
        lambda kind: calls.append(kind) or sound.SoundResult(False, C.SOUND_MUTED_SKIP),
    )
    result = w.hear_both_sounds()
    assert result.ok is False
    assert result.message == C.SOUND_MUTED_SKIP
    assert w.sound_message == C.SOUND_MUTED_SKIP
    assert calls == [sound.KIND_FINISHED]


def test_hear_replay_bypasses_the_once_marker(monkeypatch):
    from unittest.mock import PropertyMock, patch

    from beamo_wipe.models import Screen, WipeResult
    from beamo_wipe.wizard import Wizard

    w = _demo_wizard()
    w.screen = Screen.DONE
    w.wipe_result = WipeResult(True, 0, "Erase completed", "/tmp/x.log")
    calls = []
    monkeypatch.setattr(
        sound,
        "play_test",
        lambda kind: calls.append(kind) or sound.SoundResult(True, f"played {kind}"),
    )
    with patch.object(Wizard, "result_view", new_callable=PropertyMock) as view:
        view.return_value = VIEWS["verified"]
        # Explicit Hear works even while sounds are off.
        w.hear_outcome_sound()
        w.set_sounds_enabled(True)
        w.hear_outcome_sound()
    assert calls == [sound.KIND_FINISHED, sound.KIND_FINISHED]


def test_hear_both_plays_finished_then_attention(monkeypatch):
    w = _demo_wizard()
    calls = []
    monkeypatch.setattr(
        sound,
        "play_test",
        lambda kind: calls.append(kind) or sound.SoundResult(True, f"played {kind}"),
    )
    result = w.hear_both_sounds()
    assert result.ok is True
    assert calls == [sound.KIND_FINISHED, sound.KIND_ATTENTION]
    assert "finished" in result.message and "attention" in result.message


def test_gallery_renders_sounds_without_touching_audio(monkeypatch):
    from beamo_wipe import gallery

    def _boom(*a, **k):
        raise AssertionError("spawned audio")

    monkeypatch.setattr(sound, "_run", _boom)
    monkeypatch.setattr(sound, "_popen", _boom)
    html = gallery.gallery_html("en")
    for label in (
        C.SOUND_TOGGLE_OFF,
        C.SOUND_TOGGLE_ON,
        C.SOUND_HEAR,
        C.SOUND_HEAR_AGAIN,
        C.SOUND_OUTCOME_OFF_LIVE,
    ):
        assert label in html, label


def test_shipped_assets_are_valid_bounded_distinct_and_reproducible(tmp_path):
    import subprocess as sp

    assert SOUNDS_DIR.is_dir()
    finished = SOUNDS_DIR / "finished.wav"
    attention = SOUNDS_DIR / "attention.wav"
    assert finished.is_file() and attention.is_file()
    assert finished.read_bytes() != attention.read_bytes()
    for path in (finished, attention):
        assert path.stat().st_size <= 100 * 1024
        with wave.open(str(path), "rb") as wav:
            assert wav.getnchannels() == 1
            assert wav.getsampwidth() == 2
            assert wav.getframerate() in (22050, 44100)
            assert 0 < wav.getnframes() / wav.getframerate() <= 1.5
    maker = ROOT / "scripts/make-outcome-sounds.py"
    assert maker.is_file()
    proc = sp.run(
        ["python3", str(maker), "--out", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "finished.wav").read_bytes() == finished.read_bytes()
    assert (tmp_path / "attention.wav").read_bytes() == attention.read_bytes()
    staging = (ROOT / "scripts/stage_live_assets.py").read_text()
    assert '"finished.wav", "attention.wav"' in staging
    assert 'share / "sounds" / name' in staging
