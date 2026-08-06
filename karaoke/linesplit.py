"""Pure line-splitting helpers: match/regroup a timing's words against a
hand-split lyrics.txt, and balance a too-wide line into the minimum rows that
fit. No I/O, no fonts — the width `measure` is injected."""
from __future__ import annotations
from typing import Callable, List
from karaoke.timing import Timing, Line, Word

Measure = Callable[[str], float]


def _flat(timing: Timing) -> List[Word]:
    return [w for ln in timing.lines for w in ln.words]


def words_match(timing: Timing, lyrics_lines: List[str]) -> bool:
    """True when the timing's word sequence exactly equals lyrics.txt's (same
    tokens, same order). A split only *moves line boundaries*, so the flat words
    are unchanged — this is the precondition for a lossless re-segment."""
    tw = [w.text for w in _flat(timing)]
    lw = [w for line in lyrics_lines for w in line.split()]
    return tw == lw


def resegment(timing: Timing, words_per_line: List[int]) -> Timing:
    """Regroup the timing's flat words into the given per-line counts (the
    lyrics.txt structure). Times + bg preserved; wrap dropped (plain lines)."""
    flat = _flat(timing)
    if sum(words_per_line) != len(flat):
        raise ValueError(
            f"word count mismatch: lyrics {sum(words_per_line)} vs timing {len(flat)}")
    lines, i = [], 0
    for c in words_per_line:
        lines.append(Line(words=flat[i:i + c]))
        i += c
    return Timing(lines=lines)


def _row_text(words: List[Word]) -> str:
    # Appends a trailing space to every word (including the last). The injected
    # `measure` must accept this; it matches how preflight.check_line_widths builds
    # its measurement string, so split and preflight agree on widths.
    return "".join(w.text + " " for w in words)


def _greedy_rows(words: List[Word], measure: Measure, usable: float) -> List[List[Word]]:
    """Pack words into rows, breaking before a word that would exceed usable."""
    rows: List[List[Word]] = []
    cur: List[Word] = []
    for w in words:
        trial = cur + [w]
        if cur and measure(_row_text(trial)) > usable:
            rows.append(cur)
            cur = [w]
        else:
            cur = trial
    if cur:
        rows.append(cur)
    return rows


def balanced_wrap(words: List[Word], measure: Measure, usable: float) -> List[List[Word]]:
    """Split `words` into the minimum number of rows that each fit `usable`,
    balanced so the widest row is as narrow as possible (min-max contiguous
    partition). A single word wider than usable yields a lone over-wide row."""
    words = list(words)
    if len(words) <= 1:
        return [words]
    n = max(1, len(_greedy_rows(words, measure, usable)))
    if n == 1:
        return [words]
    m = len(words)

    def W(i: int, j: int) -> float:
        return measure(_row_text(words[i:j]))

    INF = float("inf")
    # dp[k][i] = min achievable widest-row splitting words[i:] into k rows.
    dp = [[INF] * (m + 1) for _ in range(n + 1)]
    nxt = [[m] * (m + 1) for _ in range(n + 1)]
    for i in range(m + 1):
        dp[1][i] = W(i, m)
    for k in range(2, n + 1):
        for i in range(0, m - k + 1):            # need >= k words in words[i:]
            best, bj = INF, i + 1
            for j in range(i + 1, m - (k - 1) + 1):  # leave >= k-1 words after
                val = max(W(i, j), dp[k - 1][j])
                if val < best:
                    best, bj = val, j
            dp[k][i], nxt[k][i] = best, bj
    rows, i = [], 0
    for k in range(n, 0, -1):
        j = nxt[k][i] if k > 1 else m
        rows.append(words[i:j])
        i = j
    return rows
