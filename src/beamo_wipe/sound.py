# SPDX-License-Identifier: GPL-3.0-or-later
"""Audio output controls for the screen-reader path.

Allowlisted pactl/spd-say/espeak-ng/pgrep calls only; never a shell string.
Every call runs only on the live USB so previews never touch host audio.
Nothing here raises: failures return structured results with customer words.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import shutil
import subprocess
import threading
from typing import List, Optional, Tuple

from beamo_wipe import copy as C
from beamo_wipe.safety import running_on_live_usb

# Shipped on the live image: pulseaudio-utils (pactl), speech-dispatcher
# (spd-say), espeak-ng, procps (pgrep).
_PACTL = "pactl"
_SPD_SAY = "spd-say"
_ESPEAK = "espeak-ng"
_PGREP = "pgrep"
_PAPLAY = "paplay"
_PULSEAUDIO = "pulseaudio"
_ALLOWED_BINARIES = frozenset(
    {_PACTL, _SPD_SAY, _ESPEAK, _PGREP, _PAPLAY, _PULSEAUDIO}
)

_PACTL_TIMEOUT = 5
_SPEECH_TIMEOUT = 20
_PLAY_TIMEOUT = 10
VOLUME_STEP = 10
VOLUME_MAX = 100

TEST_PHRASE = C.SOUND_TEST_PHRASE

_SINK_ID_RE = re.compile(r"^[\w.:+-]+$")
_VOLUME_RE = re.compile(r"(\d+)%")


@dataclass(frozen=True)
class SoundOutput:
    id: str
    label: str
    detail: str
    is_default: bool


@dataclass(frozen=True)
class SoundState:
    available: bool
    message: str
    outputs: tuple
    volume_percent: Optional[int] = None
    muted: Optional[bool] = None


@dataclass(frozen=True)
class SoundResult:
    ok: bool
    message: str


def _on_live() -> bool:
    try:
        return bool(running_on_live_usb())
    except Exception:
        return False


def _run(tool: str, args: List[str], timeout: int):
    """Allowlisted exec. Returns the completed process, or None."""
    if tool not in _ALLOWED_BINARIES:
        return None
    resolved = shutil.which(tool)
    if not resolved:
        return None
    try:
        return subprocess.run(
            [resolved, *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None


LABEL_HEADPHONES = "Headphones"
LABEL_HDMI = "HDMI sound"
LABEL_USB = "USB sound"
LABEL_BLUETOOTH = "Bluetooth sound"
LABEL_SPEAKERS = "Speakers"
LABEL_DEFAULT = "Sound output"


def _label_for(name: str) -> str:
    lowered = name.lower()
    if "headphone" in lowered or "headset" in lowered:
        return LABEL_HEADPHONES
    if "hdmi" in lowered:
        return LABEL_HDMI
    if "usb" in lowered:
        return LABEL_USB
    if "bluez" in lowered or "bluetooth" in lowered:
        return LABEL_BLUETOOTH
    if "analog" in lowered or "speaker" in lowered:
        return LABEL_SPEAKERS
    return LABEL_DEFAULT


def _labeled(names: List[str]) -> List[Tuple[str, str]]:
    counts: dict = {}
    labeled = []
    for name in names:
        base = _label_for(name)
        counts[base] = counts.get(base, 0) + 1
        label = base if counts[base] == 1 else f"{base} {counts[base]}"
        labeled.append((name, label))
    return labeled


def _valid_sink_id(sink_id: object) -> bool:
    return isinstance(sink_id, str) and bool(_SINK_ID_RE.match(sink_id))


def _volume_of(sink_id: str) -> Optional[int]:
    proc = _run(_PACTL, ["get-sink-volume", sink_id], _PACTL_TIMEOUT)
    if proc is None or proc.returncode != 0:
        return None
    match = _VOLUME_RE.search(proc.stdout or "")
    return int(match.group(1)) if match else None


def _mute_of(sink_id: str) -> Optional[bool]:
    proc = _run(_PACTL, ["get-sink-mute", sink_id], _PACTL_TIMEOUT)
    if proc is None or proc.returncode != 0:
        return None
    text = (proc.stdout or "").strip().lower()
    if "yes" in text:
        return True
    if "no" in text:
        return False
    return None


def list_outputs() -> SoundState:
    """Current outputs plus the default sink's volume and mute state."""
    if not _on_live():
        return SoundState(False, C.SOUND_OFF_LIVE, ())
    short = _run(_PACTL, ["list", "short", "sinks"], _PACTL_TIMEOUT)
    if short is None or short.returncode != 0:
        return SoundState(False, C.SOUND_NO_OUTPUT, ())
    names = []
    for line in (short.stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and _valid_sink_id(parts[1].strip()):
            names.append(parts[1].strip())
    if not names:
        return SoundState(False, C.SOUND_NO_OUTPUT, ())
    default = ""
    got = _run(_PACTL, ["get-default-sink"], _PACTL_TIMEOUT)
    if got is not None and got.returncode == 0:
        default = (got.stdout or "").strip().split("\n")[0].strip()
    outputs = tuple(
        SoundOutput(id=name, label=label, detail=name, is_default=(name == default))
        for name, label in _labeled(names)
    )
    target = default if default in names else ""
    volume = _volume_of(target) if target else None
    muted = _mute_of(target) if target else None
    return SoundState(True, "", outputs, volume, muted)


def set_output(sink_id: str) -> SoundResult:
    if not _on_live():
        return SoundResult(False, C.SOUND_OFF_LIVE)
    if not _valid_sink_id(sink_id):
        return SoundResult(False, C.SOUND_ACTION_FAILED)
    proc = _run(_PACTL, ["set-default-sink", sink_id], _PACTL_TIMEOUT)
    if proc is None or proc.returncode != 0:
        return SoundResult(False, C.SOUND_ACTION_FAILED)
    return SoundResult(True, "")


def nudge_volume(sink_id: str, delta: int) -> SoundResult:
    if not _on_live():
        return SoundResult(False, C.SOUND_OFF_LIVE)
    if not _valid_sink_id(sink_id):
        return SoundResult(False, C.SOUND_ACTION_FAILED)
    current = _volume_of(sink_id)
    if current is None:
        return SoundResult(False, C.SOUND_ACTION_FAILED)
    target = max(0, min(VOLUME_MAX, current + int(delta)))
    proc = _run(_PACTL, ["set-sink-volume", sink_id, f"{target}%"], _PACTL_TIMEOUT)
    if proc is None or proc.returncode != 0:
        return SoundResult(False, C.SOUND_ACTION_FAILED)
    return SoundResult(True, "")


def set_muted(sink_id: str, muted: bool) -> SoundResult:
    if not _on_live():
        return SoundResult(False, C.SOUND_OFF_LIVE)
    if not _valid_sink_id(sink_id):
        return SoundResult(False, C.SOUND_ACTION_FAILED)
    proc = _run(
        _PACTL, ["set-sink-mute", sink_id, "1" if muted else "0"], _PACTL_TIMEOUT
    )
    if proc is None or proc.returncode != 0:
        return SoundResult(False, C.SOUND_ACTION_FAILED)
    return SoundResult(True, "")


def play_speech_test() -> SoundResult:
    """Speak the test phrase through Orca's chain, then espeak-ng."""
    if not _on_live():
        return SoundResult(False, C.SOUND_OFF_LIVE)
    proc = _run(_SPD_SAY, ["-w", TEST_PHRASE], _SPEECH_TIMEOUT)
    if proc is not None and proc.returncode == 0:
        return SoundResult(True, C.SOUND_TEST_PLAYED)
    proc = _run(_ESPEAK, [TEST_PHRASE], _SPEECH_TIMEOUT)
    if proc is not None and proc.returncode == 0:
        return SoundResult(True, C.SOUND_TEST_PLAYED)
    return SoundResult(False, C.SOUND_TEST_FAILED)


# Outcome earcons. Shipped WAVs staged by scripts/build-iso.sh; paplay
# ships with pulseaudio-utils, so no new live package. Kinds are fixed
# vocabulary, never user input.
KIND_FINISHED = "finished"
KIND_ATTENTION = "attention"
SOUNDS_DIR = "/usr/share/beamo-wipe/sounds"
_ASSETS = {KIND_FINISHED: "finished.wav", KIND_ATTENTION: "attention.wav"}


def kind_for_code(code: str) -> str:
    """Only verified completion sounds finished; everything else needs attention."""
    return KIND_FINISHED if code == "verified" else KIND_ATTENTION


def asset_path(kind: str) -> str:
    name = _ASSETS.get(kind, "")
    return f"{SOUNDS_DIR}/{name}" if name else ""


def ensure_audio() -> bool:
    """Start the daemon when missing. Idempotent; never raises."""
    if not _on_live():
        return False
    proc = _run(_PULSEAUDIO, ["--start", "--exit-idle-time=60"], _PACTL_TIMEOUT)
    return proc is not None and proc.returncode == 0


def _popen(tool: str, args: List[str]):
    """Allowlisted fire-and-forget spawn. Returns the Popen, or None."""
    if tool not in _ALLOWED_BINARIES:
        return None
    resolved = shutil.which(tool)
    if not resolved:
        return None
    try:
        proc = subprocess.Popen(
            [resolved, *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    reaper = threading.Thread(target=proc.wait, daemon=True)
    reaper.start()
    return proc


def _ready(kind: str):
    """(ok, message). Shared gate: known kind, live, output, unmuted."""
    if kind not in _ASSETS:
        return False, C.SOUND_ACTION_FAILED
    if not _on_live():
        return False, C.SOUND_OUTCOME_OFF_LIVE
    state = list_outputs()
    if not state.available:
        return False, C.SOUND_NO_OUTPUT_PLAY
    if state.muted:
        return False, C.SOUND_MUTED_SKIP
    return True, ""


def play_outcome(kind: str) -> SoundResult:
    """Fire-and-forget auto-play. Never blocks; success stays silent."""
    ready, message = _ready(kind)
    if not ready:
        return SoundResult(False, message)
    ensure_audio()
    if _popen(_PAPLAY, [asset_path(kind)]) is None:
        return SoundResult(False, C.SOUND_PLAY_FAILED)
    return SoundResult(True, "")


def play_test(kind: str) -> SoundResult:
    """Blocking explicit test with truthful feedback."""
    ready, message = _ready(kind)
    if not ready:
        return SoundResult(False, message)
    ensure_audio()
    proc = _run(_PAPLAY, [asset_path(kind)], _PLAY_TIMEOUT)
    if proc is None or proc.returncode != 0:
        return SoundResult(False, C.SOUND_PLAY_FAILED)
    played = (
        C.SOUND_PLAYING_FINISHED
        if kind == KIND_FINISHED
        else C.SOUND_PLAYING_ATTENTION
    )
    return SoundResult(True, played)


def orca_running() -> Optional[bool]:
    """True/False when pgrep answers, None when it cannot be told."""
    if not _on_live():
        return None
    proc = _run(_PGREP, ["-x", "orca"], _PACTL_TIMEOUT)
    if proc is None:
        return None
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    return None


def resolve_output(preferred_id: str, state: SoundState):
    """Remembered choice first, then the default sink, then the first."""
    if not state.outputs:
        return None
    for output in state.outputs:
        if output.id == preferred_id:
            return output
    for output in state.outputs:
        if output.is_default:
            return output
    return state.outputs[0]


def apply_remembered_output(wizard):
    """Re-apply the wizard's recorded choice. None when there is none."""
    remembered = getattr(wizard, "sound_output", "") or ""
    if not remembered:
        return None
    return set_output(remembered)
