from pathlib import Path
import pytest
from karaoke.timing import Timing, Line, Word
from karaoke.fill import word_fill_fraction, frame_state, page_top

FIX = Path(__file__).parent / "fixtures" / "sample_timing.json"


def _make_timing(n):
    """n single-word lines; line i is word 'wi' spanning [i, i+0.5]."""
    return Timing(lines=[Line(words=[Word(f"w{i}", float(i), float(i) + 0.5)])
                         for i in range(n)])


def test_word_fill_fraction_bounds():
    w = Word("star", 1.0, 3.0)
    assert word_fill_fraction(w, 0.0) == 0.0
    assert word_fill_fraction(w, 1.0) == 0.0
    assert word_fill_fraction(w, 2.0) == 0.5
    assert word_fill_fraction(w, 3.0) == 1.0
    assert word_fill_fraction(w, 9.0) == 1.0


def test_word_fill_zero_duration():
    assert word_fill_fraction(Word("x", 2.0, 2.0), 2.0) == 1.0


def test_frame_state_empty_timing_raises():
    import pytest
    from karaoke.timing import Timing
    with pytest.raises(ValueError):
        frame_state(Timing(lines=[]), 0.0)


def test_page_top_advances_by_step():
    # 6-line page -> step 4; pages start at 0, 4, 8, ...
    assert page_top(0, 6) == 0
    assert page_top(3, 6) == 0
    assert page_top(4, 6) == 4
    assert page_top(7, 6) == 4
    assert page_top(8, 6) == 8


def test_frame_state_first_page_active_at_top():
    t = _make_timing(8)
    fs = frame_state(t, 0.25, lines_per_page=6)  # mid line 0 -> active 0
    assert [ln.index for ln in fs.lines] == [0, 1, 2, 3, 4, 5]
    assert fs.lines[0].role == "active"
    assert all(ln.role == "upcoming" for ln in fs.lines[1:])


def test_frame_state_mid_page_dims_past_lines_no_turn():
    t = _make_timing(8)
    fs = frame_state(t, 3.25, lines_per_page=6)  # mid line 3, still page 0
    roles = {ln.index: ln.role for ln in fs.lines}
    assert [ln.index for ln in fs.lines] == [0, 1, 2, 3, 4, 5]
    assert roles[0] == "past" and roles[2] == "past"
    assert roles[3] == "active"
    assert roles[4] == "upcoming" and roles[5] == "upcoming"


def test_frame_state_next_line_active_during_gap():
    # line 0 spans [0, 0.5], line 1 starts at 1.0; at t=0.7 (the gap) the next
    # line is already active for read-ahead and the finished line has dimmed.
    t = _make_timing(8)
    fs = frame_state(t, 0.7, lines_per_page=6)
    roles = {ln.index: ln.role for ln in fs.lines}
    assert roles[0] == "past"
    assert roles[1] == "active"
    active = [ln for ln in fs.lines if ln.role == "active"][0]
    assert active.words[0].fill == 0.0          # not sung yet, so unfilled


def test_frame_state_turns_when_active_reaches_second_to_last():
    t = _make_timing(8)
    fs = frame_state(t, 4.25, lines_per_page=6)  # mid line 4 -> new page top 4
    assert fs.lines[0].index == 4
    assert fs.lines[0].role == "active"          # carried line is now the top
    assert [ln.index for ln in fs.lines] == [4, 5, 6, 7]   # clamped at 8 lines


def test_frame_state_active_word_fill_is_partial():
    t = _make_timing(8)
    fs = frame_state(t, 3.25, lines_per_page=6)  # word3 spans [3, 3.5] -> 0.5
    active = [ln for ln in fs.lines if ln.role == "active"][0]
    assert abs(active.words[0].fill - 0.5) < 1e-9


# --- wait bar over long instrumental gaps ---
from karaoke.fill import current_gap, wait_fraction


def _two_lines_with_gap(gap_start, next_start):
    # line 0 spans [1.0, gap_start]; line 1 starts at next_start
    return Timing(lines=[Line(words=[Word("a", 1.0, gap_start)]),
                         Line(words=[Word("b", next_start, next_start + 1.0)])])


def test_current_gap_detects_intro_mid_outro():
    t = _two_lines_with_gap(2.0, 20.0)            # line0 [1,2], line1 [20,21]
    assert current_gap(t, 0.5, 30.0) == (0.0, 1.0, False)     # intro (before line 0)
    assert current_gap(t, 10.0, 30.0) == (2.0, 20.0, False)   # mid gap
    assert current_gap(t, 25.0, 30.0) == (21.0, 30.0, True)   # outro (after line 1)
    assert current_gap(t, 1.0, 30.0) is None                  # line 0 being sung


def test_wait_fraction_none_for_short_gap():
    assert wait_fraction((2.0, 10.0, False), 5.0, threshold=12.0, bar_end=1.0) is None


def test_wait_fraction_fills_until_bar_end_then_none():
    gap = (10.0, 30.0, False)                     # 20s gap, > 12 threshold
    assert wait_fraction(gap, 10.0, 12.0, 5.0) == 0.0      # start
    # fills over [10, 30-5=25]; at t=17.5 -> halfway
    assert abs(wait_fraction(gap, 17.5, 12.0, 5.0) - 0.5) < 1e-9
    assert wait_fraction(gap, 26.0, 12.0, 5.0) is None    # past bar_end


def test_wait_fraction_outro_fills_whole_tail():
    gap = (200.0, 220.0, True)                    # 20s outro
    assert abs(wait_fraction(gap, 210.0, 12.0, 1.0) - 0.5) < 1e-9   # no bar_end for outro


def test_frame_state_wait_suppresses_active_early_in_gap():
    t = _two_lines_with_gap(2.0, 20.0)            # mid gap 2..20 (18s > 12)
    fs = frame_state(t, 8.0, lines_per_page=6, duration=30.0)  # well before the end
    assert fs.wait is not None and 0.0 < fs.wait < 1.0
    assert all(ln.role != "active" for ln in fs.lines)   # no bright line behind the bar


def test_frame_state_highlights_next_line_while_bar_still_up():
    # bar ends 1s before line (t=19), highlight starts 3s before (t=17);
    # at t=18 the next line is already active AND the bar is still showing.
    t = _two_lines_with_gap(2.0, 20.0)
    fs = frame_state(t, 18.0, lines_per_page=6, duration=30.0)
    assert fs.wait is not None                           # bar still up
    assert any(ln.role == "active" for ln in fs.lines)   # next line highlighted


def test_frame_state_bar_gone_in_final_second():
    t = _two_lines_with_gap(2.0, 20.0)
    fs = frame_state(t, 19.5, lines_per_page=6, duration=30.0)  # within 1s of line
    assert fs.wait is None
    assert any(ln.role == "active" for ln in fs.lines)


def test_frame_state_outro_sets_wait_outro_flag():
    t = _two_lines_with_gap(2.0, 20.0)            # line 1 ends 21; outro 21..45
    fs = frame_state(t, 30.0, lines_per_page=6, duration=45.0)
    assert fs.wait is not None and fs.wait_outro is True


def test_frame_state_no_wait_without_duration():
    t = _two_lines_with_gap(2.0, 20.0)
    assert frame_state(t, 8.0, lines_per_page=6).wait is None


# --- title card + progress bar pure logic ---
from karaoke.fill import lead_in_seconds


def test_lead_in_pads_early_start_to_floor():
    # title 3s + read buffer 2s = 5s floor; first word at 2s -> delay 3s
    assert lead_in_seconds(2.0, 3.0, 2.0) == 3.0


def test_lead_in_zero_when_word_at_or_after_floor():
    assert lead_in_seconds(5.0, 3.0, 2.0) == 0.0
    assert lead_in_seconds(8.0, 3.0, 2.0) == 0.0


def test_lead_in_partial_pad():
    assert lead_in_seconds(4.5, 3.0, 2.0) == pytest.approx(0.5)


from karaoke.fill import title_alpha


def test_title_alpha_fades_in():
    assert title_alpha(0.0, 3.0, 0.5) == 0.0
    assert title_alpha(0.25, 3.0, 0.5) == pytest.approx(0.5)
    assert title_alpha(0.5, 3.0, 0.5) == 1.0


def test_title_alpha_holds_full():
    assert title_alpha(1.5, 3.0, 0.5) == 1.0


def test_title_alpha_fades_out_then_gone():
    assert title_alpha(2.75, 3.0, 0.5) == pytest.approx(0.5)
    assert title_alpha(3.0, 3.0, 0.5) == 0.0
    assert title_alpha(5.0, 3.0, 0.5) == 0.0


from karaoke.fill import progress_fraction


def test_progress_empty_during_lead_in():
    assert progress_fraction(0.0, 3.0, 10.0) == 0.0
    assert progress_fraction(1.0, 3.0, 10.0) == 0.0
    assert progress_fraction(3.0, 3.0, 10.0) == 0.0


def test_progress_linear_during_song():
    assert progress_fraction(8.0, 3.0, 10.0) == pytest.approx(0.5)


def test_progress_clamps_to_one_at_end():
    assert progress_fraction(13.0, 3.0, 10.0) == 1.0
    assert progress_fraction(20.0, 3.0, 10.0) == 1.0


from karaoke.fill import shift_all


def test_shift_all_moves_every_word():
    t = Timing(lines=[Line(words=[Word("a", 1.0, 1.5), Word("b", 1.5, 2.0)]),
                      Line(words=[Word("c", 5.0, 6.0)])])
    out = shift_all(t, 3.0)
    w = [x for ln in out.lines for x in ln.words]
    assert w[0].start == 4.0 and w[0].end == 4.5
    assert w[1].start == 4.5 and w[2].start == 8.0 and w[2].end == 9.0
    assert [len(ln.words) for ln in out.lines] == [2, 1]


def test_shift_all_zero_is_noop():
    t = Timing(lines=[Line(words=[Word("a", 1.0, 1.5)])])
    out = shift_all(t, 0.0)
    assert out.lines[0].words[0].start == 1.0 and out.lines[0].words[0].end == 1.5


def test_shift_all_preserves_bg_flag():
    """shift_all must carry Word.bg. Dropping it makes bg words count toward
    Line.start/end in every render, shrinking the lead gap so wait bars / count-ins
    that key off the non-bg gap silently vanish (the Who Knows? line-46 bug)."""
    t = Timing(lines=[Line(words=[
        Word("lead", 1.0, 2.0), Word("echo", 3.0, 4.0, bg=True)])])
    for delta in (0.0, 3.0):
        out = shift_all(t, delta)
        assert out.lines[0].words[1].bg is True, f"delta={delta}: bg flag dropped"
        # Line.end must ignore the (later-ending) bg word, matching pre-shift timing.
        assert out.lines[0].end == 2.0 + delta, f"delta={delta}: bg leaked into Line.end"


def test_shift_all_bg_keeps_wait_bar_on_lead_gap():
    """End-to-end seam: a lead gap that clears the wait threshold must still show
    the bar after shift_all, even when the earlier line ends with a trailing bg
    word inside the gap."""
    t = Timing(lines=[
        Line(words=[Word("who", 1.0, 2.0), Word("knows", 4.0, 5.0, bg=True)]),  # lead ends 2.0
        Line(words=[Word("next", 20.0, 21.0)]),                                  # gap 18s > 12
    ])
    out = shift_all(t, 0.0)
    fs = frame_state(out, 10.0, lines_per_page=6, duration=30.0,
                     wait_threshold=12.0, wait_bar_end=1.0, wait_highlight=3.0)
    assert fs.wait is not None   # bar shows across the 18s non-bg gap


def test_shift_all_preserves_wrap_flag():
    """C1: shift_all must carry Line.wrap so frame_state sees it (integration seam)."""
    t = Timing(lines=[
        Line(words=[Word("aa", 1.0, 2.0)], wrap=False),
        Line(words=[Word("bb", 3.0, 4.0)], wrap=True),
    ])
    # Both zero-delta and non-zero delta must preserve wrap.
    for delta in (0.0, 3.0):
        out = shift_all(t, delta)
        assert out.lines[0].wrap is False, f"delta={delta}: line0 wrap should be False"
        assert out.lines[1].wrap is True, f"delta={delta}: line1 wrap should be True"
        # Verify it flows all the way through frame_state (lines_per_page=6 keeps both visible).
        fs = frame_state(out, 3.0 + delta, lines_per_page=6)
        wrap_flags = {ln.index: ln.wrap for ln in fs.lines}
        assert wrap_flags.get(1) is True, (
            f"delta={delta}: LineState for line1 should have wrap=True, got {wrap_flags}")


from karaoke.fill import count_in_fraction


def _two(line0, line1):
    return Timing(lines=[Line(words=[Word("a", *line0)]),
                         Line(words=[Word("b", *line1)])])


def test_count_in_first_line_qualifies():
    t = _two((10.0, 11.0), (12.0, 13.0))   # window 3 -> [7,10]
    assert count_in_fraction(t, 0, 6.0, 3.0, 12.0) is None       # before window
    assert count_in_fraction(t, 0, 8.5, 3.0, 12.0) == pytest.approx(0.5)
    assert count_in_fraction(t, 0, 10.5, 3.0, 12.0) == 1.0        # sung -> persists


def test_count_in_big_gap_qualifies():
    t = _two((0.0, 1.0), (20.0, 21.0))     # gap 19 >= 12 -> qualifies; window [17,20]
    assert count_in_fraction(t, 1, 16.0, 3.0, 12.0) is None
    assert count_in_fraction(t, 1, 18.5, 3.0, 12.0) == pytest.approx(0.5)
    assert count_in_fraction(t, 1, 20.5, 3.0, 12.0) == 1.0


def test_count_in_small_gap_none():
    t = _two((0.0, 1.0), (3.0, 4.0))       # gap 2 < 12 -> no count-in
    assert count_in_fraction(t, 1, 2.5, 3.0, 12.0) is None
    assert count_in_fraction(t, 1, 3.5, 3.0, 12.0) is None


def test_count_in_threshold_decoupled():
    t = _two((0.0, 1.0), (7.0, 8.0))       # gap 6: window 3 -> [4,7]
    # qualifies at the 5s count-in threshold...
    assert count_in_fraction(t, 1, 5.5, 3.0, 5.0) == pytest.approx(0.5)
    # ...but not at the old 12s (wait-bar) threshold.
    assert count_in_fraction(t, 1, 5.5, 3.0, 12.0) is None


def test_frame_state_emits_title_and_progress():
    t = _make_timing(8)
    fs = frame_state(t, 0.25, lines_per_page=6, lead_in=3.0, song_duration=10.0,
                     title_seconds=3.0, title_fade=0.5)
    assert fs.title == pytest.approx(0.5)   # 0.25 into a 0.5s fade-in
    assert fs.progress == 0.0               # t < lead_in
    d = fs.to_dict()
    assert d["title"] == fs.title and d["progress"] == fs.progress


def test_frame_state_defaults_no_title_no_progress():
    fs = frame_state(_make_timing(8), 0.25, lines_per_page=6)
    assert fs.title == 0.0 and fs.progress is None
    d = fs.to_dict()
    assert d["title"] == 0.0 and d["progress"] is None


def test_active_index_holds_line_with_trailing_bg():
    from karaoke.fill import active_index
    t = Timing(lines=[
        Line(words=[Word("lead", 1.0, 5.0), Word("ooh", 2.0, 2.5, bg=True)]),  # lead->5, bg->2.5
        Line(words=[Word("next", 6.0, 7.0)]),
    ])
    # at 4.0 the lead is still being sung; the line must stay active even though
    # the trailing bg "ooh" ended at 2.5.
    assert active_index(t, 4.0) == 0


def test_frame_state_emits_countin_for_active_line():
    t = _two((0.0, 1.0), (20.0, 21.0))     # line1 after a 19s gap
    fs = frame_state(t, 18.5, lines_per_page=6, duration=30.0,
                     wait_threshold=12.0, wait_highlight=3.0)   # window [17,20]
    assert fs.countin == pytest.approx(0.5)
    assert fs.to_dict()["countin"] == fs.countin


def test_frame_state_countin_none_when_disabled():
    t = _two((0.0, 1.0), (20.0, 21.0))
    fs = frame_state(t, 18.5, lines_per_page=6, duration=30.0,
                     wait_threshold=12.0, wait_highlight=3.0, count_in=False)
    assert fs.countin is None
    assert fs.to_dict()["countin"] is None


def test_frame_state_countin_midrange_gap_no_waitbar():
    # A 7s gap: below the 12s wait-bar threshold, at/above the 5s count-in one.
    t = _two((0.0, 1.0), (8.0, 9.0))       # gap 7; count-in window [5,8]
    fs = frame_state(t, 6.5, lines_per_page=6, duration=30.0,
                     wait_threshold=12.0, wait_highlight=3.0,
                     count_in_threshold=5.0)
    assert fs.countin == pytest.approx(0.5)   # dots fill
    assert fs.wait is None                     # but no instrumental-break wait bar
