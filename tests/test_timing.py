import json
from pathlib import Path
from karaoke.timing import Word, Line, Timing

FIX = Path(__file__).parent / "fixtures" / "sample_timing.json"


def test_word_retimed_carries_all_fields():
    w = Word("ooh", 1.0, 2.0, bg=True)
    r = w.retimed(5.0, 6.5)
    assert (r.text, r.start, r.end, r.bg) == ("ooh", 5.0, 6.5, True)
    assert w.start == 1.0 and w.end == 2.0   # original unchanged


def test_roundtrip_from_fixture():
    t = Timing.from_json(FIX.read_text(encoding="utf-8"))
    assert len(t.lines) == 2
    assert t.lines[0].words[0].text == "Twinkle"
    assert t.lines[0].text == "Twinkle twinkle little star"
    assert t.lines[0].start == 0.0
    assert t.lines[0].end == 2.6
    again = Timing.from_json(t.to_json())
    assert again == t


def test_bg_roundtrip_emits_only_when_true():
    t = Timing(lines=[Line(words=[Word("a", 0.0, 1.0), Word("ooh", 0.5, 1.5, bg=True)])])
    s = t.to_json()
    assert '"bg": true' in s
    data = json.loads(s)
    assert "bg" not in data["lines"][0]["words"][0]   # normal word unchanged
    assert data["lines"][0]["words"][1]["bg"] is True
    again = Timing.from_json(s)
    assert again == t
    assert again.lines[0].words[1].bg is True
    assert again.lines[0].words[0].bg is False


def test_from_json_defaults_bg_false():
    t = Timing.from_json('{"lines":[{"words":[{"text":"a","start":0,"end":1}]}]}')
    assert t.lines[0].words[0].bg is False


def test_line_end_ignores_trailing_bg():
    ln = Line(words=[Word("lead", 1.0, 3.0), Word("ooh", 2.0, 2.5, bg=True)])
    assert ln.end == 3.0    # lead end, not the earlier bg end
    assert ln.start == 1.0


def test_line_start_ignores_leading_bg():
    ln = Line(words=[Word("ooh", 0.0, 0.5, bg=True), Word("lead", 1.0, 3.0)])
    assert ln.start == 1.0
    assert ln.end == 3.0


def test_line_all_bg_falls_back():
    ln = Line(words=[Word("o1", 1.0, 2.0, bg=True), Word("o2", 2.0, 3.0, bg=True)])
    assert ln.start == 1.0   # words[0].start fallback
    assert ln.end == 3.0     # words[-1].end fallback


def test_wrap_roundtrip_emits_only_when_true():
    t = Timing(lines=[Line(words=[Word("a", 0, 1)]),
                      Line(words=[Word("b", 1, 2)], wrap=True)])
    s = t.to_json()
    data = json.loads(s)
    assert "wrap" not in data["lines"][0]              # default line: no key
    assert data["lines"][1]["wrap"] is True
    again = Timing.from_json(s)
    assert again.lines[0].wrap is False and again.lines[1].wrap is True
