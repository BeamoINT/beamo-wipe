"""Outcome audio must follow the settled, evidenced result."""

from unittest.mock import PropertyMock, patch

from beamo_wipe import sound
from beamo_wipe.demo import make_demo_wizard
from beamo_wipe.models import Screen, WipeResult
from beamo_wipe.outcomes import VIEWS
from beamo_wipe.wizard import Wizard


def test_done_during_terminal_evidence_save_does_not_latch_attention_sound(monkeypatch):
    wizard = make_demo_wizard()
    wizard.preview = False
    wizard.screen = Screen.DONE
    wizard.wipe_result = WipeResult(True, 0, "Erase completed", "/tmp/fake-nwipe.log")
    wizard.set_sounds_enabled(True)
    wizard._finishing = True
    wizard._evidence_saving = True
    played = []
    monkeypatch.setattr(
        sound,
        "play_outcome",
        lambda kind: played.append(kind) or sound.SoundResult(True, ""),
    )

    assert wizard.maybe_play_outcome_sound() is None
    assert wizard.hear_outcome_sound() is None
    assert played == []
    assert wizard._sound_played_for is None

    wizard._evidence_saving = False
    wizard._finishing = False
    with patch.object(Wizard, "result_view", new_callable=PropertyMock) as view:
        view.return_value = VIEWS["verified"]
        assert wizard.maybe_play_outcome_sound() == sound.SoundResult(True, "")
    assert played == [sound.KIND_FINISHED]


def test_successful_evidence_retry_can_update_the_outcome_sound(monkeypatch):
    wizard = make_demo_wizard()
    wizard.preview = False
    wizard.screen = Screen.DONE
    wizard.wipe_result = WipeResult(True, 0, "Erase completed", "/tmp/fake-nwipe.log")
    wizard.evidence_error = "The report evidence could not be saved."
    wizard.set_sounds_enabled(True)
    played = []
    monkeypatch.setattr(
        sound,
        "play_outcome",
        lambda kind: played.append(kind) or sound.SoundResult(True, ""),
    )

    with patch.object(Wizard, "result_view", new_callable=PropertyMock) as view:
        view.return_value = VIEWS["indeterminate"]
        wizard.maybe_play_outcome_sound()
        assert played == [sound.KIND_ATTENTION]
        wizard.evidence_error = None
        view.return_value = VIEWS["verified"]
        wizard.maybe_play_outcome_sound()
    assert played == [sound.KIND_ATTENTION, sound.KIND_FINISHED]
