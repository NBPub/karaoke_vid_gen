from karaoke.timing import Timing, Line, Word
from karaoke import linesplit as ls


def _timing(lines):  # lines: list of list of (text, start, end)
    return Timing(lines=[Line(words=[Word(t, s, e) for t, s, e in ws]) for ws in lines])


def test_words_match_true_when_only_boundaries_move():
    t = _timing([[("a", 0, 1), ("b", 1, 2)], [("c", 2, 3)]])
    assert ls.words_match(t, ["a", "b c"]) is True          # regrouped, same words


def test_words_match_false_when_a_word_changed():
    t = _timing([[("a", 0, 1), ("b", 1, 2)]])
    assert ls.words_match(t, ["a", "bee"]) is False


def test_resegment_regroups_and_preserves_times_and_bg():
    t = Timing(lines=[Line(words=[
        Word("a", 0.0, 1.0), Word("b", 1.0, 2.0, bg=True), Word("c", 2.0, 3.0)])])
    out = ls.resegment(t, [1, 2])
    assert [len(l.words) for l in out.lines] == [1, 2]
    assert out.lines[1].words[0].text == "b" and out.lines[1].words[0].bg is True
    assert out.lines[1].words[1].start == 2.0            # times preserved
    assert out.lines[0].wrap is False                    # wrap not carried


def test_resegment_rejects_count_mismatch():
    t = _timing([[("a", 0, 1), ("b", 1, 2)]])
    import pytest
    with pytest.raises(ValueError):
        ls.resegment(t, [1])


def test_balanced_wrap_two_balanced_rows():
    # measure = 10px per char (incl. the trailing space each word adds)
    m = lambda s: 10.0 * len(s)
    words = [Word(w, 0, 1) for w in "aaaa bbbb cccc dddd".split()]
    rows = ls.balanced_wrap(words, m, usable=110.0)   # full ~= 200px -> 2 rows
    assert len(rows) == 2
    assert [w.text for w in rows[0]] == ["aaaa", "bbbb"]
    assert [w.text for w in rows[1]] == ["cccc", "dddd"]


def test_balanced_wrap_min_rows_three():
    m = lambda s: 10.0 * len(s)
    words = [Word(w, 0, 1) for w in "aa bb cc dd ee ff".split()]  # ~180px
    rows = ls.balanced_wrap(words, m, usable=70.0)   # each row <= 70px -> 3 rows
    assert len(rows) == 3
    assert all(m("".join(w.text + " " for w in r)) <= 70.0 for r in rows)


def test_balanced_wrap_single_word_over_usable_does_not_crash():
    m = lambda s: 10.0 * len(s)
    words = [Word("supercalifragilistic", 0, 1)]
    rows = ls.balanced_wrap(words, m, usable=50.0)
    assert rows == [words]                               # one over-wide row, no crash
