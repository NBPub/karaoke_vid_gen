"""Manual timing corrections that take coarse human input and stay frame-precise.

You point at a line and a rough time ("this line really starts around 1:06"); the
time is snapped to the actual sung onset in the vocal stem, so you never have to
eyeball tenths of a second. Two operations:

- shift_line: move a whole line so its first word lands on a (snapped) start,
  preserving the line's internal rhythm and duration.
- copy_line_timing: lay one line's per-word relative timing onto another line at a
  (snapped) start — for fixing a badly-anchored repeat from a clean one.
"""
from __future__ import annotations
from typing import List, Tuple
from karaoke.timing import Timing, Line, Word


def shift_line(timing: Timing, line_idx: int, new_start: float) -> Timing:
    """Shift every word in a line by the same delta so the first word starts at
    ``new_start`` (keeps the line's internal timing and length)."""
    lines = list(timing.lines)
    line = lines[line_idx]
    delta = new_start - line.words[0].start
    lines[line_idx] = Line(words=[w.retimed(w.start + delta, w.end + delta)
                                   for w in line.words], wrap=line.wrap)
    return Timing(lines=lines)


def copy_line_timing(timing: Timing, src_idx: int, dst_idx: int,
                     start: float) -> Timing:
    """Copy the source line's per-word offsets onto the destination line, anchored
    at ``start``. The lines should be the same lyric; extra dest words reuse the
    last source offset."""
    lines = list(timing.lines)
    src = lines[src_idx].words
    s0 = src[0].start
    new_words = []
    for i, w in enumerate(lines[dst_idx].words):
        sw = src[i] if i < len(src) else src[-1]
        new_words.append(w.retimed(start + (sw.start - s0), start + (sw.end - s0)))
    lines[dst_idx] = Line(words=new_words, wrap=lines[dst_idx].wrap)
    return Timing(lines=lines)


def reflow_anchors(timing: Timing, anchors: dict, *, forced=None, samples=None,
                   sr=None) -> Timing:
    """Re-time a run of lines from per-line start anchors.

    The anchored line-starts are firm pins. The lead (non-bg) words between
    consecutive anchors are placed across the window by forced alignment (or
    weighted interpolation when no aligner is given); background words keep their
    hand-set times. Words outside the [first, last] anchored span keep their
    times. Needs >= 2 anchors (the last bounds the run).
    """
    from karaoke.realign import place_window
    if len(anchors) < 2:
        raise ValueError("reflow needs at least 2 line anchors")
    words = [w for ln in timing.lines for w in ln.words]
    counts = [len(ln.words) for ln in timing.lines]
    first_idx, k = [], 0
    for n in counts:
        first_idx.append(k)
        k += n
    out = [(w.start, w.end) for w in words]
    fa = sorted((first_idx[L], t) for L, t in anchors.items())
    for (i0, t0), (i1, t1) in zip(fa, fa[1:]):
        lead_j = [j for j in range(i0, i1) if not words[j].bg]
        run = [words[j].text for j in lead_j]
        spans = place_window(run, t0, max(t0, t1), forced=forced,
                             samples=samples, sr=sr)
        for m, j in enumerate(lead_j):
            out[j] = spans[m]
        if not words[i0].bg:
            out[i0] = (t0, out[i0][1])   # reassert the firm pin on the anchored start
    iL, tL = fa[-1]
    out[iL] = (tL, max(words[iL].end, tL))  # pin the final anchor's first word
    timed = [words[i].retimed(out[i][0], out[i][1]) for i in range(len(words))]
    wraps = [ln.wrap for ln in timing.lines]
    res, p = [], 0
    for li, n in enumerate(counts):
        res.append(Line(words=timed[p:p + n], wrap=wraps[li]))
        p += n
    return Timing(lines=res)


def is_marked_for_reflow(line: Line) -> bool:
    """A line the user marked to re-anchor: clear the line's word times and set the
    first word's start to the desired start — detected by the first word's end <= 0."""
    return len(line.words) > 0 and line.words[0].end <= 0.0


def marked_line_end(line: Line):
    """The optional approximate line-end a user marked on the last NON-background
    word (its start set to 0, end > 0), or None when unmarked / no eligible word.
    Needs >= 2 non-bg words (the first carries the start marker, the last the end)."""
    nb = [w for w in line.words if not w.bg]
    if len(nb) >= 2:
        w = nb[-1]
        if w.start <= 0.0 and w.end > 0.0:
            return w.end
    return None


def _is_bg_only(line: Line) -> bool:
    """A line with no lead words — a pure background-vocal interjection. These
    overlap the lead and must not gate the lead's reflow timeline."""
    return len(line.words) > 0 and all(w.bg for w in line.words)


def reflow_marked(timing: Timing, anchors: dict, *, forced=None, samples=None,
                  sr=None, search_margin: float = 1.0) -> Timing:
    """Recompute each marked line's words. With a `forced` aligner, place them by
    forced alignment within a padded, prev-end-clamped window (the aligner owns
    the first start and last end); without one, spread them by length from the
    anchor start to the next line (the pre-existing interpolation behavior).
    Only marked lines change. Background-only interjection lines are skipped
    entirely: they overlap the lead and must not gate its forward timeline (a late
    bg interjection ordered before a lead line would otherwise clamp it flat)."""
    from karaoke.realign import place_window, interpolate_window
    from karaoke.reconcile import _weight, _EST_WORD
    lines = list(timing.lines)
    nlines = len(lines)

    def next_lead_bound(L):
        """Start time bounding line L's window: the next non-bg-only line's anchor
        (if marked) or its start. bg-only interjections are skipped so they don't
        squeeze the lead. None when no lead line follows."""
        for j in range(L + 1, nlines):
            if _is_bg_only(lines[j]):
                continue
            return anchors[j] if j in anchors else lines[j].start
        return None

    prev_end = 0.0
    for L in range(nlines):
        if _is_bg_only(lines[L]):
            continue                       # bg interjections don't gate the lead timeline
        if L not in anchors:
            prev_end = lines[L].end
            continue
        ln = lines[L]
        lead_idx = [k for k, w in enumerate(ln.words) if not w.bg]
        if not lead_idx:                   # defensive; bg-only already skipped above
            prev_end = lines[L].end
            continue
        lead_texts = [ln.words[k].text for k in lead_idx]
        guess = anchors[L]
        nxt = next_lead_bound(L)
        if forced is not None:
            approx_end = marked_line_end(ln)
            left = max(prev_end, guess - search_margin)
            if approx_end is not None:
                right = approx_end + search_margin
            elif nxt is not None:
                right = max(left, nxt)
            else:
                right = left + sum(_weight(x) for x in lead_texts) * _EST_WORD
            spans = place_window(lead_texts, left, right, forced=forced,
                                 samples=samples, sr=sr)
        else:
            t1 = nxt if nxt is not None else guess + sum(_weight(x) for x in lead_texts) * _EST_WORD
            spans = interpolate_window(lead_texts, guess, max(guess, t1))
        new_words = list(ln.words)
        for m, k in enumerate(lead_idx):
            w = ln.words[k]
            new_words[k] = Word(w.text, spans[m][0], spans[m][1], bg=False)
        lines[L] = Line(words=new_words, wrap=ln.wrap)
        prev_end = lines[L].end
    return Timing(lines=lines)


def changed_runs(baseline: Timing, edited: Timing, eps: float = 0.05) -> List[List[int]]:
    """Flat word indices whose start moved from the baseline, grouped into
    contiguous runs (each run is one hand-edited phrase)."""
    bw = [w for ln in baseline.lines for w in ln.words]
    cw = [w for ln in edited.lines for w in ln.words]
    if len(bw) != len(cw):
        raise ValueError(f"word count differs from baseline ({len(bw)} vs {len(cw)})")
    changed = [i for i in range(len(cw)) if abs(cw[i].start - bw[i].start) > eps]
    runs: List[List[int]] = []
    for i in changed:
        if runs and i == runs[-1][-1] + 1:
            runs[-1].append(i)
        else:
            runs.append([i])
    return runs


def apply_run_shifts(timing: Timing, runs: List[List[int]], deltas: dict) -> Timing:
    """Shift each run by deltas[run[0]] (start and end), preserving the user's
    internal spacing. Keeps the line structure."""
    cw = [w for ln in timing.lines for w in ln.words]
    counts = [len(ln.words) for ln in timing.lines]
    wraps = [ln.wrap for ln in timing.lines]
    starts = [w.start for w in cw]
    ends = [w.end for w in cw]
    for run in runs:
        d = deltas.get(run[0], 0.0)
        for i in run:
            starts[i] += d
            ends[i] += d
    timed = [cw[i].retimed(starts[i], max(ends[i], starts[i])) for i in range(len(cw))]
    out, k = [], 0
    for li, n in enumerate(counts):
        out.append(Line(words=timed[k:k + n], wrap=wraps[li]))
        k += n
    return Timing(lines=out)


def snap_edits(baseline: Timing, edited: Timing, vocals_path, *,
               window: float = 0.6, snap: bool = True):
    """Snap each hand-edited phrase's first word onto its vocal onset and shift the
    phrase by that delta. Returns (new_timing, runs, deltas)."""
    runs = changed_runs(baseline, edited)
    cw = [w for ln in edited.lines for w in ln.words]
    deltas: dict = {}
    if runs and snap:
        from karaoke.onsets import load_env, snap_to_onset
        env, hop, floor = load_env(vocals_path)
        for run in runs:
            f = run[0]
            deltas[f] = snap_to_onset(env, hop, cw[f].start, floor, window=window) - cw[f].start
    return apply_run_shifts(edited, runs, deltas), runs, deltas


def apply_edits(timing: Timing, vocals_path, edits: List[Tuple],
                snap: bool = True, window: float = 0.75) -> Timing:
    """Apply a list of edits, snapping each rough time to a vocal onset first.

    Each edit is ("shift", line_idx, rough_t) or ("copy", src_idx, dst_idx, rough_t).
    """
    env = hop = floor = None
    if snap and edits:
        from karaoke.onsets import load_env
        env, hop, floor = load_env(vocals_path)

    def precise(rough_t: float) -> float:
        if not snap or env is None:
            return rough_t
        from karaoke.onsets import snap_to_onset
        return snap_to_onset(env, hop, rough_t, floor, window=window)

    for edit in edits:
        if edit[0] == "shift":
            _, line_idx, rough_t = edit
            timing = shift_line(timing, line_idx, precise(rough_t))
        elif edit[0] == "copy":
            _, src_idx, dst_idx, rough_t = edit
            timing = copy_line_timing(timing, src_idx, dst_idx, precise(rough_t))
        else:
            raise ValueError(f"unknown edit op: {edit[0]}")
    return timing
