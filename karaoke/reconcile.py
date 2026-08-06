"""Map a known lyric word sequence onto ASR word timings.

The ASR pass (Whisper) yields timestamped words for what is actually sung.
We sequence-align the known lyrics against that ASR transcript and let matched
words borrow the ASR timing as anchors; unmatched runs are interpolated between
neighbouring anchors. Because anchors are spread through the song, a bad patch
(e.g. a screamed/overlapping chorus the ASR mishears) stays local instead of
drifting the rest of the track.
"""
from __future__ import annotations
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import List, Optional, Tuple

# Fallback word duration (seconds) for runs with no surrounding anchor to span.
_EST_WORD = 0.35
# Every word must last at least this long so its letter-fill is actually visible
# (zero-duration words never animate). Dense, repeated outros where the ASR
# anchors coincide are the source of collapsed runs.
_MIN_WORD = 0.30
# Cap a single word's fill span; a held/screamed note the ASR timed at tens of
# seconds should fill in a sane window and then hold, not crawl for the whole note.
_MAX_WORD = 4.0


@dataclass
class AsrWord:
    text: str
    start: float
    end: float


def _norm(word: str) -> str:
    """Lowercase and keep only alphanumerics and apostrophes, for matching."""
    return "".join(c for c in word.lower() if c.isalnum() or c == "'")


def anchor_count(known_words: List[str], asr_words: List[AsrWord]) -> int:
    """How many known lyric words a given ASR transcript anchors (matches). Used
    to pick the best of several Whisper draws (best-of-N)."""
    if not asr_words:
        return 0
    a = [_norm(w) for w in known_words]
    b = [_norm(w.text) for w in asr_words]
    return sum(size for _, _, size in
               SequenceMatcher(a=a, b=b, autojunk=False).get_matching_blocks())


def _weight(word: str) -> float:
    """Relative sung-length of a word: its letter count (>=1). Used to share an
    interpolated gap so long words get proportionally more time than short ones,
    which tracks singing far better than an even per-word split."""
    return float(max(1, len(_norm(word))))


def reconcile(known_words: List[str],
              asr_words: List[AsrWord]) -> List[Tuple[float, float]]:
    """Return a (start, end) for every known word."""
    n = len(known_words)
    times: List[Optional[Tuple[float, float]]] = [None] * n
    if asr_words:
        a = [_norm(w) for w in known_words]
        b = [_norm(w.text) for w in asr_words]
        for i, j, size in SequenceMatcher(a=a, b=b, autojunk=False).get_matching_blocks():
            for k in range(size):
                times[i + k] = (asr_words[j + k].start, asr_words[j + k].end)
    weights = [_weight(w) for w in known_words]
    return _enforce_bounds(_fill_gaps(times, weights), _MIN_WORD, _MAX_WORD)


def _place_weighted(out: list, lo: int, hi: int, t0: float, t1: float,
                    weights: List[float]) -> None:
    """Lay words [lo, hi) sequentially across [t0, t1], each given a share of the
    span proportional to its weight."""
    ws = weights[lo:hi]
    total = sum(ws) or 1.0
    span = max(0.0, t1 - t0)
    t = t0
    for k, w in enumerate(ws):
        d = span * w / total
        out[lo + k] = (t, t + d)
        t += d


def _fill_gaps(times: List[Optional[Tuple[float, float]]],
               weights: List[float]) -> List[Tuple[float, float]]:
    n = len(times)
    anchors = [i for i, v in enumerate(times) if v is not None]
    if not anchors:
        # No ASR matches at all — lay words out sequentially as a last resort.
        return [(i * _EST_WORD, (i + 1) * _EST_WORD) for i in range(n)]

    out: List[Optional[Tuple[float, float]]] = list(times)

    # Leading run before the first anchor: pack it just ahead of that anchor,
    # sharing the available span by word weight.
    first = anchors[0]
    if first > 0:
        s0 = times[first][0]
        span = min(s0, first * _EST_WORD)
        _place_weighted(out, 0, first, s0 - span, s0, weights)

    # Interior runs: share the gap between the bounding anchors by word weight.
    for p, q in zip(anchors, anchors[1:]):
        if q - p - 1 <= 0:
            continue
        ep = times[p][1]
        sq = times[q][0]
        _place_weighted(out, p + 1, q, ep, max(ep, sq), weights)

    # Trailing run after the last anchor (no bounding time): pace at _EST_WORD.
    last = anchors[-1]
    if last < n - 1:
        el = times[last][1]
        for k in range(n - 1 - last):
            out[last + 1 + k] = (el + k * _EST_WORD, el + (k + 1) * _EST_WORD)

    return out  # type: ignore[return-value]


def _enforce_bounds(times: List[Tuple[float, float]],
                    min_dur: float, max_dur: float) -> List[Tuple[float, float]]:
    """Clamp each word to a sane fill span, keeping times monotonic.

    1. Cap over-long words by shrinking the *end* (a held note fills then holds);
       this only opens gaps, never overlaps.
    2. Guarantee a minimum duration. When a word has to grow into the next word's
       start (the collapsed-run case, where anchors coincide), push that neighbour
       forward. The shove cascades only through the coincident cluster and is
       absorbed by the first following word that already has slack, so it stays
       local instead of drifting the rest of the track.
    """
    out = list(times)
    for i, (s, e) in enumerate(out):
        if e - s > max_dur:
            out[i] = (s, s + max_dur)
    for i in range(len(out)):
        s, e = out[i]
        if e - s < min_dur:
            e = s + min_dur
            out[i] = (s, e)
        if i + 1 < len(out):
            ns, ne = out[i + 1]
            if ns < e:
                out[i + 1] = (e, max(ne, e))
    return out
