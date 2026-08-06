"""Refine word start times against the vocal stem's energy.

Whisper marks a word's start once it is confidently audible — slightly after the
sound actually begins — so onsets read late, most noticeably on phrase-initial
words after a gap. Here we back each start up to where its sound truly starts:
scan the RMS energy envelope backward from Whisper's start while energy stays
voiced, and snap to just after the preceding silence. The move is bounded (never
past the previous word, never more than a lookback window) and only ever earlier,
so connected/legato words — where there is no silence to find — are left alone.

A separate uniform ``lead`` shift gives the karaoke fill a small constant
head-start over the voice, which singers expect.
"""
from __future__ import annotations
from typing import List
import numpy as np
from karaoke.timing import Timing, Line, Word

_HOP = 0.01            # 10 ms envelope hop
_WIN = 0.025           # 25 ms RMS window
_ONSET_FRAC = 0.5      # voiced when energy >= floor + frac*(level_at_start - floor)
_FLOOR_PCT = 10.0      # noise floor = this percentile of the whole envelope


def rms_envelope(samples, sr: int, hop: float = _HOP, win: float = _WIN):
    """Frame-wise RMS energy of (mono-mixed) ``samples``. Returns (env, hop)."""
    samples = np.asarray(samples, dtype=np.float64)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    n = len(samples)
    if n == 0:
        return np.zeros(0), hop
    hop_n = max(1, int(round(hop * sr)))
    win_n = max(1, int(round(win * sr)))
    env = [float(np.sqrt(np.mean(np.square(samples[i:i + win_n]))))
           for i in range(0, n, hop_n) if i < n]
    return np.asarray(env), hop


def noise_floor(env, percentile: float = _FLOOR_PCT) -> float:
    return float(np.percentile(env, percentile)) if len(env) else 0.0


def _idx(t: float, hop: float, n: int) -> int:
    return min(n - 1, max(0, int(round(t / hop))))


def snap_start(env, hop: float, start_t: float, earliest_t: float,
               floor: float, frac: float = _ONSET_FRAC) -> float:
    """Return a start <= ``start_t`` (and >= ``earliest_t``) snapped to the local
    sound onset, or ``start_t`` unchanged when there is no clear onset to snap to."""
    n = len(env)
    if n == 0 or start_t <= earliest_t:
        return start_t
    s = _idx(start_t, hop, n)
    e = _idx(earliest_t, hop, n)
    if e >= s:
        return start_t
    level = float(env[s])
    if level <= floor:                 # start already sits in near-silence
        return start_t
    thr = floor + frac * (level - floor)
    onset, k = s, s - 1
    while k >= e and env[k] >= thr:
        onset, k = k, k - 1
    if onset == s:                     # silence right before start -> already at onset
        return start_t
    if k < e:                          # voiced all the way back -> legato/bleed, don't snap
        return start_t
    return onset * hop


def snap_to_onset(env, hop: float, rough_t: float, floor: float,
                  window: float = 0.75, frac: float = _ONSET_FRAC) -> float:
    """Snap a rough (human-supplied) time to the nearest sung onset.

    Searches +/- ``window`` around ``rough_t`` for upward energy crossings (silence
    -> voice) and returns the crossing time closest to the guess, or ``rough_t``
    unchanged if none is found. Unlike snap_start this is bidirectional and seeded
    by a human mark, so it can search a wide window without misfiring.
    """
    n = len(env)
    if n == 0:
        return rough_t
    lo = _idx(rough_t - window, hop, n)
    hi = _idx(rough_t + window, hop, n)
    if hi <= lo:
        return rough_t
    peak = float(env[lo:hi + 1].max())
    if peak <= floor:
        return rough_t
    thr = floor + frac * (peak - floor)
    crossings = [k + 1 for k in range(lo, hi) if env[k] < thr <= env[k + 1]]
    if not crossings:
        return rough_t
    return min(crossings, key=lambda k: abs(k * hop - rough_t)) * hop


def load_env(vocals_path):
    """Read a vocal stem and return ``(env, hop, floor)`` — the shared setup
    every snap_start / snap_to_onset caller needs (soundfile read + RMS envelope
    + noise floor), in one place."""
    import soundfile as sf
    samples, sr = sf.read(str(vocals_path))
    env, hop = rms_envelope(samples, sr)
    return env, hop, noise_floor(env)


def snap_marks(vocals_path, marks: dict, window: float = 0.75) -> dict:
    """Snap each ``{key: rough_time}`` to its nearest sung onset (``load_env``
    then ``snap_to_onset`` per value); keys pass through unchanged."""
    env, hop, floor = load_env(vocals_path)
    return {k: snap_to_onset(env, hop, t, floor, window=window)
            for k, t in marks.items()}


def refine_timing(timing: Timing, vocals_path, *, onset_snap: bool = True,
                  lookback: float = 0.25, lead: float = 0.0) -> Timing:
    """Apply onset snapping and a uniform lead to every word, preserving the line
    structure and keeping starts monotonic / non-overlapping."""
    words = [w for ln in timing.lines for w in ln.words]
    counts = [len(ln.words) for ln in timing.lines]

    if onset_snap and words:
        env, hop, floor = load_env(vocals_path)
        prev_end = 0.0
        snapped: List[Word] = []
        for w in words:
            earliest = max(prev_end, w.start - lookback)
            ns = min(snap_start(env, hop, w.start, earliest, floor), w.end)
            snapped.append(w.retimed(ns, w.end))
            prev_end = w.end
        words = snapped

    if lead:
        words = [w.retimed(max(0.0, w.start - lead), max(0.0, w.end - lead))
                 for w in words]

    out, i = [], 0
    for li, c in enumerate(counts):
        out.append(Line(words=words[i:i + c], wrap=timing.lines[li].wrap))
        i += c
    return Timing(lines=out)
