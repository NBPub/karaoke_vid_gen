from karaoke.config import Config, RenderConfig
from karaoke.render.draw import _rgb, load_font


def test_rgb_parses_hex():
    assert _rgb("#0b0e14") == (11, 14, 20)
    assert _rgb("#FFFFFF") == (255, 255, 255)


def test_load_font_returns_font():
    assert load_font(Config()) is not None


def test_load_font_bad_path_falls_back():
    # a non-existent explicit font must not raise; it falls back
    f = load_font(Config(render=RenderConfig(font_file="/no/such/font.ttf")))
    assert f is not None


from karaoke.render.draw import draw_frame
from karaoke.metadata import TrackMeta


def _state(**over):
    s = {"lines": [], "wait": None, "wait_outro": False,
         "title": 0.0, "progress": None, "countin": None}
    s.update(over)
    return s


def _has(img, rgb):
    return any(c == rgb for _, c in img.convert("RGB").getcolors(maxcolors=1 << 24))


def test_draw_frame_size_and_background():
    cfg = Config()
    img = draw_frame(_state(), cfg)
    assert img.size == (cfg.render.width, cfg.render.height)
    assert img.getpixel((0, 0)) == _rgb(cfg.render.background)


def test_draw_frame_progress_fill_present_only_when_set():
    cfg = Config()
    assert _has(draw_frame(_state(progress=1.0), cfg), _rgb(cfg.render.progress_fill_color))
    assert not _has(draw_frame(_state(progress=None), cfg), _rgb(cfg.render.progress_fill_color))


def test_draw_frame_wait_fill_present():
    cfg = Config()
    img = draw_frame(_state(wait=1.0, wait_outro=False), cfg)
    assert _has(img, _rgb(cfg.render.wait_fill_color))


def test_draw_frame_title_changes_image():
    cfg = Config()
    meta = TrackMeta("Pavement", "Cut Your Hair")
    base = draw_frame(_state(title=0.0), cfg, meta)
    titled = draw_frame(_state(title=1.0), cfg, meta)
    assert base.tobytes() != titled.tobytes()   # card text drawn


def test_draw_frame_lyrics_change_image():
    cfg = Config()
    empty = draw_frame(_state(lines=[]), cfg)
    line = {"index": 0, "role": "active",
            "words": [{"text": "hello", "fill": 1.0}]}
    drawn = draw_frame(_state(lines=[line]), cfg)
    assert empty.tobytes() != drawn.tobytes()
