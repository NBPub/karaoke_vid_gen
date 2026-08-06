import numpy as np
import pytest
from karaoke import no_extract as nx


# --- parse_intervals ---

def test_parse_basic_with_comments_and_blanks():
    text = "# spoken intro\n0:00-0:12\n\n2:30-2:38.5\n"
    assert nx.parse_intervals(text) == [(0.0, 12.0), (150.0, 158.5)]


def test_parse_plain_seconds():
    assert nx.parse_intervals("3-5.5\n") == [(3.0, 5.5)]


def test_parse_empty_or_comments_only():
    assert nx.parse_intervals("") == []
    assert nx.parse_intervals("# nothing\n\n") == []


def test_parse_missing_dash_raises():
    with pytest.raises(ValueError):
        nx.parse_intervals("0:10\n")


def test_parse_start_ge_end_raises():
    with pytest.raises(ValueError):
        nx.parse_intervals("0:20-0:10\n")


def test_parse_clamps_to_duration():
    assert nx.parse_intervals("0:00-1:00\n", duration=30.0) == [(0.0, 30.0)]


def test_parse_drops_interval_out_of_range_after_clamp():
    # starts past the song -> clamps empty -> dropped
    assert nx.parse_intervals("0:40-0:50\n", duration=30.0) == []


# --- splice_original ---

def test_splice_middle_is_song_edges_outside_are_instr_mono():
    sr = 100
    instr = np.zeros(sr, dtype=float)
    song = np.ones(sr, dtype=float)
    out = nx.splice_original(instr, song, sr, [(0.1, 0.5)], fade_seconds=0.1)
    assert out[30] == 1.0          # pure-original middle
    assert out[0] == 0.0           # well before
    assert out[60] == 0.0          # well after
    assert 0.0 < out[12] < 1.0     # inside the start crossfade
    assert instr[30] == 0.0        # input not mutated


def test_splice_handles_stereo():
    sr = 100
    instr = np.zeros((sr, 2), dtype=float)
    song = np.ones((sr, 2), dtype=float)
    out = nx.splice_original(instr, song, sr, [(0.1, 0.5)], fade_seconds=0.1)
    assert out[30, 0] == 1.0 and out[30, 1] == 1.0
    assert out[0, 0] == 0.0


def test_splice_short_interval_does_not_crash():
    sr = 100
    instr = np.zeros(sr, dtype=float)
    song = np.ones(sr, dtype=float)
    out = nx.splice_original(instr, song, sr, [(0.10, 0.12)], fade_seconds=0.1)
    assert out.shape == instr.shape
