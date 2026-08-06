from pathlib import Path
from karaoke.config import Config, RenderConfig


def test_line_left_xs_wrap_group_shares_left_edge():
    from karaoke.render.draw import line_left_xs
    # standalone (width 100) centered in W=1000 -> x=450;
    # wrap group rows (widths 200, 400) share left = (1000-400)//2 = 300
    lines = [{"wrap": False}, {"wrap": False}, {"wrap": True}]
    widths = {0: 100, 1: 200, 2: 400}
    xs = line_left_xs(lines, lambda i_ln: widths[i_ln[0]], 1000)
    assert xs == [450, 300, 300]


def test_line_left_xs_all_standalone_centered():
    from karaoke.render.draw import line_left_xs
    lines = [{"wrap": False}, {"wrap": False}]
    widths = {0: 100, 1: 300}
    xs = line_left_xs(lines, lambda i_ln: widths[i_ln[0]], 1000)
    assert xs == [450, 350]


def test_get_renderer_default_is_pillow():
    from karaoke.render import get_renderer
    from karaoke.render.pillow import PillowRenderer
    assert isinstance(get_renderer(Config()), PillowRenderer)


def test_frame_times_count_and_spacing():
    from karaoke.render.pillow import frame_times
    times = frame_times(duration=2.0, fps=10)
    assert times[0] == 0.0
    assert len(times) == 20
    assert abs(times[1] - 0.1) < 1e-9
    assert times[-1] < 2.0


def test_render_context_defaults():
    from karaoke.render import RenderContext
    ctx = RenderContext()
    assert ctx.lead_in == 0.0
    assert ctx.song_duration is None
    assert ctx.meta.artist is None and ctx.meta.title is None


def test_build_frame_state_emits_expected_fields():
    from karaoke.render import build_frame_state, RenderContext
    from karaoke.timing import Timing, Line, Word
    t = Timing(lines=[Line(words=[Word("a", 0.0, 1.0)])])
    fs = build_frame_state(t, 0.25, Config(), 5.0, RenderContext(song_duration=5.0))
    d = fs.to_dict()
    for key in ("lines", "wait", "wait_outro", "title", "progress", "countin"):
        assert key in d


def test_pillow_render_draws_frames_and_encodes(tmp_path, monkeypatch):
    import glob
    import karaoke.render.pillow as pil
    from karaoke.render.pillow import PillowRenderer
    from karaoke.render import RenderContext
    from karaoke.timing import Timing, Line, Word

    seen = {"encoded": [], "frames": 0}

    def fake_encode(pattern, audio, out, config, lead_in=0.0):
        seen["frames"] = len(glob.glob(pattern.replace("%06d", "*")))
        seen["encoded"].append((Path(audio).name, Path(out).name))
        Path(out).write_bytes(b"v")
        return Path(out)

    monkeypatch.setattr(pil, "encode", fake_encode)
    timing = Timing(lines=[Line(words=[Word("hi", 0.0, 1.0)])])
    cfg = Config(render=RenderConfig(width=64, height=48, fps=4, jobs=1))
    targets = [(tmp_path / "a.wav", tmp_path / "a.mp4"),
               (tmp_path / "b.wav", tmp_path / "b.mp4")]
    out = PillowRenderer().render(timing, targets, cfg, duration=1.0,
                                  ctx=RenderContext(song_duration=1.0))
    assert seen["frames"] == 4            # 1.0s * 4fps
    assert len(seen["encoded"]) == 2      # one encode per target
    assert len(out) == 2
