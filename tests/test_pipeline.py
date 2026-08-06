from pathlib import Path
import karaoke.pipeline as pipeline


def test_cached_skips_when_output_exists(tmp_path):
    out = tmp_path / "song.wav"; out.write_bytes(b"x")
    calls = []
    pipeline.run_stage("acquire", out, lambda: calls.append("ran"), force=False)
    assert calls == []


def test_cached_runs_when_missing(tmp_path):
    out = tmp_path / "song.wav"
    calls = []
    pipeline.run_stage("acquire", out, lambda: calls.append("ran"), force=False)
    assert calls == ["ran"]


def test_force_reruns(tmp_path):
    out = tmp_path / "song.wav"; out.write_bytes(b"x")
    calls = []
    pipeline.run_stage("acquire", out, lambda: calls.append("ran"), force=True)
    assert calls == ["ran"]


# --- render duration resolution ---
from karaoke.pipeline import resolve_render_duration


def test_resolve_full_song_when_trailing_gap_small():
    # last lyric at 170s, song 189s -> 19s gap < 60 -> full song
    assert resolve_render_duration(170.0, 189.0, threshold=60.0) == 189.0


def test_resolve_returns_none_when_trailing_gap_large():
    # 89s of instrumental after the last lyric -> needs user decision
    assert resolve_render_duration(100.0, 189.0, threshold=60.0) is None


def test_resolve_full_flag_overrides_gap():
    assert resolve_render_duration(100.0, 189.0, full=True, threshold=60.0) == 189.0


def test_resolve_tail_ends_after_last_lyric_capped_at_audio():
    assert resolve_render_duration(170.0, 189.0, tail=5.0) == 175.0
    assert resolve_render_duration(187.0, 189.0, tail=10.0) == 189.0  # capped at audio


def _song_with_audio(tmp_path):
    from karaoke.paths import SongPaths
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.timing_json.write_text(
        '{"lines":[{"words":[{"text":"hi","start":0.0,"end":1.0}]}]}', encoding="utf-8")
    sp.instrumental.write_bytes(b"x")
    sp.song.write_bytes(b"y")
    return sp


class _FakeRenderer:
    """Captures every render pass and writes a stub file for each target output.

    Single-target modes make one pass, so ``captured[...]`` holds that pass.
    ``captured["calls"]`` accumulates all passes (mode "both" can make two when a
    review pass strips a lead-in the karaoke pass keeps)."""
    def __init__(self, captured):
        self.captured = captured
        captured.setdefault("calls", [])

    def render(self, timing, targets, config, duration, ctx=None):
        self.captured["duration"] = duration
        self.captured["targets"] = list(targets)
        self.captured["ctx"] = ctx
        self.captured["timing"] = timing
        self.captured["calls"].append(
            {"duration": duration, "targets": list(targets), "ctx": ctx,
             "timing": timing})
        for _, out in targets:
            Path(out).write_bytes(b"v")
        return [out for _, out in targets]


def test_run_render_asks_user_and_trims_when_declined(tmp_path, monkeypatch):
    from karaoke.config import Config
    sp = _song_with_audio(tmp_path)
    monkeypatch.setattr("karaoke.render.encode.audio_duration", lambda p: 200.0)
    captured = {}
    monkeypatch.setattr("karaoke.pipeline.get_renderer", lambda cfg: _FakeRenderer(captured))

    asked = {}

    def confirm(gap):
        asked["gap"] = gap
        return False  # decline the full outro -> trim to last + tail_seconds (3.0)

    pipeline.run_render(sp, Config(), confirm_full_outro=confirm)
    assert asked["gap"] == 199.0
    assert captured["ctx"].song_duration == 4.0    # 1.0 last + 3.0 tail
    # review (default mode) strips the early-lyrics lead-in -> no buffer
    assert captured["ctx"].lead_in == 0.0
    assert captured["duration"] == 4.0             # song only, no lead-in


def test_run_render_karaoke_builds_lead_in_and_shifts_timing(tmp_path, monkeypatch):
    from karaoke.config import Config
    sp = _song_with_audio(tmp_path)        # folder "A - B", first word at 0.0
    monkeypatch.setattr("karaoke.render.encode.audio_duration", lambda p: 10.0)
    captured = {}
    monkeypatch.setattr("karaoke.pipeline.get_renderer", lambda cfg: _FakeRenderer(captured))

    pipeline.run_render(sp, Config(), full=True, mode="karaoke")
    ctx = captured["ctx"]
    assert ctx.lead_in == 5.0                       # 5s floor - 0s first word
    assert ctx.title is True
    assert ctx.song_duration == 10.0
    assert captured["duration"] == 15.0             # song + lead-in
    assert captured["timing"].lines[0].words[0].start == 5.0   # timing shifted
    assert ctx.meta.artist == "A" and ctx.meta.title == "B"


def test_run_render_review_strips_lead_in_when_lyrics_start_early(tmp_path, monkeypatch):
    from karaoke.config import Config
    sp = _song_with_audio(tmp_path)        # first word at 0.0 -> lead-in would apply
    monkeypatch.setattr("karaoke.render.encode.audio_duration", lambda p: 10.0)
    captured = {}
    monkeypatch.setattr("karaoke.pipeline.get_renderer", lambda cfg: _FakeRenderer(captured))

    pipeline.run_render(sp, Config(), full=True)   # default mode = review
    ctx = captured["ctx"]
    assert ctx.lead_in == 0.0                       # buffer stripped for review
    assert ctx.title is False                       # and its title card dropped
    assert captured["duration"] == 10.0             # song only
    assert captured["timing"].lines[0].words[0].start == 0.0   # unshifted -> matches file


def test_run_render_review_keeps_title_when_lyrics_start_late(tmp_path, monkeypatch):
    from karaoke.config import Config
    from karaoke.paths import SongPaths
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    # first word at 8.0s -> no lead-in needed, so review keeps the title card
    sp.timing_json.write_text(
        '{"lines":[{"words":[{"text":"hi","start":8.0,"end":9.0}]}]}', encoding="utf-8")
    sp.instrumental.write_bytes(b"x")
    sp.song.write_bytes(b"y")
    monkeypatch.setattr("karaoke.render.encode.audio_duration", lambda p: 12.0)
    captured = {}
    monkeypatch.setattr("karaoke.pipeline.get_renderer", lambda cfg: _FakeRenderer(captured))

    pipeline.run_render(sp, Config(), full=True)   # default mode = review
    ctx = captured["ctx"]
    assert ctx.lead_in == 0.0
    assert ctx.title is True                        # no lead-in to strip -> title stays
    assert captured["timing"].lines[0].words[0].start == 8.0   # unshifted


def test_run_render_no_lead_in_when_title_card_off(tmp_path, monkeypatch):
    from karaoke.config import Config, RenderConfig
    sp = _song_with_audio(tmp_path)
    monkeypatch.setattr("karaoke.render.encode.audio_duration", lambda p: 10.0)
    captured = {}
    monkeypatch.setattr("karaoke.pipeline.get_renderer", lambda cfg: _FakeRenderer(captured))

    pipeline.run_render(sp, Config(render=RenderConfig(title_card=False)), full=True)
    assert captured["ctx"].lead_in == 0.0
    assert captured["duration"] == 10.0
    assert captured["timing"].lines[0].words[0].start == 0.0   # unshifted


def test_run_render_mode_both_splits_passes_when_lead_in(tmp_path, monkeypatch):
    from karaoke.config import Config
    sp = _song_with_audio(tmp_path)        # first word at 0.0 -> karaoke gets a lead-in
    monkeypatch.setattr("karaoke.render.encode.audio_duration", lambda p: 10.0)
    captured = {}
    monkeypatch.setattr("karaoke.pipeline.get_renderer", lambda cfg: _FakeRenderer(captured))

    pipeline.run_render(sp, Config(), full=True, mode="both")
    assert sp.output_mp4.exists() and sp.review_mp4.exists()
    calls = captured["calls"]
    assert len(calls) == 2                          # review and karaoke differ -> two passes
    by_out = {c["targets"][0][1]: c for c in calls}
    review, karaoke = by_out[sp.review_mp4], by_out[sp.output_mp4]
    assert review["ctx"].lead_in == 0.0 and review["ctx"].title is False
    assert karaoke["ctx"].lead_in == 5.0 and karaoke["ctx"].title is True


def test_run_render_mode_both_single_pass_when_no_lead_in(tmp_path, monkeypatch):
    from karaoke.config import Config
    from karaoke.paths import SongPaths
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.timing_json.write_text(   # first word late -> review == karaoke, one pass
        '{"lines":[{"words":[{"text":"hi","start":8.0,"end":9.0}]}]}', encoding="utf-8")
    sp.instrumental.write_bytes(b"x")
    sp.song.write_bytes(b"y")
    monkeypatch.setattr("karaoke.render.encode.audio_duration", lambda p: 12.0)
    captured = {}
    monkeypatch.setattr("karaoke.pipeline.get_renderer", lambda cfg: _FakeRenderer(captured))

    pipeline.run_render(sp, Config(), full=True, mode="both")
    assert sp.output_mp4.exists() and sp.review_mp4.exists()
    assert len(captured["calls"]) == 1              # identical frames -> drawn once
    assert (sp.instrumental, sp.output_mp4) in captured["targets"]
    assert (sp.song, sp.review_mp4) in captured["targets"]


def test_run_render_mode_karaoke_only(tmp_path, monkeypatch):
    from karaoke.config import Config
    sp = _song_with_audio(tmp_path)
    monkeypatch.setattr("karaoke.render.encode.audio_duration", lambda p: 10.0)
    captured = {}
    monkeypatch.setattr("karaoke.pipeline.get_renderer", lambda cfg: _FakeRenderer(captured))

    pipeline.run_render(sp, Config(), full=True, mode="karaoke")
    assert captured["targets"] == [(sp.instrumental, sp.output_mp4)]
    assert not sp.review_mp4.exists()


def test_run_render_mode_review_default(tmp_path, monkeypatch):
    from karaoke.config import Config
    sp = _song_with_audio(tmp_path)
    monkeypatch.setattr("karaoke.render.encode.audio_duration", lambda p: 10.0)
    captured = {}
    monkeypatch.setattr("karaoke.pipeline.get_renderer", lambda cfg: _FakeRenderer(captured))

    pipeline.run_render(sp, Config(), full=True)   # default mode = "review"
    assert captured["targets"] == [(sp.song, sp.review_mp4)]


def test_render_targets_by_mode(tmp_path):
    from karaoke.config import Config
    from karaoke.paths import SongPaths
    from karaoke.pipeline import render_targets
    sp = SongPaths.for_song(tmp_path, "A - B")
    cfg = Config()
    assert render_targets(sp, cfg, "karaoke") == [(sp.instrumental, sp.output_mp4)]
    assert render_targets(sp, cfg, "review") == [(sp.song, sp.review_mp4)]
    assert render_targets(sp, cfg, "both") == [
        (sp.instrumental, sp.output_mp4), (sp.song, sp.review_mp4)]


def test_render_skips_only_when_all_outputs_exist(tmp_path):
    a = tmp_path / "karaoke.mp4"
    b = tmp_path / "karaoke.review.mp4"
    a.write_bytes(b"x")
    calls = []
    pipeline.run_stage_multi("render", [a, b], lambda: calls.append(1), force=False)
    assert calls == [1]  # review copy missing -> stage runs
    b.write_bytes(b"x")
    calls.clear()
    pipeline.run_stage_multi("render", [a, b], lambda: calls.append(1), force=False)
    assert calls == []  # both present -> skip


# --- aligner backend selection ---
from karaoke.config import Config, ModelConfig
from karaoke.align import WhisperAligner, TorchAudioAligner


def test_make_aligner_defaults_to_whisper():
    a = pipeline.make_aligner(Config())
    assert isinstance(a, WhisperAligner)
    assert a.model == "medium"
    assert a.best_of_n == 1


def test_make_aligner_passes_best_of_n():
    from karaoke.config import AlignConfig
    a = pipeline.make_aligner(Config(align=AlignConfig(best_of_n=5)))
    assert isinstance(a, WhisperAligner)
    assert a.best_of_n == 5


def test_make_aligner_torchaudio_when_configured():
    cfg = Config(models=ModelConfig(aligner="torchaudio"))
    assert isinstance(pipeline.make_aligner(cfg), TorchAudioAligner)


def test_run_align_model_override_builds_that_aligner(tmp_path, monkeypatch):
    from karaoke.paths import SongPaths
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.vocals.write_bytes(b"x")
    sp.lyrics_txt.write_text("hi", encoding="utf-8")
    seen = {}
    monkeypatch.setattr(pipeline.align_mod, "align_song",
                        lambda v, l, out, aligner, **kw: (seen.__setitem__("aligner", aligner),
                                                          out.write_text('{"lines": []}', encoding="utf-8")))
    monkeypatch.setattr(pipeline.history, "append_row",
                        lambda *a, **k: seen.__setitem__("model", k.get("model")))
    # config default is whisper; override to mms
    pipeline.run_align(sp, Config(), force=True, model="mms")
    assert isinstance(seen["aligner"], TorchAudioAligner)
    assert seen["model"] == "mms"


def test_run_align_default_model_follows_config(tmp_path, monkeypatch):
    from karaoke.paths import SongPaths
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.vocals.write_bytes(b"x")
    sp.lyrics_txt.write_text("hi", encoding="utf-8")
    seen = {}
    monkeypatch.setattr(pipeline.align_mod, "align_song",
                        lambda v, l, out, aligner, **kw: (seen.__setitem__("aligner", aligner),
                                                          out.write_text('{"lines": []}', encoding="utf-8")))
    monkeypatch.setattr(pipeline.history, "append_row",
                        lambda *a, **k: seen.__setitem__("model", k.get("model")))
    pipeline.run_align(sp, Config(models=ModelConfig(aligner="torchaudio")), force=True)
    assert isinstance(seen["aligner"], TorchAudioAligner)
    assert seen["model"] == "mms"      # torchaudio maps to the "mms" label


# --- run_split ---

def test_run_split_resegments_from_lyrics(tmp_path, monkeypatch):
    from karaoke import pipeline
    from karaoke.config import Config
    from karaoke.paths import SongPaths
    from karaoke.timing import Timing
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    # one timing line, two words; lyrics splits it into two lines
    sp.timing_json.write_text(
        '{"lines": [{"words": [{"text": "aa", "start": 1.0, "end": 2.0},'
        '{"text": "bb", "start": 2.0, "end": 3.0}]}]}', encoding="utf-8")
    sp.lyrics_txt.write_text("aa\nbb\n", encoding="utf-8")
    # measure so nothing is too wide (skip auto-split)
    monkeypatch.setattr("karaoke.preflight._line_measurer", lambda cfg: (lambda t: 1.0))
    pipeline.run_split(sp, Config())
    out = Timing.from_json(sp.timing_json.read_text(encoding="utf-8"))
    assert [len(l.words) for l in out.lines] == [1, 1]         # re-segmented
    assert sp.timing_json.with_suffix(".json.bak").exists()    # backup written


def test_run_split_refuses_on_word_change(tmp_path, monkeypatch):
    from karaoke import pipeline
    from karaoke.config import Config
    from karaoke.paths import SongPaths
    import pytest
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.timing_json.write_text(
        '{"lines": [{"words": [{"text": "aa", "start": 1.0, "end": 2.0}]}]}',
        encoding="utf-8")
    sp.lyrics_txt.write_text("bee\n", encoding="utf-8")        # word changed
    with pytest.raises(ValueError) as e:
        pipeline.run_split(sp, Config())
    assert "align" in str(e.value).lower()
    # Refusal must be before any write: no .bak should exist (data-safety property).
    assert not sp.timing_json.with_suffix(".json.bak").exists()


def test_run_split_auto_splits_wide_line(tmp_path, monkeypatch):
    from karaoke import pipeline
    from karaoke.config import Config, RenderConfig
    from karaoke.paths import SongPaths
    from karaoke.timing import Timing
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.timing_json.write_text(
        '{"lines": [{"words": [{"text": "aa", "start": 1.0, "end": 2.0},'
        '{"text": "bb", "start": 2.0, "end": 3.0},'
        '{"text": "cc", "start": 3.0, "end": 4.0},'
        '{"text": "dd", "start": 4.0, "end": 5.0}]}]}', encoding="utf-8")
    sp.lyrics_txt.write_text("aa bb cc dd\n", encoding="utf-8")
    monkeypatch.setattr("karaoke.preflight._line_measurer",
                        lambda cfg: (lambda t: 10.0 * len(t)))   # ~120px full
    cfg = Config(render=RenderConfig(width=80, usable_width_frac=1.0))  # usable 80
    pipeline.run_split(sp, cfg)
    out = Timing.from_json(sp.timing_json.read_text(encoding="utf-8"))
    assert len(out.lines) == 2 and out.lines[1].wrap is True     # wrapped, marked
