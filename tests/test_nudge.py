import numpy as np
import pytest
from karaoke.timing import Timing, Line, Word
from karaoke.nudge import shift_line, copy_line_timing
from karaoke.onsets import snap_to_onset


def _t():
    return Timing(lines=[
        Line(words=[Word("a", 1.0, 1.4), Word("b", 1.4, 2.0)]),
        Line(words=[Word("c", 5.0, 5.3), Word("d", 5.3, 6.0)]),
    ])


def test_shift_line_moves_whole_line_preserving_shape():
    out = shift_line(_t(), 1, 8.0)               # line 1 first word -> 8.0
    w = out.lines[1].words
    assert w[0].start == 8.0
    assert round(w[0].end, 2) == 8.3             # 0.3 dur preserved
    assert round(w[1].start, 2) == 8.3 and round(w[1].end, 2) == 9.0
    assert out.lines[0].words[0].start == 1.0    # other line untouched


def test_copy_line_timing_applies_source_offsets_at_start():
    # source line 0 offsets: a@0.0-0.4, b@0.4-1.0 ; apply onto line 1 at start=10
    out = copy_line_timing(_t(), 0, 1, 10.0)
    w = out.lines[1].words
    assert w[0].text == "c" and round(w[0].start, 2) == 10.0 and round(w[0].end, 2) == 10.4
    assert round(w[1].start, 2) == 10.4 and round(w[1].end, 2) == 11.0


def test_snap_to_onset_picks_crossing_nearest_guess():
    # silence then voice starting at frame 50 (0.50s); rough guess 0.55 -> 0.50
    env = np.concatenate([np.zeros(50), np.ones(50)])
    assert abs(snap_to_onset(env, 0.01, 0.55, floor=0.0, window=0.75) - 0.50) < 1e-9


def test_snap_to_onset_chooses_nearest_of_two_onsets():
    env = np.zeros(100)
    env[30:35] = 1.0      # onset at 0.30
    env[70:75] = 1.0      # onset at 0.70
    assert abs(snap_to_onset(env, 0.01, 0.66, floor=0.0, window=0.75) - 0.70) < 1e-9


def test_snap_to_onset_returns_guess_when_no_onset():
    env = np.ones(100)    # continuously voiced, no crossing
    assert snap_to_onset(env, 0.01, 0.5, floor=0.0, window=0.3) == 0.5


# --- fill cleared/marked lines from the file ---
from karaoke.nudge import is_marked_for_reflow, reflow_marked, marked_line_end


def test_marked_line_end_reads_last_word_end():
    ln = Line(words=[Word("a", 5.0, 0.0), Word("b", 0.0, 8.0)])  # last word start=0,end=8
    assert marked_line_end(ln) == 8.0


def test_marked_line_end_none_without_marker():
    ln = Line(words=[Word("a", 5.0, 0.0), Word("b", 6.0, 7.0)])  # last word has real start
    assert marked_line_end(ln) is None


def test_marked_line_end_none_for_single_word():
    assert marked_line_end(Line(words=[Word("a", 5.0, 0.0)])) is None


def test_marked_line_end_ignores_trailing_bg():
    # last NON-bg word "free" carries the end marker (start 0, end 9); trailing bg ooh ignored
    ln = Line(words=[Word("there", 5.0, 0.0), Word("free", 0.0, 9.0),
                     Word("ooh", 0.0, 9.5, bg=True)])
    assert marked_line_end(ln) == 9.0


def test_is_marked_for_reflow_detects_zeroed_first_word_end():
    assert is_marked_for_reflow(Line(words=[Word("a", 5.0, 0.0), Word("b", 0.0, 0.0)]))
    assert is_marked_for_reflow(Line(words=[Word("a", 0.0, 0.0)]))      # fully cleared
    assert not is_marked_for_reflow(Line(words=[Word("a", 1.0, 2.0), Word("b", 2.0, 3.0)]))


def test_reflow_marked_only_changes_marked_lines():
    t = Timing(lines=[
        Line(words=[Word("a", 0.0, 1.0)]),                          # line0 good
        Line(words=[Word("x", 5.0, 0.0), Word("y", 0.0, 0.0)]),     # line1 marked, start 5
        Line(words=[Word("z", 13.0, 14.0)]),                        # line2 good (next start 13)
    ])
    out = reflow_marked(t, {1: 5.0})
    w = [q for ln in out.lines for q in ln.words]
    assert w[0].start == 0.0 and w[0].end == 1.0          # line0 untouched
    assert w[1].start == 5.0 and w[2].start == pytest.approx(9.0)   # x,y across [5,13]
    assert w[3].start == 13.0 and w[3].end == 14.0        # line2 untouched


class _StubForced:
    """Records each window it's asked to align and returns deterministic spans."""
    def __init__(self):
        self.calls = []

    def align_window(self, samples, sr, t0, t1, words):
        self.calls.append((round(t0, 3), round(t1, 3), list(words)))
        n = len(words)
        step = (t1 - t0) / max(1, n)
        return [(t0 + k * step, t0 + k * step + 0.1) for k in range(n)]


def test_reflow_marked_forced_window_no_end_marker():
    t = Timing(lines=[
        Line(words=[Word("a", 0.0, 1.0)]),                       # line0 good, ends 1.0
        Line(words=[Word("x", 5.0, 0.0), Word("y", 0.0, 0.0)]),  # line1 marked start 5
        Line(words=[Word("z", 13.0, 14.0)]),                     # line2 next start 13
    ])
    stub = _StubForced()
    out = reflow_marked(t, {1: 5.0}, forced=stub, samples=[0] * 200, sr=10,
                        search_margin=1.0)
    # left = max(prev_end 1.0, 5.0 - 1.0) = 4.0 ; right = next start 13.0
    assert stub.calls == [(4.0, 13.0, ["x", "y"])]
    w = [q for ln in out.lines for q in ln.words]
    assert (w[0].start, w[0].end) == (0.0, 1.0)        # line0 untouched
    assert w[1].start == 4.0                            # forced span for x
    assert (w[3].start, w[3].end) == (13.0, 14.0)       # line2 untouched


def test_reflow_marked_forced_uses_end_marker():
    t = Timing(lines=[
        Line(words=[Word("a", 0.0, 1.0)]),
        Line(words=[Word("x", 5.0, 0.0), Word("y", 0.0, 8.0)]),  # end marker -> 8.0
        Line(words=[Word("z", 20.0, 21.0)]),
    ])
    stub = _StubForced()
    reflow_marked(t, {1: 5.0}, forced=stub, samples=[0] * 300, sr=10, search_margin=1.0)
    # left = max(1.0, 4.0) = 4.0 ; right = approx_end 8.0 + margin 1.0 = 9.0
    assert stub.calls == [(4.0, 9.0, ["x", "y"])]


def test_reflow_marked_leaves_bg_words_untouched():
    t = Timing(lines=[
        Line(words=[Word("a", 0.0, 1.0)]),                                    # line0
        Line(words=[Word("x", 5.0, 0.0), Word("ooh", 6.5, 7.0, bg=True)]),    # line1 marked + bg
        Line(words=[Word("z", 13.0, 14.0)]),                                  # line2
    ])
    stub = _StubForced()
    out = reflow_marked(t, {1: 5.0}, forced=stub, samples=[0] * 200, sr=10, search_margin=1.0)
    # only the lead word "x" is aligned; window left=max(prev_end 1.0, 5-1)=4, right=next start 13
    assert stub.calls == [(4.0, 13.0, ["x"])]
    ooh = out.lines[1].words[1]
    assert (ooh.start, ooh.end, ooh.bg) == (6.5, 7.0, True)   # bg untouched
    assert out.lines[1].words[0].text == "x"                  # lead re-timed


def test_reflow_marked_bg_only_line_does_not_gate_prev_end():
    # A bg-only interjection sits (in list order) before a marked lead line but
    # overlaps it in time. Its late end must NOT push prev_end and clamp the lead.
    t = Timing(lines=[
        Line(words=[Word("a", 0.0, 1.0)]),                        # line0 lead, ends 1.0
        Line(words=[Word("(wow)", 5.0, 9.0, bg=True)]),           # line1 bg-only, ends 9.0
        Line(words=[Word("x", 4.0, 0.0), Word("y", 0.0, 0.0)]),   # line2 marked, anchor 4
        Line(words=[Word("z", 12.0, 13.0)]),                      # line3 lead, next start 12
    ])
    stub = _StubForced()
    reflow_marked(t, {2: 4.0}, forced=stub, samples=[0] * 300, sr=10, search_margin=1.0)
    # bg line1 (ends 9.0) is skipped: left = max(prev_end 1.0, 4-1) = 3.0, right = 12.0
    assert stub.calls == [(3.0, 12.0, ["x", "y"])]


def test_reflow_marked_skips_bg_only_line_for_next_bound():
    # A bg-only interjection between the marked line and the next lead line must
    # not become the window's right bound.
    t = Timing(lines=[
        Line(words=[Word("a", 0.0, 1.0)]),                        # line0 lead
        Line(words=[Word("x", 4.0, 0.0), Word("y", 0.0, 0.0)]),   # line1 marked, anchor 4
        Line(words=[Word("(look)", 5.0, 6.0, bg=True)]),          # line2 bg-only, start 5
        Line(words=[Word("z", 12.0, 13.0)]),                      # line3 lead, start 12
    ])
    stub = _StubForced()
    reflow_marked(t, {1: 4.0}, forced=stub, samples=[0] * 300, sr=10, search_margin=1.0)
    # right bound skips bg line2 (start 5) and uses lead line3 start 12
    assert stub.calls == [(3.0, 12.0, ["x", "y"])]


# --- reflow from per-line anchors ---
from karaoke.nudge import reflow_anchors


def test_reflow_anchors_pins_line_starts_and_interpolates():
    t = Timing(lines=[
        Line(words=[Word("a", 0.0, 1.0), Word("b", 1.0, 2.0)]),   # line 0
        Line(words=[Word("x", 9.0, 9.0), Word("y", 9.0, 9.0)]),   # line 1 (bad)
        Line(words=[Word("z", 20.0, 21.0)]),                      # line 2
    ])
    out = reflow_anchors(t, {0: 0.0, 1: 10.0, 2: 20.0})
    w = [x for ln in out.lines for x in ln.words]
    assert w[0].start == 0.0 and w[1].start == pytest.approx(5.0)   # line0 a,b across [0,10]
    assert w[2].start == 10.0 and w[3].start == pytest.approx(15.0)  # line1 pinned at 10, x,y across [10,20]
    assert w[4].start == 20.0                                        # line2 pinned at 20


def test_reflow_anchors_interpolates_unanchored_line_between():
    t = Timing(lines=[
        Line(words=[Word("a", 0.0, 1.0)]),     # line 0 anchored
        Line(words=[Word("b", 0.0, 0.0)]),     # line 1 NOT anchored
        Line(words=[Word("c", 0.0, 0.0)]),     # line 2 anchored
    ])
    out = reflow_anchors(t, {0: 0.0, 2: 9.0})  # only 0 and 2; line1 interpolated
    w = [x for ln in out.lines for x in ln.words]
    # words a,b across [0,9] by equal weight -> a 0-4.5, b 4.5-9 ; c pinned at 9
    assert w[0].start == 0.0 and w[1].start == pytest.approx(4.5)
    assert w[2].start == 9.0


def test_reflow_anchors_needs_two():
    t = Timing(lines=[Line(words=[Word("a", 0.0, 1.0)])])
    with pytest.raises(ValueError):
        reflow_anchors(t, {0: 0.0})


def test_reflow_anchors_forced_realigns_interior_keeps_pins():
    t = Timing(lines=[
        Line(words=[Word("a", 0.0, 1.0), Word("b", 1.0, 2.0)]),   # line 0 anchored at 0
        Line(words=[Word("x", 9.0, 9.0), Word("y", 9.0, 9.0)]),   # line 1 (bad)
        Line(words=[Word("z", 20.0, 21.0)]),                      # line 2 anchored at 20
    ])
    stub = _StubForced()
    out = reflow_anchors(t, {0: 0.0, 2: 20.0}, forced=stub, samples=[0] * 300, sr=10)
    # one window between the two anchors, over [0, 20], covering words a,b,x,y
    assert stub.calls == [(0.0, 20.0, ["a", "b", "x", "y"])]
    w = [q for ln in out.lines for q in ln.words]
    assert w[0].start == 0.0          # anchored first word pinned firm at t0
    assert w[4].start == 20.0         # last anchor (z) pinned at 20.0


def test_reflow_anchors_forced_leaves_bg_untouched():
    t = Timing(lines=[
        Line(words=[Word("a", 0.0, 1.0), Word("ooh", 0.5, 1.5, bg=True)]),   # line0 anchored@0 + bg
        Line(words=[Word("z", 20.0, 21.0)]),                                  # line1 anchored@20
    ])
    stub = _StubForced()
    out = reflow_anchors(t, {0: 0.0, 1: 20.0}, forced=stub, samples=[0] * 300, sr=10)
    assert stub.calls == [(0.0, 20.0, ["a"])]                 # only the lead "a"
    ooh = out.lines[0].words[1]
    assert (ooh.start, ooh.end, ooh.bg) == (0.5, 1.5, True)   # bg untouched + flag kept
    assert out.lines[0].words[0].start == 0.0                 # lead pinned


# --- snap-edits: detect hand-edited phrases vs a baseline ---
from karaoke.nudge import changed_runs, apply_run_shifts


def _two_phrases():
    # baseline timing for a 2-line song
    return Timing(lines=[
        Line(words=[Word("a", 1.0, 1.4), Word("b", 1.4, 2.0), Word("c", 2.0, 2.6)]),
        Line(words=[Word("x", 5.0, 5.4), Word("y", 5.4, 6.0)]),
    ])


def test_changed_runs_groups_contiguous_edits():
    base = _two_phrases()
    edited = Timing(lines=[
        Line(words=[Word("a", 1.5, 1.9), Word("b", 1.9, 2.5), Word("c", 2.0, 2.6)]),  # a,b moved
        Line(words=[Word("x", 5.0, 5.4), Word("y", 5.9, 6.5)]),                        # y moved
    ])
    assert changed_runs(base, edited) == [[0, 1], [4]]   # flat indices; a,b contiguous; y alone


def test_changed_runs_raises_on_structure_mismatch():
    base = _two_phrases()
    edited = Timing(lines=[Line(words=[Word("a", 1.0, 1.4)])])
    with pytest.raises(ValueError):
        changed_runs(base, edited)


def test_apply_run_shifts_shifts_each_run_preserving_spacing():
    t = _two_phrases()
    out = apply_run_shifts(t, [[0, 1], [4]], {0: 0.5, 4: -0.3})
    w = [x for ln in out.lines for x in ln.words]
    assert w[0].start == 1.5 and w[0].end == pytest.approx(1.9)  # a +0.5
    assert w[1].start == pytest.approx(1.9) and w[1].end == pytest.approx(2.5)  # b +0.5
    assert w[2].start == 2.0                                     # c unchanged
    assert w[4].start == pytest.approx(5.1)                      # y 5.4 - 0.3
    assert [len(ln.words) for ln in out.lines] == [3, 2]         # structure kept


# --- I2: wrap preservation through nudge line-rebuilders ---

def test_shift_line_preserves_wrap():
    """I2: shift_line must not drop wrap=True."""
    t = Timing(lines=[
        Line(words=[Word("a", 1.0, 1.4), Word("b", 1.4, 2.0)], wrap=False),
        Line(words=[Word("c", 5.0, 5.3), Word("d", 5.3, 6.0)], wrap=True),
    ])
    out = shift_line(t, 1, 8.0)
    assert out.lines[1].wrap is True
    assert out.lines[0].wrap is False


def test_copy_line_timing_preserves_dst_wrap():
    """I2: copy_line_timing must preserve the destination line's wrap flag."""
    t = Timing(lines=[
        Line(words=[Word("a", 1.0, 1.4), Word("b", 1.4, 2.0)], wrap=False),
        Line(words=[Word("c", 5.0, 5.3), Word("d", 5.3, 6.0)], wrap=True),
    ])
    out = copy_line_timing(t, 0, 1, 10.0)
    assert out.lines[1].wrap is True
    assert out.lines[0].wrap is False


def test_apply_run_shifts_preserves_wrap():
    """I2: apply_run_shifts must not drop wrap flags when rebuilding lines."""
    t = Timing(lines=[
        Line(words=[Word("a", 1.0, 1.4), Word("b", 1.4, 2.0), Word("c", 2.0, 2.6)], wrap=False),
        Line(words=[Word("x", 5.0, 5.4), Word("y", 5.4, 6.0)], wrap=True),
    ])
    out = apply_run_shifts(t, [[0, 1], [4]], {0: 0.5, 4: -0.3})
    assert out.lines[0].wrap is False
    assert out.lines[1].wrap is True


# --- bg preservation across coarse nudge ops (same class as shift_all bg drop) ---

def test_shift_line_preserves_bg():
    t = Timing(lines=[
        Line(words=[Word("a", 1.0, 2.0)]),
        Line(words=[Word("lead", 5.0, 5.3), Word("echo", 5.3, 6.0, bg=True)]),
    ])
    out = shift_line(t, 1, 8.0)
    assert [w.bg for w in out.lines[1].words] == [False, True]


def test_copy_line_timing_preserves_bg():
    t = Timing(lines=[
        Line(words=[Word("lead", 1.0, 1.4), Word("echo", 1.4, 2.0)]),
        Line(words=[Word("lead", 5.0, 5.3), Word("echo", 5.3, 6.0, bg=True)]),
    ])
    out = copy_line_timing(t, 0, 1, 10.0)
    assert [w.bg for w in out.lines[1].words] == [False, True]


def test_apply_run_shifts_preserves_bg():
    t = Timing(lines=[
        Line(words=[Word("a", 1.0, 1.4), Word("b", 1.4, 2.0), Word("ooh", 1.6, 2.2, bg=True)]),
        Line(words=[Word("x", 5.0, 5.4), Word("y", 5.4, 6.0)]),
    ])
    out = apply_run_shifts(t, [[0]], {0: 0.5})
    flat = [w for ln in out.lines for w in ln.words]
    assert [w.bg for w in flat] == [False, False, True, False, False]
