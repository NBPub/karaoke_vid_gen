from __future__ import annotations
from dataclasses import dataclass
from typing import List
from karaoke.timing import Timing, Line, Word


def word_fill_fraction(word: Word, t: float) -> float:
    if word.end <= word.start:
        return 1.0 if t >= word.start else 0.0
    if t <= word.start:
        return 0.0
    if t >= word.end:
        return 1.0
    return (t - word.start) / (word.end - word.start)


def lead_in_seconds(first_word_start: float, title_seconds: float,
                    read_buffer: float) -> float:
    """Seconds to delay the song so singing starts no sooner than the title card
    plus a read buffer. Zero when the first word already starts late enough."""
    return max(0.0, (title_seconds + read_buffer) - first_word_start)


def title_alpha(t: float, title_seconds: float, fade: float) -> float:
    """Title-card opacity (0..1): fade in over `fade`s, hold, fade out into the
    lyrics by `title_seconds`. Zero before the song and once the card is gone."""
    if title_seconds <= 0 or t <= 0 or t >= title_seconds:
        return 0.0
    if fade <= 0:
        return 1.0
    if t < fade:
        return t / fade
    if t > title_seconds - fade:
        return max(0.0, (title_seconds - t) / fade)
    return 1.0


def progress_fraction(t: float, lead_in: float, song_duration: float) -> float:
    """Progress-bar fill (0..1): empty through the lead-in, then linear across the
    actual track, clamped to 1 at the end."""
    if song_duration <= 0:
        return 0.0
    return max(0.0, min(1.0, (t - lead_in) / song_duration))


def count_in_fraction(timing: Timing, i: int, t: float, window: float,
                      threshold: float):
    """Count-in dots fill (0..1) for line `i`, or None when it doesn't apply.

    A line qualifies if it's the first line or the gap before it is at least
    `threshold` (a wait-bar gap). The dots fill over the final `window` seconds
    before the line starts and stay full (1.0) once it begins (persisting while
    it's the active line). Returns None when the line doesn't qualify or `t` is
    before the window."""
    lines = timing.lines
    if i > 0 and (lines[i].start - lines[i - 1].end) < threshold:
        return None
    start = lines[i].start
    prev_end = lines[i - 1].end if i > 0 else 0.0
    window_start = max(0.0, prev_end, start - window)
    if t < window_start:
        return None
    if t >= start:
        return 1.0
    span = start - window_start
    return (t - window_start) / span if span > 0 else 1.0


def shift_all(timing: Timing, delta: float) -> Timing:
    """Shift every word's start/end later by `delta`, preserving line structure.
    `delta == 0` returns an equivalent timing (used as the no-lead-in path).
    Uses Word.retimed so `bg` (and any future field) rides along — dropping `bg`
    here made backing-vocal words count toward line start/end in every render,
    shrinking lead gaps and killing wait bars / count-ins that depend on the
    non-bg gap."""
    return Timing(lines=[
        Line(words=[w.retimed(w.start + delta, w.end + delta) for w in ln.words],
             wrap=ln.wrap)
        for ln in timing.lines])


@dataclass
class WordState:
    text: str
    fill: float


@dataclass
class LineState:
    index: int
    role: str
    words: List[WordState]
    wrap: bool = False


@dataclass
class FrameState:
    t: float
    lines: List[LineState]
    wait: float | None = None   # 0..1 progress-bar fill during a long instrumental gap
    wait_outro: bool = False    # the gap is the end-of-song outro (warmer bar colour)
    title: float = 0.0          # title-card opacity 0..1 (0 once the card is gone)
    progress: float | None = None   # song progress-bar fill 0..1 (None = no bar)
    countin: float | None = None   # count-in dots fill 0..1 for the active line (None = none)

    def to_dict(self) -> dict:
        return {
            "t": self.t,
            "wait": self.wait,
            "wait_outro": self.wait_outro,
            "title": self.title,
            "progress": self.progress,
            "countin": self.countin,
            "lines": [
                {"index": ln.index, "role": ln.role, "wrap": ln.wrap,
                 "words": [{"text": w.text, "fill": w.fill} for w in ln.words]}
                for ln in self.lines
            ],
        }


def active_index(timing: Timing, t: float) -> int:
    """Index of the line to highlight at time t.

    A line becomes active for read-ahead as soon as the *previous* line finishes
    (not when this line starts singing), so it lights up during the instrumental
    gap before it. Concretely: the first line that hasn't ended yet; the last
    line once everything has ended.
    """
    for i, line in enumerate(timing.lines):
        if line.end > t:
            return i
    return len(timing.lines) - 1


def page_top(active: int, lines_per_page: int) -> int:
    """Index of the top line of the page containing the active line.

    The page stays fixed while the active line fills down it. When the active
    line reaches the second-to-last line of the page, the page turns and that
    line becomes the new top — so pages advance by (lines_per_page - 2) lines,
    overlapping by two for continuity.
    """
    step = max(1, lines_per_page - 2)
    return (active // step) * step


def current_gap(timing: Timing, t: float, duration: float):
    """The silent gap (no line being sung) containing t, as (start, end, is_outro),
    or None when a line is currently being sung. Covers the intro before the first
    line, gaps between lines, and the outro after the last line."""
    lines = timing.lines
    if t < lines[0].start:
        return (0.0, lines[0].start, False)
    for i in range(len(lines) - 1):
        if lines[i].end <= t < lines[i + 1].start:
            return (lines[i].end, lines[i + 1].start, False)
    if t >= lines[-1].end:
        return (lines[-1].end, duration, True)
    return None


def wait_fraction(gap, t: float, threshold: float, bar_end: float):
    """Progress-bar fill (0..1) for a qualifying long gap, or None.

    The bar only appears for gaps longer than ``threshold``. For intro/mid gaps it
    fills to full ``bar_end`` seconds before the next line (then disappears); for
    the outro it fills across the whole tail.
    """
    start, end, is_outro = gap
    if end - start <= threshold:
        return None
    fill_end = end if is_outro else end - bar_end
    if t >= fill_end:
        return None
    span = fill_end - start
    return max(0.0, min(1.0, (t - start) / span)) if span > 0 else None


def frame_state(timing: Timing, t: float, lines_per_page: int = 6, *,
                duration: float | None = None, wait_threshold: float = 12.0,
                wait_bar_end: float = 1.0, wait_highlight: float = 3.0,
                lead_in: float = 0.0, song_duration: float | None = None,
                title_seconds: float = 0.0, title_fade: float = 0.5,
                count_in: bool = True, count_in_threshold: float = 5.0) -> FrameState:
    if not timing.lines:
        raise ValueError("Timing has no lines")
    ai = active_index(timing, t)
    top = page_top(ai, lines_per_page)
    hi = min(len(timing.lines), top + lines_per_page)
    lines: List[LineState] = []
    for i in range(top, hi):
        line = timing.lines[i]
        role = "active" if i == ai else ("past" if i < ai else "upcoming")
        words = [WordState(w.text, word_fill_fraction(w, t)) for w in line.words]
        lines.append(LineState(index=i, role=role, words=words, wrap=line.wrap))

    wait = None
    wait_outro = False
    if duration is not None:
        gap = current_gap(timing, t, duration)
        if gap is not None and gap[1] - gap[0] > wait_threshold:
            start, end, is_outro = gap
            wait_outro = is_outro
            wait = wait_fraction(gap, t, wait_threshold, wait_bar_end)
            # The bar fills longer than the highlight waits: keep the next line
            # dimmed until wait_highlight seconds before it starts (no next line
            # to highlight in the outro, so the sung lines just dim).
            if is_outro or t < end - wait_highlight:
                demoted = "past" if is_outro else "upcoming"
                for ls in lines:
                    if ls.role == "active":
                        ls.role = demoted

    title = title_alpha(t, title_seconds, title_fade) if title_seconds > 0 else 0.0
    progress = (progress_fraction(t, lead_in, song_duration)
                if song_duration is not None else None)
    countin = (count_in_fraction(timing, ai, t, wait_highlight, count_in_threshold)
               if count_in else None)
    return FrameState(t=t, lines=lines, wait=wait, wait_outro=wait_outro,
                      title=title, progress=progress, countin=countin)
