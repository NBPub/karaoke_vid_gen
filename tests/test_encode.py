import pytest

import karaoke.render.encode as encode
from karaoke.config import Config


def test_needs_reencode_true_for_wav(monkeypatch):
    monkeypatch.setattr(encode, "_audio_codec", lambda p: "pcm_s16le")
    assert encode.needs_reencode("x.wav") is True


def test_needs_reencode_false_for_aac(monkeypatch):
    monkeypatch.setattr(encode, "_audio_codec", lambda p: "aac")
    assert encode.needs_reencode("x.m4a") is False


def test_build_ffmpeg_cmd_reencode():
    cmd = encode.build_ffmpeg_cmd("frames/%06d.png", "a.wav", "out.mp4",
                                  Config(), reencode=True)
    assert "-c:a" in cmd and "aac" in cmd
    assert "320k" in cmd
    assert "libx264" in cmd


def test_build_ffmpeg_cmd_streamcopy():
    cmd = encode.build_ffmpeg_cmd("frames/%06d.png", "a.m4a", "out.mp4",
                                  Config(), reencode=False)
    assert "copy" in cmd


def test_build_ffmpeg_cmd_is_quiet():
    """Banner / stream dumps suppressed (loglevel error), but the progress line
    is kept (-stats). Errors still surface."""
    cmd = encode.build_ffmpeg_cmd("frames/%06d.png", "a.m4a", "out.mp4",
                                  Config(), reencode=False)
    assert "-hide_banner" in cmd and "-stats" in cmd
    assert "-nostats" not in cmd
    assert cmd[cmd.index("-loglevel") + 1] == "error"


def test_audio_duration_parses_ffprobe(monkeypatch):
    class _R:
        stdout = "189.693333\n"
    monkeypatch.setattr(encode.subprocess, "run", lambda *a, **k: _R())
    assert encode.audio_duration("x.wav") == 189.693333


def test_build_ffmpeg_cmd_adelay_when_lead_in():
    cmd = encode.build_ffmpeg_cmd("frames/%06d.png", "a.m4a", "out.mp4",
                                  Config(), reencode=True, lead_in=2.0)
    assert "-af" in cmd
    assert "adelay=2000:all=1" in " ".join(cmd)
    assert "aac" in cmd            # delayed audio must be re-encoded


def test_build_ffmpeg_cmd_no_adelay_when_zero():
    cmd = encode.build_ffmpeg_cmd("frames/%06d.png", "a.m4a", "out.mp4",
                                  Config(), reencode=False, lead_in=0.0)
    assert "-af" not in cmd
    assert "copy" in cmd


def test_video_codec_auto_uses_nvenc_when_available(monkeypatch):
    monkeypatch.setattr(encode, "_has_nvenc", lambda: True)
    assert encode._video_codec(Config()) == "h264_nvenc"


def test_video_codec_auto_falls_back_to_libx264(monkeypatch):
    monkeypatch.setattr(encode, "_has_nvenc", lambda: False)
    assert encode._video_codec(Config()) == "libx264"


def test_video_codec_forced(monkeypatch):
    from karaoke.config import Config, RenderConfig
    monkeypatch.setattr(encode, "_has_nvenc", lambda: False)
    assert encode._video_codec(Config(render=RenderConfig(video_codec="nvenc"))) == "h264_nvenc"
    monkeypatch.setattr(encode, "_has_nvenc", lambda: True)
    assert encode._video_codec(Config(render=RenderConfig(video_codec="libx264"))) == "libx264"


def test_build_ffmpeg_cmd_nvenc():
    cmd = encode.build_ffmpeg_cmd("f/%06d.png", "a.m4a", "o.mp4", Config(),
                                  reencode=False, video_codec="h264_nvenc")
    assert "h264_nvenc" in cmd
    assert "-cq" in cmd and "23" in cmd
    assert "libx264" not in cmd


def test_encode_auto_nvenc_failure_falls_back_to_libx264(monkeypatch, tmp_path):
    from karaoke.config import Config
    monkeypatch.setattr(encode, "_audio_codec", lambda p: "aac")
    monkeypatch.setattr(encode, "_has_nvenc", lambda: True)   # auto -> nvenc
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if "h264_nvenc" in cmd:
            raise encode.subprocess.CalledProcessError(1, cmd)
        class _Ok:  # libx264 retry succeeds
            returncode = 0
        return _Ok()

    monkeypatch.setattr(encode.subprocess, "run", fake_run)
    encode.encode("f/%06d.png", "a.m4a", str(tmp_path / "o.mp4"), Config(), lead_in=0.0)
    assert any("h264_nvenc" in c for c in calls)   # tried NVENC
    assert any("libx264" in c for c in calls)      # then fell back


def test_encode_delayed_aac_forces_reencode(monkeypatch, tmp_path):
    monkeypatch.setattr(encode, "_audio_codec", lambda p: "aac")  # would normally copy
    monkeypatch.setattr(encode, "_has_nvenc", lambda: False)      # libx264 path, no probe
    captured = {}

    class _Ok:
        returncode = 0

    monkeypatch.setattr(encode.subprocess, "run",
                        lambda cmd, **k: captured.setdefault("cmd", cmd) or _Ok())
    encode.encode("frames/%06d.png", "a.m4a", str(tmp_path / "o.mp4"), Config(), lead_in=1.5)
    assert "aac" in captured["cmd"]
    assert "adelay=1500:all=1" in " ".join(captured["cmd"])


def test_encode_returns_codec_used(monkeypatch, tmp_path):
    cfg = Config.load(tmp_path / "missing.toml")  # video_codec="auto"
    monkeypatch.setattr(encode, "_video_codec", lambda config: "h264_nvenc")
    monkeypatch.setattr(encode, "needs_reencode", lambda p: False)
    monkeypatch.setattr(encode, "build_ffmpeg_cmd", lambda *a, **k: ["true"])
    calls = []
    monkeypatch.setattr(encode.subprocess, "run", lambda cmd, check: calls.append(cmd))
    used = encode.encode("p/%06d.png", "a.wav", str(tmp_path / "o.mp4"), cfg)
    assert used == "h264_nvenc"


def test_build_ffmpeg_cmd_title_from_folder():
    # The video's title tag defaults to the song folder name.
    cmd = encode.build_ffmpeg_cmd(
        "f/%06d.png", "a.m4a",
        "songs/Jonathan Coulton - Code Monkey/karaoke.mp4",
        Config(), reencode=False)
    assert "-metadata" in cmd
    assert "title=Jonathan Coulton - Code Monkey" in cmd


def test_build_ffmpeg_cmd_title_explicit_overrides():
    cmd = encode.build_ffmpeg_cmd("f/%06d.png", "a.m4a", "o.mp4", Config(),
                                  reencode=False, title="Custom Title")
    assert "title=Custom Title" in cmd


def test_encode_reports_libx264_on_nvenc_fallback(monkeypatch, tmp_path):
    cfg = Config.load(tmp_path / "missing.toml")  # auto
    monkeypatch.setattr(encode, "_video_codec", lambda config: "h264_nvenc")
    monkeypatch.setattr(encode, "needs_reencode", lambda p: False)
    monkeypatch.setattr(encode, "build_ffmpeg_cmd", lambda *a, **k: ["x"])
    seq = {"n": 0}

    def fake_run(cmd, check):
        seq["n"] += 1
        if seq["n"] == 1:
            raise encode.subprocess.CalledProcessError(1, cmd)  # NVENC fails

    monkeypatch.setattr(encode.subprocess, "run", fake_run)
    used = encode.encode("p/%06d.png", "a.wav", str(tmp_path / "o.mp4"), cfg)
    assert used == "libx264"


def test_encode_writes_via_temp_then_replaces(monkeypatch, tmp_path):
    """A successful encode targets a temp file and atomically replaces the output."""
    cfg = Config.load(tmp_path / "missing.toml")
    monkeypatch.setattr(encode, "_video_codec", lambda config: "libx264")
    monkeypatch.setattr(encode, "needs_reencode", lambda p: False)
    out = tmp_path / "karaoke.mp4"
    out.write_bytes(b"OLD")                          # an existing, working render

    def fake_run(cmd, check):
        dest = cmd[-1]
        assert dest != str(out)                      # ffmpeg writes a temp, not the final path
        open(dest, "wb").write(b"NEW")               # simulate a completed encode

    monkeypatch.setattr(encode.subprocess, "run", fake_run)
    encode.encode("f/%06d.png", "a.m4a", str(out), cfg)
    assert out.read_bytes() == b"NEW"                # replaced only on success
    assert not list(tmp_path.glob("*.partial.mp4"))  # temp consumed by the replace


def test_encode_failure_leaves_existing_render_untouched(monkeypatch, tmp_path):
    """A failed encode never clobbers an existing render, and cleans up its temp."""
    cfg = Config.load(tmp_path / "missing.toml")
    monkeypatch.setattr(encode, "_video_codec", lambda config: "libx264")  # no NVENC fallback
    monkeypatch.setattr(encode, "needs_reencode", lambda p: False)
    out = tmp_path / "karaoke.mp4"
    out.write_bytes(b"GOOD")

    def boom(cmd, check):
        open(cmd[-1], "wb").write(b"partial")        # wrote a partial temp...
        raise encode.subprocess.CalledProcessError(1, cmd)  # ...then failed

    monkeypatch.setattr(encode.subprocess, "run", boom)
    with pytest.raises(encode.subprocess.CalledProcessError):
        encode.encode("f/%06d.png", "a.m4a", str(out), cfg)
    assert out.read_bytes() == b"GOOD"               # existing render preserved
    assert not list(tmp_path.glob("*.partial.mp4"))  # partial temp removed


def test_encode_keyboardinterrupt_leaves_existing_render(monkeypatch, tmp_path):
    """Ctrl+C mid-encode preserves the existing render and cleans up the temp."""
    cfg = Config.load(tmp_path / "missing.toml")
    monkeypatch.setattr(encode, "_video_codec", lambda config: "libx264")
    monkeypatch.setattr(encode, "needs_reencode", lambda p: False)
    out = tmp_path / "karaoke.mp4"
    out.write_bytes(b"GOOD")

    def interrupt(cmd, check):
        open(cmd[-1], "wb").write(b"partial")
        raise KeyboardInterrupt

    monkeypatch.setattr(encode.subprocess, "run", interrupt)
    with pytest.raises(KeyboardInterrupt):
        encode.encode("f/%06d.png", "a.m4a", str(out), cfg)
    assert out.read_bytes() == b"GOOD"
    assert not list(tmp_path.glob("*.partial.mp4"))
