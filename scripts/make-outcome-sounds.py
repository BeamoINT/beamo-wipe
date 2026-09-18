#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate the offline outcome earcons. Stdlib only, fully deterministic.

finished.wav: two rising tones (erase verified).
attention.wav: three same-pitch beeps (anything else final).

Run from anywhere; without --out the files land in packaging/sounds
(the tracked source; scripts/build-iso.sh stages them into the live
image). Re-running must be byte-identical (pinned by
tests/test_outcome_sounds.py).
"""

from __future__ import annotations

import argparse
import math
import struct
import wave
from pathlib import Path

RATE = 22050
AMPLITUDE = 0.5  # -6 dBFS: clearly audible, never blasting.
FADE_S = 0.010


def _tone(freq: float, seconds: float) -> list[float]:
    count = int(RATE * seconds)
    fade = max(1, int(RATE * FADE_S))
    out = []
    for n in range(count):
        sample = math.sin(2.0 * math.pi * freq * n / RATE)
        edge = min(n, count - 1 - n, fade) / fade
        out.append(sample * edge * AMPLITUDE)
    return out


def _silence(seconds: float) -> list[float]:
    return [0.0] * int(RATE * seconds)


# (kind, [(freq_hz, seconds), ...]) with gaps between tones.
SCORES = {
    "finished": ([(660.0, 0.14), (880.0, 0.22)], 0.06),
    "attention": ([(494.0, 0.11), (494.0, 0.11), (494.0, 0.16)], 0.07),
}


def render(kind: str) -> bytes:
    tones, gap = SCORES[kind]
    samples: list[float] = []
    for index, (freq, seconds) in enumerate(tones):
        if index:
            samples.extend(_silence(gap))
        samples.extend(_tone(freq, seconds))
    frames = struct.pack(f"<{len(samples)}h", *(int(s * 32767) for s in samples))
    return frames, len(samples)


def write_wav(path: Path, kind: str) -> Path:
    frames, _ = render(kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(frames)
    return path


def default_out() -> Path:
    root = Path(__file__).resolve().parent.parent
    return root / "packaging/sounds"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=default_out())
    args = parser.parse_args()
    for kind in ("finished", "attention"):
        path = write_wav(args.out / f"{kind}.wav", kind)
        print(f"{path} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
