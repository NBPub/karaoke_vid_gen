from __future__ import annotations
from dataclasses import dataclass, field
import json
import re

ERROR = "error"
WARNING = "warning"


@dataclass
class Finding:
    severity: str
    code: str
    message: str
    line: int | None = None
    end_line: int | None = None
    context: list[str] = field(default_factory=list)
    # A WARNING that should interactively gate the render (prompt to continue /
    # take an action) rather than just inform. Acted on only by the interactive
    # `render` command; inert elsewhere. See cli._maybe_reseparate_for_no_extract.
    prompt: bool = False


def has_errors(findings: list[Finding]) -> bool:
    return any(f.severity == ERROR for f in findings)


def attach_context(findings: list[Finding], text: str, radius: int = 2) -> None:
    """Fill each finding's `context` with surrounding source lines (1-indexed),
    marking the offending line with '>'."""
    lines = text.splitlines()
    for f in findings:
        if f.line is None or not lines:
            continue
        lo = max(1, f.line - radius)
        hi = min(len(lines), f.line + radius)
        out = []
        for n in range(lo, hi + 1):
            mark = ">" if n == f.line else " "
            out.append(f"{mark} {n:>2}: {lines[n - 1]}")
        f.context = out


def format_report(findings: list[Finding]) -> str:
    if not findings:
        return "OK - no problems found."
    errs = [f for f in findings if f.severity == ERROR]
    warns = [f for f in findings if f.severity == WARNING]
    out = [f"{len(errs)} error(s), {len(warns)} warning(s)"]
    for label, group in (("ERROR", errs), ("WARN", warns)):
        for f in group:
            loc = f"line {f.line}" if f.line else "-"
            out.append(f"[{label}] {f.code} ({loc}): {f.message}")
            out.extend(f"    {c}" for c in f.context)
    return "\n".join(out)


_VALUE = re.compile(r'"[^"]+"\s*:\s*(?:-?\d+(?:\.\d+)?|"[^"]*"|true|false|null)$')
_EMPTY = re.compile(r'"\w+"\s*:\s*,?\s*$')


def scan_syntax(text: str) -> list[Finding]:
    """Heuristic, all-at-once syntax scan over the raw text (works on JSON that
    won't parse). Detects missing commas, empty values, trailing commas, and
    unbalanced braces/brackets. Every finding is an error with an exact line."""
    findings: list[Finding] = []
    lines = text.splitlines()

    def next_nonempty(i: int) -> str:
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        return lines[j].strip() if j < len(lines) else ""

    for i, raw in enumerate(lines):
        cur = raw.rstrip()
        stripped = cur.strip()
        nxt = next_nonempty(i)

        if _EMPTY.search(cur):
            findings.append(Finding(ERROR, "empty_value",
                "field has no value after the colon", line=i + 1))
            continue

        opens_field = nxt.startswith('"') or nxt.startswith("{")
        if _VALUE.search(cur) and opens_field:
            findings.append(Finding(ERROR, "missing_comma",
                "value is not followed by a comma before the next field", line=i + 1))
        elif stripped in ("}", "]") and (nxt.startswith("{") or nxt.startswith('"')):
            findings.append(Finding(ERROR, "missing_comma",
                "closing brace/bracket is not followed by a comma before the next item",
                line=i + 1))

        if cur.endswith(",") and (nxt.startswith("}") or nxt.startswith("]")):
            findings.append(Finding(ERROR, "trailing_comma",
                "comma immediately before a closing brace/bracket", line=i + 1))

    if text.count("{") != text.count("}") or text.count("[") != text.count("]"):
        findings.append(Finding(ERROR, "unbalanced_braces",
            f"unbalanced braces/brackets "
            f"(curly {text.count('{')}/{text.count('}')}, "
            f"square {text.count('[')}/{text.count(']')})", line=len(lines)))

    return findings


_TEXT_TOKEN = re.compile(r'"text"\s*:')


def word_lines(text: str) -> list[int]:
    """1-indexed source line of each word's `"text":` token, in document order.
    Assumes the canonical one-`"text":`-per-word layout that Timing.to_json emits."""
    return [i + 1 for i, l in enumerate(text.splitlines()) if _TEXT_TOKEN.search(l)]


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def check_shape(data) -> list[Finding]:
    """Structure & types. Errors only. Run before any dict-based check."""
    if not isinstance(data, dict) or not isinstance(data.get("lines"), list):
        return [Finding(ERROR, "bad_shape",
                        "top-level JSON must be an object with a 'lines' array")]
    findings: list[Finding] = []
    for li, ln in enumerate(data["lines"]):
        if not isinstance(ln, dict) or not isinstance(ln.get("words"), list):
            findings.append(Finding(ERROR, "bad_shape",
                f"line {li} must be an object with a 'words' array"))
            continue
        if not ln["words"]:
            findings.append(Finding(ERROR, "bad_shape",
                f"line {li} has an empty 'words' list"))
            continue
        for wi, w in enumerate(ln["words"]):
            if not isinstance(w, dict):
                findings.append(Finding(ERROR, "bad_shape",
                    f"line {li} word {wi} must be an object"))
                continue
            if not isinstance(w.get("text"), str):
                findings.append(Finding(ERROR, "missing_key",
                    f"line {li} word {wi}: missing or non-string 'text'"))
            for key in ("start", "end"):
                if key not in w:
                    findings.append(Finding(ERROR, "missing_key",
                        f"line {li} word {wi}: missing '{key}'"))
                elif not _is_number(w[key]):
                    findings.append(Finding(ERROR, "bad_type",
                        f"line {li} word {wi}: '{key}' must be a number"))
    return findings


def _ltext(words) -> str:
    return " ".join(w["text"] for w in words)[:40]


def _nonbg_span(words) -> tuple[float, float]:
    """(start, end) of a line's LEAD (non-bg) words — the dict-based twin of
    Timing.Line.start/end. bg words are excluded from line-transition timing;
    falls back to the first/last word when the line is all-bg."""
    nb = [w for w in words if not w.get("bg")]
    start = min((w["start"] for w in nb), default=words[0]["start"])
    end = max((w["end"] for w in nb), default=words[-1]["end"])
    return start, end


def _src(wl, g) -> int | None:
    return wl[g] if 0 <= g < len(wl) else None


def check_timing_semantics(data, wl) -> list[Finding]:
    findings: list[Finding] = []
    g = 0
    prev_end = -1.0
    for li, ln in enumerate(data["lines"]):
        words = ln["words"]
        if not words:
            continue
        first_g = g
        for w in words:
            if w["end"] > 0 and w["end"] < w["start"]:
                findings.append(Finding(ERROR, "end_before_start",
                    f"line {li} word '{w['text']}': end {w['end']} before start {w['start']}",
                    line=_src(wl, g)))
            g += 1
        first, last = words[0], words[-1]
        marked = first["end"] <= 0
        bgonly = all(w.get("bg") for w in words)
        # Line start/end for ordering come from the LEAD (non-bg) words: bg words
        # may overlap the lead and are excluded from line-transition timing.
        lstart, lend = _nonbg_span(words)
        fline = _src(wl, first_g)
        if not marked and lend <= lstart:
            findings.append(Finding(ERROR, "zero_width_line",
                f"line {li} ('{_ltext(words)}'): ends {lend} at/before its start {lstart}",
                line=fline))
        if not marked and not bgonly:
            if lstart < prev_end - 0.001:
                findings.append(Finding(ERROR, "out_of_order",
                    f"line {li} ('{_ltext(words)}'): starts {lstart} before the previous "
                    f"line ends {prev_end}", line=fline))
            prev_end = max(prev_end, lend)
        if marked and first["start"] <= 0:
            findings.append(Finding(ERROR, "mark_no_anchor",
                f"line {li} is marked for nudge but its first word has no start time",
                line=fline))
        if marked and bgonly:
            findings.append(Finding(WARNING, "bg_only_marked",
                f"line {li} is background-only and marked for nudge - the nudge will skip "
                f"it; hand-time it instead", line=fline))
    return findings


def check_markers(data, wl, context: str) -> list[Finding]:
    """`unprocessed_marker` warning — a line still marked for nudge. Suppressed
    for context == 'nudge' (markers are the expected input there). bg-only marked
    lines are covered by `bg_only_marked`, so skip them here."""
    if context == "nudge":
        return []
    findings: list[Finding] = []
    g = 0
    for li, ln in enumerate(data["lines"]):
        words = ln["words"]
        if not words:
            continue
        marked = words[0]["end"] <= 0
        bgonly = all(w.get("bg") for w in words)
        if marked and not bgonly:
            findings.append(Finding(WARNING, "unprocessed_marker",
                f"line {li} ('{_ltext(words)}') is still marked for nudge - run nudge, "
                f"or it renders with no fill on the first word", line=_src(wl, g)))
        g += len(words)
    return findings


def _norm(s: str) -> str:
    s = s.lower().replace("-", " ")
    s = re.sub(r"[^a-z0-9 ]", "", s)
    return " ".join(s.split())


def _collapse_wrap(tlines):
    """Group display lines into logical lines: a line plus following wrap rows.
    Returns a list of word-lists (each logical line's words concatenated)."""
    groups: list[list] = []
    for ln in tlines:
        if ln.get("wrap") and groups:
            groups[-1].extend(ln["words"])
        else:
            groups.append(list(ln["words"]))
    return groups


def check_lyrics_consistency(data, lyrics_lines, wl) -> list[Finding]:
    """Warnings: timing/lyrics line-count and per-line text divergence
    (hyphen-insensitive). Wrap-groups collapse to one logical line first, so an
    auto-split line still matches its single lyrics.txt line."""
    findings: list[Finding] = []
    groups = _collapse_wrap(data["lines"])
    if len(groups) != len(lyrics_lines):
        findings.append(Finding(WARNING, "lyrics_count_mismatch",
            f"timing has {len(groups)} lines but lyrics.txt has {len(lyrics_lines)}"))
    g = 0
    for li, words in enumerate(groups):
        first_g = g
        g += len(words)
        if li >= len(lyrics_lines):
            continue
        t, ly = _norm(" ".join(w["text"] for w in words)), _norm(lyrics_lines[li])
        if t != ly:
            findings.append(Finding(WARNING, "lyrics_text_mismatch",
                f"line {li}: timing text != lyrics.txt (timing={t!r} lyrics={ly!r})",
                line=_src(wl, first_g)))
    return findings


_SHORTCUT_PATTERNS = [
    (re.compile(r"\((?:\s*x?\s*\d+\s*x?\s*|[^)]*\b(?:repeat|chorus|verse|times|x\d+)\b[^)]*)\)", re.I),
     "repeat shortcut / count"),
    (re.compile(r"\[[^\]]+\]"), "section header / bracket"),
    (re.compile(r"\bx\s?\d+\b|\b\d+\s?x\b", re.I), "multiplier (xN / Nx)"),
]
_FOOTER_MARKER = re.compile(r"you might also like", re.I)


def check_lyrics_artifacts(lyrics_text: str) -> list[Finding]:
    """Warnings for non-sung text in lyrics that corrupts alignment: repeat
    shortcuts / section headers, and a Genius 'You might also like' footer plus
    its trailing junk. Line numbers refer to NON-EMPTY lyrics lines (reported in
    the message, since they index lyrics.txt, not timing.json)."""
    ne = [l.strip() for l in lyrics_text.splitlines() if l.strip()]
    pairs: list[tuple[int, Finding]] = []
    footer_at: int | None = None
    flagged: set[int] = set()

    def add(idx: int, reason: str, line_text: str):
        flagged.add(idx)
        pairs.append((idx, Finding(WARNING, "lyric_artifact",
            f"lyrics.txt line {idx}: {reason}: {line_text[:60]!r}")))

    for idx, line in enumerate(ne):
        if _FOOTER_MARKER.search(line):
            footer_at = idx if footer_at is None else footer_at
            add(idx, 'scrape footer ("You might also like")', line)
            continue
        for pat, desc in _SHORTCUT_PATTERNS:
            if pat.search(line):
                add(idx, desc, line)
                break
    if footer_at is not None:
        for idx in range(footer_at + 1, len(ne)):
            if idx not in flagged:
                add(idx, "after-footer (likely junk)", ne[idx])
    return [f for _, f in sorted(pairs, key=lambda p: p[0])]


def audio_duration(path) -> float | None:
    """Song length in seconds via soundfile, or None if unreadable/missing.
    Thin seam so tests pass durations directly instead of needing audio."""
    try:
        import soundfile as sf
        return float(sf.info(str(path)).duration)
    except Exception:
        return None


def check_song_bounds(data, duration: float, wl) -> list[Finding]:
    """One warning if any word ends past the song length (reports the first)."""
    g = 0
    for li, ln in enumerate(data["lines"]):
        for w in ln["words"]:
            if w["end"] > duration + 0.001:
                return [Finding(WARNING, "past_song_end",
                    f"line {li} word '{w['text']}' ends {w['end']:.1f}s, past the song "
                    f"length {duration:.1f}s (and possibly later words)", line=_src(wl, g))]
            g += 1
    return []


def check_line_widths(data, usable_width: float, measure,
                      severity: str = ERROR) -> list[Finding]:
    """Flag rendered lyric lines wider than ``usable_width`` pixels.
    ``measure(text) -> width_px`` must match the renderer's font and size. The
    fix is to hand-split the line in timing.json (each word keeps its time — no
    re-align), so all offenders are gathered into one finding listing each
    (1-indexed) line number and its full text. ``severity`` is ERROR for the
    render/standalone gate (block shipping cut-off lyrics) and WARNING for nudge
    (a display concern must not block timing work). Empty when nothing
    overflows."""
    over: list[tuple[int, str]] = []
    for li, ln in enumerate(data["lines"]):
        words = ln["words"]
        if not words:
            continue
        rendered = "".join(w["text"] + " " for w in words)   # renderer's tokens
        if measure(rendered) > usable_width:
            over.append((li + 1, " ".join(w["text"] for w in words)))
    if not over:
        return []
    return [Finding(severity, "line_too_wide",
        "Line(s) detected that will extend past the video window, break up to "
        "ensure all lyrics visible",
        context=[f"line {n}: {text}" for n, text in over])]


def _line_measurer(cfg):
    """A ``text -> pixel width`` function using the configured render font and
    size, so the width check measures exactly what the Pillow renderer draws."""
    from karaoke.render.draw import load_font
    font = load_font(cfg)
    return lambda text: font.getlength(text)


_COUNT_IN_DENSITY_RATIO = 0.30
# Below this many lines the ratio is dominated by the always-present first-line
# count-in (a 1-line song is trivially 100%), so the check would false-positive
# on short songs. Skip until there are enough lines for the ratio to mean something.
_COUNT_IN_DENSITY_MIN_LINES = 8


def check_count_in_density(data, threshold: float,
                           ratio: float = _COUNT_IN_DENSITY_RATIO) -> list[Finding]:
    """Warn when count-in dots would appear on more than ``ratio`` of lines — the
    first line plus any line whose gap to the previous line is >= ``threshold``
    seconds (mirroring fill.count_in_fraction). The '●  ●  ●' prefix persists
    while its line is sung, so too many is on-screen clutter; the fix is to raise
    render.count_in_min_gap_seconds. Warning only, every context. Line start/end
    use non-bg lead words, matching Timing.Line. Empty when under the ratio or
    when the song has too few lines for the ratio to be meaningful."""
    lines = data["lines"]
    n = len(lines)
    if n < _COUNT_IN_DENSITY_MIN_LINES:
        return []

    spans = [_nonbg_span(ln["words"]) for ln in lines]
    count = 1  # the first line always gets a count-in
    for i in range(1, n):
        if spans[i][0] - spans[i - 1][1] >= threshold:   # non-bg gap
            count += 1
    if count > ratio * n:
        return [Finding(WARNING, "count_in_density",
            f"{count} of {n} lines ({count / n:.0%}) get a count-in "
            f"(gap >= {threshold:g}s, or the first line) — over {ratio:.0%}; raise "
            f"render.count_in_min_gap_seconds to reduce on-screen '●  ●  ●' clutter")]
    return []


def check_staleness(timing_mtime: float, mp4_mtime: float) -> list[Finding]:
    if timing_mtime > mp4_mtime + 1.0:
        return [Finding(WARNING, "stale_render",
            "timing.json was modified after the rendered video - re-render (with "
            "--force) to avoid shipping a stale video")]
    return []


def check_no_extract_staleness(no_extract_mtime: float,
                               instrumental_mtime: float) -> list[Finding]:
    """Warn (and prompt at render) when no_extract.txt was edited after the
    instrumental was separated: the no-extract spans aren't applied until
    `separate` is re-run. Assumes AI separation (a supplied instrumental ignores
    no_extract)."""
    if no_extract_mtime > instrumental_mtime + 1.0:
        return [Finding(WARNING, "stale_no_extract",
            "no_extract.txt was modified after the instrumental was separated - "
            "run `separate --force` to apply the no-extract spans (ignore if you "
            "used a supplied instrumental)", prompt=True)]
    return []


def run_preflight(sp, cfg, *, context: str) -> list[Finding]:
    """Collect all findings for a song's timing.json in the given context
    ('nudge' | 'render' | 'standalone'). Errors halt callers; warnings inform.
    ``cfg`` supplies render settings for config-aware checks (line width); pass
    None to skip those."""
    if not sp.timing_json.exists():
        return [Finding(ERROR, "missing_timing", f"no timing.json at {sp.timing_json}")]
    text = sp.timing_json.read_text(encoding="utf-8")

    syntax = scan_syntax(text)
    if syntax:
        attach_context(syntax, text)
        return syntax
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        f = Finding(ERROR, "json_parse", e.msg, line=e.lineno)
        attach_context([f], text)
        return [f]

    shape = check_shape(data)
    if has_errors(shape):
        attach_context(shape, text)
        return shape

    wl = word_lines(text)
    findings: list[Finding] = []
    findings += check_timing_semantics(data, wl)
    findings += check_markers(data, wl, context)

    if sp.lyrics_txt.exists():
        raw = sp.lyrics_txt.read_text(encoding="utf-8")
        lyric_lines = [l.strip() for l in raw.splitlines() if l.strip()]
        findings += check_lyrics_consistency(data, lyric_lines, wl)
        findings += check_lyrics_artifacts(raw)

    dur = audio_duration(sp.song) if sp.song.exists() else None
    if dur is not None:
        findings += check_song_bounds(data, dur, wl)
    # Compare against the newest rendered output that exists. The default mode
    # is review-only (just karaoke.review.mp4), so checking karaoke.mp4 alone
    # would never fire for the common iterate-on-timing workflow.
    rendered = [p for p in (sp.output_mp4, sp.review_mp4) if p.exists()]
    if rendered:
        newest = max(p.stat().st_mtime for p in rendered)
        findings += check_staleness(sp.timing_json.stat().st_mtime, newest)
    if sp.no_extract.exists() and sp.instrumental.exists():
        findings += check_no_extract_staleness(
            sp.no_extract.stat().st_mtime, sp.instrumental.stat().st_mtime)

    if cfg is not None:
        # An over-wide line is a blocking error when about to render/ship, but
        # only a warning during nudge — width is a display concern, not a timing
        # one, and must not gate timing correction.
        width_severity = WARNING if context == "nudge" else ERROR
        findings += check_line_widths(
            data, cfg.render.width * cfg.render.usable_width_frac,
            _line_measurer(cfg), severity=width_severity)
        if cfg.render.count_in:
            findings += check_count_in_density(
                data, cfg.render.count_in_min_gap_seconds)

    attach_context(findings, text)
    return findings
