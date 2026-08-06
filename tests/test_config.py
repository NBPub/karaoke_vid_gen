from pathlib import Path
from karaoke.config import Config


def test_defaults_when_no_file(tmp_path):
    cfg = Config.load(tmp_path / "missing.toml")
    assert cfg.render.width == 1920
    assert cfg.render.height == 1080
    assert cfg.render.fps == 30
    assert cfg.render.lines_per_page == 6
    assert cfg.render.wait_bar is True
    assert cfg.render.wait_min_gap_seconds == 12.0
    assert cfg.render.wait_bar_end_seconds == 1.0
    assert cfg.render.wait_highlight_seconds == 3.0
    assert cfg.align.onset_snap is True
    assert cfg.align.lead_seconds == 0.10
    assert cfg.align.best_of_n == 1
    assert cfg.audio.bitrate == "320k"
    assert cfg.models.demucs_model == "htdemucs"
    assert cfg.models.device == "cuda"
    assert cfg.render.title_card is True
    assert cfg.render.title_seconds == 3.0
    assert cfg.render.title_read_buffer_seconds == 2.0
    assert cfg.render.title_fade_seconds == 0.5
    assert cfg.render.progress_bar is True
    assert cfg.render.progress_fill_color == "#8B0000"
    assert cfg.render.progress_outline_color == "#4a3f9e"
    assert cfg.render.count_in is True
    assert cfg.render.font_file == ""
    assert cfg.render.jobs == 0
    assert cfg.render.mode == "review"
    assert cfg.render.video_codec == "auto"
    assert cfg.render.nvenc_cq == 23


def test_mode_and_codec_overrides(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[render]\nmode = \"both\"\nvideo_codec = \"libx264\"\nnvenc_cq = 19\n",
                 encoding="utf-8")
    cfg = Config.load(p)
    assert cfg.render.mode == "both"
    assert cfg.render.video_codec == "libx264"
    assert cfg.render.nvenc_cq == 19


def test_renderer_jobs_override(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[render]\njobs = 1\n", encoding="utf-8")
    assert Config.load(p).render.jobs == 1


def test_count_in_override(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[render]\ncount_in = false\n", encoding="utf-8")
    assert Config.load(p).render.count_in is False


def test_title_and_progress_overrides(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        "[render]\ntitle_card = false\ntitle_seconds = 4.0\n"
        "progress_fill_color = \"#330000\"\n",
        encoding="utf-8",
    )
    cfg = Config.load(p)
    assert cfg.render.title_card is False
    assert cfg.render.title_seconds == 4.0
    assert cfg.render.progress_fill_color == "#330000"
    assert cfg.render.progress_bar is True  # untouched default


def test_unknown_key_raises_clear_error(tmp_path):
    import pytest
    p = tmp_path / "config.toml"
    p.write_text("[render]\nbogus_key = 5\n", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        Config.load(p)
    msg = str(exc.value)
    assert "render" in msg.lower()
    assert "bogus_key" in msg


def test_file_overrides_defaults(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        "[render]\nwidth = 1280\nheight = 720\n\n[models]\ndevice = \"cpu\"\n",
        encoding="utf-8",
    )
    cfg = Config.load(p)
    assert cfg.render.width == 1280
    assert cfg.render.height == 720
    assert cfg.render.fps == 30
    assert cfg.models.device == "cpu"


def test_first_line_pad_default_and_override(tmp_path):
    assert Config.load(tmp_path / "missing.toml").align.first_line_pad_seconds == 1.0
    p = tmp_path / "config.toml"
    p.write_text("[align]\nfirst_line_pad_seconds = 0.5\n", encoding="utf-8")
    assert Config.load(p).align.first_line_pad_seconds == 0.5


def test_realign_search_margin_default_and_override(tmp_path):
    assert Config.load(tmp_path / "missing.toml").align.realign_search_margin_seconds == 1.0
    p = tmp_path / "config.toml"
    p.write_text("[align]\nrealign_search_margin_seconds = 0.5\n", encoding="utf-8")
    assert Config.load(p).align.realign_search_margin_seconds == 0.5


def test_history_enabled_default_and_override(tmp_path):
    assert Config.load(tmp_path / "missing.toml").history.enabled is True
    p = tmp_path / "config.toml"
    p.write_text("[history]\nenabled = false\n", encoding="utf-8")
    assert Config.load(p).history.enabled is False


def test_usable_width_frac_default_and_override(tmp_path):
    from karaoke.config import Config
    assert Config().render.usable_width_frac == 0.92
    p = tmp_path / "c.toml"
    p.write_text("[render]\nusable_width_frac = 0.8\n", encoding="utf-8")
    assert Config.load(p).render.usable_width_frac == 0.8


def test_paths_songs_dir_default(tmp_path):
    assert Config.load(tmp_path / "missing.toml").paths.songs_dir == "songs"


def test_paths_songs_dir_override(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[paths]\nsongs_dir = \"/data/karaoke\"\n", encoding="utf-8")
    assert Config.load(p).paths.songs_dir == "/data/karaoke"
