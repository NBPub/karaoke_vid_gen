"""Localized word placement for nudge reflows.

Two placement strategies fill a time window [t0, t1] with a run of words:
`interpolate_window` (char-length weighted spread — the fallback) and a forced
aligner (`ForcedAligner`) that reports real per-word timing from the vocal stem.
`place_window` picks the aligner when available and falls back to interpolation
on any failure.
"""
from __future__ import annotations
from typing import Dict, List, Tuple
from karaoke.reconcile import _weight, _place_weighted


def interpolate_window(words: List[str], t0: float, t1: float) -> List[Tuple[float, float]]:
    """Spread `words` across [t0, t1], each word's share proportional to its
    letter count. The first word starts at t0 and the last ends at t1."""
    weights = [_weight(w) for w in words]
    out: List[Tuple[float, float]] = [(0.0, 0.0)] * len(words)
    _place_weighted(out, 0, len(words), t0, max(t0, t1), weights)
    return out


def _offset_and_fill(words: List[str], aligned_rel: Dict[int, Tuple[float, float]],
                     t0: float) -> List[Tuple[float, float]]:
    """Shift clip-relative spans (`aligned_rel`, index -> (start, end)) into
    absolute time by t0; words missing from `aligned_rel` (unalignable) get a
    zero-length span at the most recent end, preserving order and monotonicity."""
    out: List[Tuple[float, float]] = []
    last_end = t0
    for i in range(len(words)):
        if i in aligned_rel:
            s, e = t0 + aligned_rel[i][0], t0 + aligned_rel[i][1]
            out.append((s, e))
            last_end = e
        else:
            out.append((last_end, last_end))
    return out


def place_window(words: List[str], t0: float, t1: float, *, forced,
                 samples, sr) -> List[Tuple[float, float]]:
    """Place `words` across [t0, t1]: forced alignment when `forced` is provided
    and succeeds, otherwise weighted interpolation. Any aligner failure or empty
    result falls back to interpolation for this window."""
    if forced is not None:
        try:
            spans = forced.align_window(samples, sr, t0, t1, words)
            if spans:
                return spans
        except Exception:
            pass
    return interpolate_window(words, t0, t1)


class ForcedAligner:
    """Loads the MMS_FA forced-alignment model once and aligns a word run inside
    an audio window. Reused across every window in a nudge run."""

    def __init__(self, device: str = "cuda"):
        import torch
        from torchaudio.pipelines import MMS_FA as bundle
        self._torch = torch
        self._bundle = bundle
        self.device = device if torch.cuda.is_available() else "cpu"
        self._artifacts = (bundle.get_model().to(self.device), bundle.get_tokenizer(),
                           bundle.get_aligner(),
                           {c for c, idx in bundle.get_dict().items() if idx != 0},
                           bundle.sample_rate)

    def align_window(self, samples, sr, t0: float, t1: float,
                     words: List[str]) -> List[Tuple[float, float]]:
        import numpy as np
        import torchaudio
        from karaoke.align import _align_mono_waveform

        lo = max(0, int(round(t0 * sr)))
        hi = min(len(samples), int(round(t1 * sr)))
        clip = np.asarray(samples, dtype=np.float64)[lo:hi]
        if clip.ndim > 1:
            clip = clip.mean(axis=1)
        if clip.size == 0:
            return []
        wav = self._torch.tensor(clip, dtype=self._torch.float32).unsqueeze(0)
        wav = torchaudio.functional.resample(wav, sr, self._bundle.sample_rate).to(self.device)
        aligned_rel = _align_mono_waveform(self._artifacts, wav, words)
        if not aligned_rel:
            return []
        return _offset_and_fill(words, aligned_rel, t0)
