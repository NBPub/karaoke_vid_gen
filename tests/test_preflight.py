# tests/test_preflight.py
from karaoke.preflight import (
    Finding, ERROR, WARNING, has_errors, format_report, attach_context,
)


def test_has_errors_true_only_with_error():
    assert has_errors([Finding(WARNING, "w", "warn")]) is False
    assert has_errors([Finding(WARNING, "w", "warn"), Finding(ERROR, "e", "err")]) is True
    assert has_errors([]) is False


def test_format_report_groups_and_labels():
    findings = [
        Finding(WARNING, "stale_render", "stale"),
        Finding(ERROR, "missing_comma", "needs a comma", line=4),
    ]
    out = format_report(findings)
    assert "1 error(s), 1 warning(s)" in out
    # errors come before warnings
    assert out.index("[ERROR]") < out.index("[WARN]")
    assert "missing_comma (line 4): needs a comma" in out
    assert "stale_render" in out


def test_format_report_clean():
    assert "no problems" in format_report([]).lower()


def test_attach_context_marks_offending_line():
    text = "a\nb\nc\nd\ne"
    f = Finding(ERROR, "x", "boom", line=3)
    attach_context([f], text, radius=1)
    assert f.context == ["   2: b", ">  3: c", "   4: d"]


# Task 2: scan_syntax tests
from karaoke.preflight import scan_syntax


def _codes(findings):
    return sorted(f.code for f in findings)


def test_scan_syntax_clean_file_has_no_findings():
    text = '{\n  "lines": [\n    { "words": [\n      {"text": "a", "start": 1.0, "end": 2.0}\n    ] }\n  ]\n}\n'
    assert scan_syntax(text) == []


def test_scan_syntax_missing_comma_between_fields():
    text = '{\n  "text": "know",\n  "start": 0\n  "end": 210\n}\n'
    fs = scan_syntax(text)
    assert "missing_comma" in _codes(fs)
    assert any(f.line == 3 for f in fs)  # the "start": 0 line lacks the comma


def test_scan_syntax_empty_value():
    text = '{\n  "start": ,\n  "end": 5\n}\n'
    fs = scan_syntax(text)
    assert "empty_value" in _codes(fs)
    assert any(f.line == 2 for f in fs)


def test_scan_syntax_trailing_comma():
    text = '{\n  "words": [\n    {"text": "a", "start": 1, "end": 2},\n  ]\n}\n'
    assert "trailing_comma" in _codes(scan_syntax(text))


def test_scan_syntax_unbalanced_braces():
    text = '{\n  "lines": [\n    {"words": []}\n  ]\n'  # missing final }
    assert "unbalanced_braces" in _codes(scan_syntax(text))


# Task 3: word_lines + check_shape tests
from karaoke.preflight import word_lines, check_shape


def test_word_lines_maps_text_tokens_to_source_lines():
    text = (
        '{\n'              # 1
        '  "lines": [\n'   # 2
        '    {"words": [\n'  # 3
        '      {"text": "a",\n'   # 4  <- word 0
        '       "start": 1, "end": 2},\n'  # 5
        '      {"text": "b",\n'   # 6  <- word 1
        '       "start": 2, "end": 3}\n'   # 7
        '    ]}\n'
        '  ]\n}\n'
    )
    assert word_lines(text) == [4, 6]


def test_check_shape_flags_bad_top_level():
    assert any(f.code == "bad_shape" for f in check_shape({"nope": 1}))


def test_check_shape_flags_missing_and_bad_word_fields():
    data = {"lines": [{"words": [{"text": "a", "start": "x"}]}]}
    codes = sorted(f.code for f in check_shape(data))
    assert "bad_type" in codes      # start is a string
    assert "missing_key" in codes   # end is absent (treated as bad/missing)


def test_check_shape_clean():
    data = {"lines": [{"words": [{"text": "a", "start": 1.0, "end": 2.0}]}]}
    assert check_shape(data) == []


# Task 4: check_timing_semantics tests
from karaoke.preflight import check_timing_semantics


def _line(words):  # words: list of (text, start, end[, bg])
    return {"words": [
        {"text": t, "start": s, "end": e, **({"bg": True} if len(rest) and rest[0] else {})}
        for (t, s, e, *rest) in words]}


def _codes2(data, wl=None):
    return sorted(f.code for f in check_timing_semantics(data, wl or []))


def test_semantics_clean_passes():
    data = {"lines": [_line([("a", 1.0, 2.0)]), _line([("b", 2.0, 3.0)])]}
    assert check_timing_semantics(data, [1, 2]) == []


def test_semantics_end_before_start():
    data = {"lines": [_line([("a", 5.0, 3.0)])]}
    assert "end_before_start" in _codes2(data)


def test_semantics_marker_is_not_end_before_start():
    # first word end=0 is the nudge marker convention, not a typo
    data = {"lines": [_line([("a", 5.0, 0.0), ("b", 6.0, 7.0)])]}
    assert "end_before_start" not in _codes2(data)


def test_semantics_out_of_order_line():
    data = {"lines": [_line([("a", 5.0, 6.0)]), _line([("b", 2.0, 3.0)])]}
    assert "out_of_order" in _codes2(data)


def test_semantics_zero_width_line():
    data = {"lines": [_line([("a", 4.0, 4.0)])]}
    assert "zero_width_line" in _codes2(data)


def test_semantics_mark_no_anchor():
    data = {"lines": [_line([("a", 0.0, 0.0)])]}  # marked but start<=0
    assert "mark_no_anchor" in _codes2(data)


def test_semantics_bg_only_marked_is_warning():
    data = {"lines": [_line([("ah", 5.0, 0.0, True), ("ah", 5.2, 6.0, True)])]}
    fs = check_timing_semantics(data, [1, 2])
    bg = [f for f in fs if f.code == "bg_only_marked"]
    assert bg and bg[0].severity == "warning"


def test_semantics_trailing_bg_excluded_from_out_of_order():
    # line 0 lead ends 49.5; its bg tail runs to 50.72 (overlaps line 1) — but bg
    # is excluded from line-transition timing, so no out_of_order (lead 49.5 < 50.18).
    data = {"lines": [
        _line([("Well", 49.0, 49.3), ("gone", 49.3, 49.5), ("(then)", 50.28, 50.72, True)]),
        _line([("Can", 50.18, 50.5)]),
    ]}
    assert "out_of_order" not in _codes2(data, [1, 2, 3, 4])


def test_semantics_trailing_nonbg_still_trips_out_of_order():
    # same shape but the overlapping tail is NOT bg -> genuine overlap, still flagged.
    data = {"lines": [
        _line([("Well", 49.0, 49.3), ("gone", 50.28, 50.72)]),
        _line([("Can", 50.18, 50.5)]),
    ]}
    assert "out_of_order" in _codes2(data, [1, 2, 3])


# Task 5: check_markers tests
from karaoke.preflight import check_markers


def test_unprocessed_marker_warns_for_render_and_standalone():
    data = {"lines": [_line([("a", 5.0, 0.0), ("b", 6.0, 7.0)])]}  # marked lead line
    for ctx in ("render", "standalone"):
        fs = check_markers(data, [1, 2], ctx)
        assert any(f.code == "unprocessed_marker" and f.severity == "warning" for f in fs)


def test_unprocessed_marker_suppressed_for_nudge():
    data = {"lines": [_line([("a", 5.0, 0.0), ("b", 6.0, 7.0)])]}
    assert check_markers(data, [1, 2], "nudge") == []


def test_unprocessed_marker_skips_bg_only_lines():
    # bg-only marked is handled by bg_only_marked, not here
    data = {"lines": [_line([("ah", 5.0, 0.0, True)])]}
    assert check_markers(data, [1], "render") == []


# Task 6: check_lyrics_consistency tests
from karaoke.preflight import check_lyrics_consistency


def test_lyrics_count_mismatch_warns():
    data = {"lines": [_line([("a", 1, 2)])]}
    fs = check_lyrics_consistency(data, ["a", "b"], [1])
    assert any(f.code == "lyrics_count_mismatch" for f in fs)


def test_lyrics_text_mismatch_warns():
    data = {"lines": [_line([("ship", 1, 2)])]}
    fs = check_lyrics_consistency(data, ["shit"], [1])
    assert any(f.code == "lyrics_text_mismatch" for f in fs)


def test_lyrics_syllable_split_does_not_warn():
    # timing splits the word; lyrics uses hyphen notation -> must MATCH
    data = {"lines": [_line([("strug", 1, 1.5), ("gles", 1.5, 2)])]}
    fs = check_lyrics_consistency(data, ["strug - gles"], [1, 1])
    assert [f for f in fs if f.code == "lyrics_text_mismatch"] == []


def test_consistency_collapses_wrap_group():
    # one logical line auto-split into two display rows (row2 wrap=True)
    data = {"lines": [
        {"words": [{"text": "hello", "start": 1, "end": 2}]},
        {"words": [{"text": "world", "start": 2, "end": 3}], "wrap": True},
    ]}
    fs = check_lyrics_consistency(data, ["hello world"], [1, 2])
    assert fs == []  # collapses -> matches, no warning


def test_wrap_group_mismatch_line_maps_to_head_row():
    # M5: when a wrap-group's collapsed text mismatches lyrics, the finding's
    # line= must be the HEAD row's source line (wl[first_g]), not a continuation row.
    # HEAD row's word "hello" is at wl index 0 -> source line 5.
    # continuation row's word "world" is at wl index 1 -> source line 9.
    data = {"lines": [
        {"words": [{"text": "hello", "start": 1, "end": 2}]},
        {"words": [{"text": "world", "start": 2, "end": 3}], "wrap": True},
    ]}
    wl = [5, 9]   # source line 5 for "hello" (head), 9 for "world" (continuation)
    fs = check_lyrics_consistency(data, ["goodbye world"], wl)
    mismatch = [f for f in fs if f.code == "lyrics_text_mismatch"]
    assert len(mismatch) == 1
    assert mismatch[0].line == 5   # HEAD row's source line, not continuation's 9


# Task 7: check_lyrics_artifacts tests
from karaoke.preflight import check_lyrics_artifacts


def test_artifacts_flag_repeat_shortcut():
    fs = check_lyrics_artifacts("line one\n(x4)\nline two\n")
    assert any(f.code == "lyric_artifact" for f in fs)


def test_artifacts_flag_genius_footer_and_after():
    text = "real line\nYou might also like\nNightshop\nFugazi\n"
    fs = check_lyrics_artifacts(text)
    assert sum(f.code == "lyric_artifact" for f in fs) >= 3  # footer + 2 trailing


def test_artifacts_clean():
    assert check_lyrics_artifacts("just\nclean\nlyrics\n") == []


# Task 8: Environment checks tests
from karaoke.preflight import check_song_bounds, check_staleness


def test_song_bounds_flags_word_past_end():
    data = {"lines": [_line([("a", 1, 2)]), _line([("b", 3, 99.0)])]}
    fs = check_song_bounds(data, duration=10.0, wl=[1, 2])
    assert len(fs) == 1 and fs[0].code == "past_song_end"


def test_song_bounds_clean_within_duration():
    data = {"lines": [_line([("a", 1, 2)])]}
    assert check_song_bounds(data, duration=10.0, wl=[1]) == []


def test_staleness_warns_when_timing_newer():
    assert any(f.code == "stale_render" for f in check_staleness(200.0, 100.0))


def test_staleness_clean_when_render_newer():
    assert check_staleness(100.0, 200.0) == []


from karaoke.preflight import check_no_extract_staleness


def test_no_extract_staleness_warns_and_prompts_when_newer():
    fs = check_no_extract_staleness(no_extract_mtime=200.0, instrumental_mtime=100.0)
    assert len(fs) == 1
    assert fs[0].code == "stale_no_extract"
    assert fs[0].severity == "warning"
    assert fs[0].prompt is True


def test_no_extract_staleness_clean_when_instrumental_newer():
    assert check_no_extract_staleness(no_extract_mtime=100.0,
                                      instrumental_mtime=200.0) == []


# Task 9: run_preflight orchestrator tests
import json
from karaoke.preflight import run_preflight, check_line_widths
from karaoke.paths import SongPaths
from karaoke.config import Config, RenderConfig


def _song(tmp_path, timing=None, lyrics=None):
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    if timing is not None:
        sp.timing_json.write_text(timing, encoding="utf-8")
    if lyrics is not None:
        sp.lyrics_txt.write_text(lyrics, encoding="utf-8")
    return sp


def _good_timing():
    return json.dumps({"lines": [
        {"words": [{"text": "hello", "start": 1.0, "end": 1.5},
                   {"text": "world", "start": 1.5, "end": 2.0}]},
    ]}, indent=2)


def test_run_preflight_missing_timing(tmp_path):
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    fs = run_preflight(sp, Config(), context="standalone")
    assert len(fs) == 1 and fs[0].code == "missing_timing"


def test_run_preflight_syntax_stops_before_semantics(tmp_path):
    sp = _song(tmp_path, timing='{\n  "start": 0\n  "end": 5\n}\n')
    fs = run_preflight(sp, Config(), context="render")
    assert any(f.code == "missing_comma" for f in fs)
    # context populated from the source text
    assert any(f.context for f in fs if f.line)


def test_run_preflight_clean_with_lyrics(tmp_path):
    sp = _song(tmp_path, timing=_good_timing(), lyrics="hello world\n")
    assert run_preflight(sp, Config(), context="render") == []


def test_run_preflight_text_mismatch_is_warning(tmp_path):
    sp = _song(tmp_path, timing=_good_timing(), lyrics="goodbye world\n")
    fs = run_preflight(sp, Config(), context="render")
    assert any(f.code == "lyrics_text_mismatch" and f.severity == "warning" for f in fs)
    assert not has_errors(fs)


# --- review fixes: empty 'words' list must be a reported error, never a crash ---

def test_check_shape_flags_empty_words_list():
    assert any(f.code == "bad_shape" for f in check_shape({"lines": [{"words": []}]}))


def test_semantics_and_markers_skip_empty_words():
    data = {"lines": [{"words": []}]}
    assert check_timing_semantics(data, []) == []      # no IndexError
    assert check_markers(data, [], "render") == []


def test_run_preflight_empty_words_reports_not_crashes(tmp_path):
    sp = _song(tmp_path, timing='{"lines": [{"words": []}]}')
    fs = run_preflight(sp, Config(), context="render")           # must not raise
    assert any(f.code == "bad_shape" for f in fs)


def test_run_preflight_stale_against_review_copy(tmp_path):
    """The default mode renders only karaoke.review.mp4; a timing edit newer
    than it must still warn (regression: previously only karaoke.mp4 was checked)."""
    import os
    sp = _song(tmp_path, timing=_good_timing(), lyrics="hello world\n")
    sp.review_mp4.write_bytes(b"x")
    os.utime(sp.review_mp4, (1000, 1000))
    os.utime(sp.timing_json, (2000, 2000))
    fs = run_preflight(sp, Config(), context="render")
    assert any(f.code == "stale_render" for f in fs)


def test_run_preflight_not_stale_when_review_newer(tmp_path):
    import os
    sp = _song(tmp_path, timing=_good_timing(), lyrics="hello world\n")
    sp.review_mp4.write_bytes(b"x")
    os.utime(sp.timing_json, (1000, 1000))
    os.utime(sp.review_mp4, (2000, 2000))
    assert not any(f.code == "stale_render" for f in run_preflight(sp, Config(), context="render"))


# --- line-width check (warn to break up lines that run past the window) ---

def test_check_line_widths_flags_only_overflowing_lines():
    data = {"lines": [
        _line([("short", 1.0, 2.0)]),
        _line([("very", 2.0, 3.0), ("long", 3.0, 4.0), ("line", 4.0, 5.0)]),
    ]}
    fs = check_line_widths(data, usable_width=1000, measure=lambda t: 100 * len(t))
    assert len(fs) == 1 and fs[0].code == "line_too_wide"
    assert fs[0].severity == ERROR                                    # default blocks
    assert "extend past the video window" in fs[0].message
    assert "karaoke split" in fs[0].message                            # suggests the fix
    assert any(c == "line 2: very long line" for c in fs[0].context)   # 1-indexed, full text
    assert all("line 1:" not in c for c in fs[0].context)              # short line not flagged


def test_check_line_widths_severity_override():
    data = {"lines": [_line([("very", 2.0, 3.0), ("long", 3.0, 4.0)])]}
    fs = check_line_widths(data, 100, lambda t: 100 * len(t), severity=WARNING)
    assert fs and fs[0].severity == WARNING


def test_check_line_widths_clean_when_all_fit():
    data = {"lines": [_line([("a", 1.0, 2.0)])]}
    assert check_line_widths(data, 1000, lambda t: 10 * len(t)) == []


def test_run_preflight_too_wide_line_is_error_when_rendering(tmp_path):
    """Wiring: a 10px-wide window makes any real text overflow under the actual
    render font. In render context it's a blocking error."""
    sp = _song(tmp_path, timing=_good_timing(), lyrics="hello world\n")
    cfg = Config(render=RenderConfig(width=10))
    fs = run_preflight(sp, cfg, context="render")
    assert any(f.code == "line_too_wide" for f in fs)
    assert has_errors(fs)


def test_run_preflight_too_wide_line_is_warning_in_nudge(tmp_path):
    """In nudge context the same over-wide line is only a warning — it must not
    block timing work."""
    sp = _song(tmp_path, timing=_good_timing(), lyrics="hello world\n")
    cfg = Config(render=RenderConfig(width=10))
    fs = run_preflight(sp, cfg, context="nudge")
    wide = [f for f in fs if f.code == "line_too_wide"]
    assert wide and wide[0].severity == WARNING
    assert not has_errors(fs)


def test_run_preflight_line_width_clean_at_full_width(tmp_path):
    sp = _song(tmp_path, timing=_good_timing(), lyrics="hello world\n")
    assert not any(f.code == "line_too_wide"
                   for f in run_preflight(sp, Config(), context="render"))


def test_run_preflight_flags_line_within_margin(tmp_path):
    # A line that fits the full frame but not 0.92 of it must now flag.
    import karaoke.preflight as pf
    sp = _song(tmp_path,
        timing=json.dumps({"lines": [{"words": [
            {"text": "x", "start": 1.0, "end": 2.0}]}]}),
        lyrics="x\n")
    # width 100, frac 0.92 -> usable 92; measure returns 95 for the line
    cfg = Config(render=RenderConfig(width=100, usable_width_frac=0.92))
    orig = pf._line_measurer
    pf._line_measurer = lambda c: (lambda t: 95.0)
    try:
        fs = run_preflight(sp, cfg, context="render")
    finally:
        pf._line_measurer = orig
    assert any(f.code == "line_too_wide" for f in fs)


def test_artifacts_sorted_by_line_order():
    fs = check_lyrics_artifacts("real\nYou might also like\nNightshop\nFugazi\n")
    idxs = [int(f.message.split("line ", 1)[1].split(":", 1)[0]) for f in fs]
    assert idxs == sorted(idxs)


from karaoke.preflight import check_count_in_density


def _lines_at(starts, dur=1.0):
    """One word per line; line i spans [start_i, start_i + dur]."""
    return {"lines": [_line([("w", s, s + dur)]) for s in starts]}


def test_count_in_density_clean_when_lines_close():
    # 10 back-to-back lines (~0.1s gaps): only the first line qualifies -> 10%.
    data = _lines_at([float(i) for i in range(10)], dur=0.9)
    assert check_count_in_density(data, threshold=5.0) == []


_BIG_GAPS = [7.0 * i for i in range(8)]   # 8 lines, all 6s gaps -> every line qualifies


def test_count_in_density_warns_when_many_gaps():
    # 8 lines 7s apart: first + 7 big gaps all qualify -> 100% > 30%.
    fs = check_count_in_density(_lines_at(_BIG_GAPS), threshold=5.0)
    assert len(fs) == 1 and fs[0].code == "count_in_density"
    assert fs[0].severity == WARNING
    assert "8 of 8" in fs[0].message


def test_count_in_density_respects_threshold():
    # Same 6s gaps are below a 12s threshold: only the first line -> 12.5% clean.
    assert check_count_in_density(_lines_at(_BIG_GAPS), threshold=12.0) == []


def test_count_in_density_short_song_skipped():
    # Under the min-lines floor, a trivially-100% short song must not warn.
    assert check_count_in_density(_lines_at([0.0, 7.0, 14.0]), threshold=5.0) == []


def test_run_preflight_count_in_density_warns(tmp_path):
    sp = _song(tmp_path, timing=json.dumps(_lines_at(_BIG_GAPS)))
    fs = run_preflight(sp, Config(), context="render")
    assert any(f.code == "count_in_density" for f in fs)
    assert not has_errors(fs)


def test_run_preflight_count_in_density_skipped_when_disabled(tmp_path):
    sp = _song(tmp_path, timing=json.dumps(_lines_at(_BIG_GAPS)))
    cfg = Config(render=RenderConfig(count_in=False))
    assert not any(f.code == "count_in_density"
                   for f in run_preflight(sp, cfg, context="render"))
