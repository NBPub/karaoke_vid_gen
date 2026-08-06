from __future__ import annotations
import numpy as np
from karaoke.timeparse import parse_time as _parse_time

# Crossfade seconds applied at each edge where the original mix is spliced back
# into the instrumental. Raise to smooth boundaries, lower for sharper cuts.
# This is the single knob for the no-extract splice — edit it here.
FADE_SECONDS = 0.1


def parse_intervals(text: str, duration: float | None = None):
    """Parse no_extract.txt content into a list of (start, end) second pairs.
    Skips blank lines and '#' comments. Raises ValueError on a malformed line or
    start >= end. When `duration` is given, clamps each interval to [0, duration]
    and drops any that become empty (with a note)."""
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "-" not in line:
            raise ValueError(f"bad interval line (expected START-END): {raw!r}")
        a, b = line.split("-", 1)
        try:
            start, end = _parse_time(a), _parse_time(b)
        except ValueError:
            raise ValueError(f"bad time in interval line: {raw!r}")
        if start >= end:
            raise ValueError(f"interval start >= end: {raw!r}")
        if duration is not None:
            start, end = max(0.0, start), min(duration, end)
            if start >= end:
                print(f"[no_extract] interval out of range, skipped: {line}")
                continue
        out.append((start, end))
    return out


def splice_original(instr: np.ndarray, song: np.ndarray, sr: int, intervals,
                    fade_seconds: float = FADE_SECONDS) -> np.ndarray:
    """Return a copy of `instr` with `song` spliced over each (start, end) second
    interval, linearly crossfaded over `fade_seconds` at each edge. Handles mono
    (n,) and multi-channel (n, ch). `instr` and `song` must share `sr` and length
    (caller truncates to the shorter first)."""
    out = np.array(instr, copy=True)
    n = out.shape[0]
    fade = max(1, int(round(fade_seconds * sr)))

    def ramp(length: int, up: bool) -> np.ndarray:
        r = np.linspace(0.0, 1.0, length, endpoint=False)
        if not up:
            r = r[::-1]
        return r.reshape((-1,) + (1,) * (out.ndim - 1))  # broadcast over channels

    for start, end in intervals:
        s = max(0, min(n, int(round(start * sr))))
        e = max(0, min(n, int(round(end * sr))))
        if e <= s:
            continue
        f = min(fade, (e - s) // 2)        # shrink fades to fit short intervals
        out[s + f:e - f] = song[s + f:e - f]
        if f > 0:
            up = ramp(f, up=True)          # 0 -> 1
            out[s:s + f] = instr[s:s + f] * (1 - up) + song[s:s + f] * up
            down = ramp(f, up=False)       # 1 -> 0
            out[e - f:e] = song[e - f:e] * down + instr[e - f:e] * (1 - down)
    return out
