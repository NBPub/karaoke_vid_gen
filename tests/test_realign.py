from karaoke.realign import interpolate_window, _offset_and_fill


def test_interpolate_window_equal_weight_split():
    out = interpolate_window(["ab", "cd"], 10.0, 20.0)   # equal letter counts
    assert out[0] == (10.0, 15.0)
    assert out[1] == (15.0, 20.0)


def test_interpolate_window_proportional_to_length():
    out = interpolate_window(["a", "abc"], 0.0, 8.0)      # weights 1 and 3
    assert out[0] == (0.0, 2.0)
    assert out[1] == (2.0, 8.0)


def test_interpolate_window_empty():
    assert interpolate_window([], 0.0, 5.0) == []


def test_offset_and_fill_offsets_and_zero_fills():
    out = _offset_and_fill(["a", "-", "b"], {0: (0.0, 1.0), 2: (2.0, 3.0)}, t0=10.0)
    assert out[0] == (10.0, 11.0)
    assert out[1] == (11.0, 11.0)   # unaligned -> zero-length at the previous end
    assert out[2] == (12.0, 13.0)


def test_offset_and_fill_unaligned_first():
    out = _offset_and_fill(["-", "a"], {1: (2.0, 3.0)}, t0=10.0)
    assert out[0] == (10.0, 10.0)
    assert out[1] == (12.0, 13.0)


from karaoke.realign import place_window


class _OKForced:
    def align_window(self, samples, sr, t0, t1, words):
        return [(t0, t0 + 0.5) for _ in words]


class _BoomForced:
    def align_window(self, samples, sr, t0, t1, words):
        raise RuntimeError("model failed")


class _EmptyForced:
    def align_window(self, samples, sr, t0, t1, words):
        return []


def test_place_window_uses_forced_when_ok():
    out = place_window(["a", "b"], 1.0, 5.0, forced=_OKForced(), samples=[0], sr=10)
    assert out == [(1.0, 1.5), (1.0, 1.5)]


def test_place_window_falls_back_when_forced_raises():
    out = place_window(["a", "b"], 1.0, 5.0, forced=_BoomForced(), samples=[0], sr=10)
    assert out == interpolate_window(["a", "b"], 1.0, 5.0)


def test_place_window_falls_back_on_empty():
    out = place_window(["a", "b"], 1.0, 5.0, forced=_EmptyForced(), samples=[0], sr=10)
    assert out == interpolate_window(["a", "b"], 1.0, 5.0)


def test_place_window_interpolates_when_no_forced():
    out = place_window(["a", "b"], 1.0, 5.0, forced=None, samples=None, sr=None)
    assert out == interpolate_window(["a", "b"], 1.0, 5.0)
