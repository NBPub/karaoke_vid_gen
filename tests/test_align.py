from pathlib import Path
import pytest
import karaoke.align as align
from karaoke.timing import Timing, Line, Word


class FakeAligner:
    def align(self, vocals_path, lines):
        out = []
        for i, line in enumerate(lines):
            words = line.split()
            out.append(Line(words=[Word(w, float(i), float(i) + 1.0) for w in words]))
        return Timing(lines=out)


def _silent_wav(path, seconds, sr=8000):
    import numpy as np, soundfile as sf
    sf.write(str(path), np.zeros(int(seconds * sr), dtype="float32"), sr)


class _RecAligner:
    """Records the duration (s) of the wav it is handed; returns one word at 0-1s."""
    def __init__(self):
        self.seconds = None

    def align(self, vocals_path, lines):
        import soundfile as sf
        data, sr = sf.read(str(vocals_path))
        self.seconds = round(len(data) / sr, 2)
        return Timing(lines=[Line(words=[Word("hello", 0.0, 1.0)])])


def test_align_song_first_line_trims_and_offsets(tmp_path):
    vocals = tmp_path / "vocals.wav"; _silent_wav(vocals, 10.0)
    lyrics = tmp_path / "lyrics.txt"; lyrics.write_text("hello", encoding="utf-8")
    stub = _RecAligner()
    t = align.align_song(vocals, lyrics, tmp_path / "timing.json", aligner=stub,
                         first_line_seconds=3.0, first_line_pad=1.0)
    assert stub.seconds == 8.0                       # trimmed at 3.0-1.0=2.0 -> 8s left
    assert t.lines[0].words[0].start == 2.0          # offset back by trim_start


def test_align_song_no_hint_uses_full_audio(tmp_path):
    vocals = tmp_path / "vocals.wav"; _silent_wav(vocals, 10.0)
    lyrics = tmp_path / "lyrics.txt"; lyrics.write_text("hello", encoding="utf-8")
    stub = _RecAligner()
    t = align.align_song(vocals, lyrics, tmp_path / "timing.json", aligner=stub)
    assert stub.seconds == 10.0                      # full audio, no trim
    assert t.lines[0].words[0].start == 0.0          # no offset


def test_align_song_writes_timing(tmp_path):
    vocals = tmp_path / "vocals.wav"; vocals.write_bytes(b"x")
    lyrics = tmp_path / "lyrics.txt"; lyrics.write_text("hello world\nfoo", encoding="utf-8")
    timing_out = tmp_path / "timing.json"
    align.align_song(vocals, lyrics, timing_out, aligner=FakeAligner())
    t = Timing.from_json(timing_out.read_text(encoding="utf-8"))
    assert len(t.lines) == 2
    assert t.lines[0].text == "hello world"


def test_align_song_applies_lead_offset(tmp_path):
    # lead shifts every word earlier; onset_snap off so no audio is read.
    # FakeAligner puts "hello world" at start=0.0, end=1.0.
    vocals = tmp_path / "vocals.wav"; vocals.write_bytes(b"x")
    lyrics = tmp_path / "lyrics.txt"; lyrics.write_text("hello world", encoding="utf-8")
    timing_out = tmp_path / "timing.json"
    align.align_song(vocals, lyrics, timing_out, aligner=FakeAligner(),
                     onset_snap=False, lead_seconds=0.2)
    w = Timing.from_json(timing_out.read_text(encoding="utf-8")).lines[0].words[0]
    assert w.start == 0.0          # 0.0 - 0.2 clamped at zero
    assert w.end == pytest.approx(0.8)  # 1.0 - 0.2


def test_align_song_raises_on_empty_lyrics(tmp_path):
    vocals = tmp_path / "vocals.wav"; vocals.write_bytes(b"x")
    lyrics = tmp_path / "lyrics.txt"; lyrics.write_text("   \n", encoding="utf-8")
    timing_out = tmp_path / "timing.json"
    with pytest.raises(ValueError):
        align.align_song(vocals, lyrics, timing_out, aligner=FakeAligner())


# --- best-of-N transcript selection (pure) ---

from karaoke.align import _select_transcript
from karaoke.reconcile import AsrWord


def test_select_transcript_keeps_greedy_on_tie():
    known = list("abcdefghij")
    greedy = [AsrWord(c, i, i + 1) for i, c in enumerate("abcdefghij")]   # anchors 10
    sample = [AsrWord(c, i, i + 1) for i, c in enumerate("abcdefghij")]   # also 10
    assert _select_transcript(known, [greedy, sample]) is greedy          # prefer greedy


def test_select_transcript_switches_when_sample_beats_greedy_by_margin():
    known = list("abcdefghij")
    greedy = [AsrWord(c, i, i + 1) for i, c in enumerate("abcde")]        # anchors 5
    sample = [AsrWord(c, i, i + 1) for i, c in enumerate("abcdefghij")]   # anchors 10
    assert _select_transcript(known, [greedy, sample]) is sample


# --- pure helpers used by TorchAudioAligner (testable without torch/models) ---

VALID = set("abcdefghijklmnopqrstuvwxyz'")


def test_normalize_word_keeps_only_vocab_chars():
    # internal hyphens removed (they map to the blank token and crash forced_align)
    assert align._normalize_word("Mental-Pack", VALID) == "mentalpack"
    assert align._normalize_word("boil-in-bag", VALID) == "boilinbag"
    # trailing punctuation removed
    assert align._normalize_word("limb.", VALID) == "limb"
    assert align._normalize_word("viva,", VALID) == "viva"
    # internal apostrophe kept (it's in the vocabulary)
    assert align._normalize_word("can't", VALID) == "can't"
    # all-non-vocab tokens normalize to empty
    assert align._normalize_word("-", VALID) == ""
    assert align._normalize_word("1979", VALID) == ""


def test_fill_word_timings_synthesizes_zero_length_for_unaligned():
    flat = ["a", "-", "b"]
    aligned = {0: (0.0, 1.0), 2: (2.0, 3.0)}  # index 1 ("-") was not alignable
    words = align._fill_word_timings(flat, aligned)
    assert [w.text for w in words] == ["a", "-", "b"]
    assert (words[0].start, words[0].end) == (0.0, 1.0)
    # unaligned word gets a zero-length span at the previous aligned end
    assert (words[1].start, words[1].end) == (1.0, 1.0)
    assert (words[2].start, words[2].end) == (2.0, 3.0)


def test_fill_word_timings_unaligned_before_any_aligned():
    flat = ["-", "a"]
    aligned = {1: (2.0, 3.0)}
    words = align._fill_word_timings(flat, aligned)
    assert (words[0].start, words[0].end) == (0.0, 0.0)
    assert (words[1].start, words[1].end) == (2.0, 3.0)
