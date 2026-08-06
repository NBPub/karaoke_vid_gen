import numpy as np
from karaoke.onsets import rms_envelope, noise_floor, snap_start, refine_timing
from karaoke.timing import Timing, Line, Word


def test_rms_envelope_tracks_energy():
    sr = 1000
    samples = np.concatenate([np.zeros(sr), np.ones(sr)])  # 1s silence, 1s tone
    env, hop = rms_envelope(samples, sr, hop=0.1, win=0.1)
    assert hop == 0.1
    assert env[0] < 1e-6          # silent region
    assert env[-1] > 0.9          # loud region


def test_snap_start_moves_back_to_onset():
    # frames 0..4 silent, 5..9 voiced; Whisper start at frame 9 -> snap to 0.05
    env = np.array([0, 0, 0, 0, 0, 1, 1, 1, 1, 1], dtype=float)
    assert abs(snap_start(env, 0.01, 0.09, 0.0, floor=0.0) - 0.05) < 1e-9


def test_snap_start_no_change_when_continuously_voiced():
    env = np.ones(10, dtype=float)               # voiced all the way back
    assert snap_start(env, 0.01, 0.09, 0.0, floor=0.0) == 0.09


def test_snap_start_no_change_when_silence_just_before_start():
    env = np.array([0, 0, 0, 0, 0, 0, 0, 0, 0, 1], dtype=float)  # onset already at start
    assert snap_start(env, 0.01, 0.09, 0.0, floor=0.0) == 0.09


def test_snap_start_bounded_by_earliest():
    # voiced 5..9, but earliest is frame 7 -> cannot go past 0.07
    env = np.array([0, 0, 0, 0, 0, 1, 1, 1, 1, 1], dtype=float)
    out = snap_start(env, 0.01, 0.09, 0.07, floor=0.0)
    assert out >= 0.07


def test_noise_floor_is_low_percentile():
    env = np.array([0.0, 0.0, 0.0, 1.0, 1.0])
    assert noise_floor(env, percentile=10.0) == 0.0


def test_refine_timing_applies_uniform_lead_and_keeps_structure():
    t = Timing(lines=[Line(words=[Word("a", 1.0, 1.5), Word("b", 1.5, 2.0)]),
                      Line(words=[Word("c", 3.0, 3.4)])])
    out = refine_timing(t, "unused.wav", onset_snap=False, lead=0.2)
    assert [len(ln.words) for ln in out.lines] == [2, 1]
    assert out.lines[0].words[0].start == 0.8 and out.lines[0].words[0].end == 1.3
    assert out.lines[1].words[0].start == 2.8


def test_refine_timing_lead_clamped_at_zero():
    t = Timing(lines=[Line(words=[Word("a", 0.1, 0.5)])])
    out = refine_timing(t, "unused.wav", onset_snap=False, lead=0.5)
    assert out.lines[0].words[0].start == 0.0
