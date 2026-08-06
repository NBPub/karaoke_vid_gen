from pathlib import Path

import pytest
from click.testing import CliRunner

from karaoke import cli as cli_mod
from karaoke import pipeline
from karaoke.config import Config
from karaoke.paths import SongPaths


def _cfg():
    return Config.load(Path("missing.toml"))


def _song(tmp_path):
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.vocals.write_bytes(b"x")
    sp.song.write_bytes(b"x")
    sp.lyrics_txt.write_text("hello world\n", encoding="utf-8")
    return sp


# --- run_ab (generate) -----------------------------------------------------

def test_run_ab_writes_labeled_and_never_touches_canonical(tmp_path, monkeypatch):
    sp = _song(tmp_path)
    monkeypatch.setattr(pipeline, "_build_aligner", lambda model, cfg: ("ALIGNER", model))
    written = []

    def fake_align(vocals, lyrics, out, aligner, **kw):
        out.write_text('{"lines": []}', encoding="utf-8")
        written.append((aligner[1], out.name))

    monkeypatch.setattr(pipeline.align_mod, "align_song", fake_align)
    renders = []
    monkeypatch.setattr(pipeline, "run_render", lambda sp, cfg, **kw: renders.append(kw))

    pipeline.run_ab(sp, _cfg())

    assert sp.ab_timing("whisper").exists() and sp.ab_timing("mms").exists()
    # canonical files are never created by generate
    assert not sp.timing_json.exists()
    assert not sp.timing_baseline.exists()
    assert not sp.review_mp4.exists() and not sp.output_mp4.exists()
    # both aligners forced, each aligned to its labeled path
    assert {w[0] for w in written} == {"whisper", "mms"}
    # rendered both, to labeled review targets via timing_path
    assert len(renders) == 2
    for kw in renders:
        assert kw["timing_path"] in (sp.ab_timing("whisper"), sp.ab_timing("mms"))
        assert kw["targets"][0][1] in (sp.ab_review("whisper"), sp.ab_review("mms"))


def test_run_ab_preserves_pre_existing_canonical(tmp_path, monkeypatch):
    sp = _song(tmp_path)
    sp.timing_json.write_text("CANON", encoding="utf-8")
    sp.timing_baseline.write_text("CANONBASE", encoding="utf-8")
    sp.review_mp4.write_bytes(b"CANONVIDEO")
    monkeypatch.setattr(pipeline, "_build_aligner", lambda model, cfg: None)
    monkeypatch.setattr(pipeline.align_mod, "align_song",
                        lambda v, l, out, a, **kw: out.write_text("{}", encoding="utf-8"))
    monkeypatch.setattr(pipeline, "run_render", lambda sp, cfg, **kw: None)

    pipeline.run_ab(sp, _cfg())

    assert sp.timing_json.read_text(encoding="utf-8") == "CANON"
    assert sp.timing_baseline.read_text(encoding="utf-8") == "CANONBASE"
    assert sp.review_mp4.read_bytes() == b"CANONVIDEO"


def test_run_ab_no_render_skips_render(tmp_path, monkeypatch):
    sp = _song(tmp_path)
    monkeypatch.setattr(pipeline, "_build_aligner", lambda model, cfg: None)
    monkeypatch.setattr(pipeline.align_mod, "align_song",
                        lambda v, l, out, a, **kw: out.write_text("{}", encoding="utf-8"))
    called = []
    monkeypatch.setattr(pipeline, "run_render", lambda sp, cfg, **kw: called.append(kw))

    pipeline.run_ab(sp, _cfg(), render=False)
    assert called == []


def test_run_ab_passes_first_line_to_both(tmp_path, monkeypatch):
    sp = _song(tmp_path)
    monkeypatch.setattr(pipeline, "_build_aligner", lambda model, cfg: None)
    seen = []

    def fake_align(v, l, out, a, **kw):
        seen.append(kw.get("first_line_seconds"))
        out.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(pipeline.align_mod, "align_song", fake_align)
    monkeypatch.setattr(pipeline, "run_render", lambda sp, cfg, **kw: None)

    pipeline.run_ab(sp, _cfg(), first_line=20.5, render=False)
    assert seen == [20.5, 20.5]


def test_ab_render_targets_by_mode(tmp_path):
    sp = SongPaths.for_song(tmp_path, "A - B")
    assert pipeline.ab_render_targets(sp, "mms", "review") == [(sp.song, sp.ab_review("mms"))]
    assert pipeline.ab_render_targets(sp, "mms", "karaoke") == [(sp.instrumental, sp.ab_output("mms"))]
    assert pipeline.ab_render_targets(sp, "mms", "both") == [
        (sp.instrumental, sp.ab_output("mms")),
        (sp.song, sp.ab_review("mms")),
    ]


def test_run_ab_both_mode_renders_labeled_karaoke_and_review(tmp_path, monkeypatch):
    sp = _song(tmp_path)
    p = tmp_path / "config.toml"
    p.write_text("[render]\nmode = \"both\"\n", encoding="utf-8")
    cfg = Config.load(p)
    monkeypatch.setattr(pipeline, "_build_aligner", lambda model, cfg: None)
    monkeypatch.setattr(pipeline.align_mod, "align_song",
                        lambda v, l, out, a, **kw: out.write_text("{}", encoding="utf-8"))
    renders = []
    monkeypatch.setattr(pipeline, "run_render", lambda sp, cfg, **kw: renders.append(kw))

    pipeline.run_ab(sp, cfg)

    assert len(renders) == 2                      # one render call per model
    for kw in renders:
        outs = {out.name for _, out in kw["targets"]}
        assert any(n.startswith("karaoke.") and n.endswith(".mp4")
                   and ".review." not in n for n in outs)      # labeled instrumental
        assert any(".review." in n for n in outs)              # labeled review


def _mark_history(sp, *ops):
    sp.history_csv.write_text(
        "op,model\n" + "\n".join(f"{op},{model}" for op, model in ops) + "\n",
        encoding="utf-8")


# Valid timing whose words ("hello world") match the `_song` fixture's lyrics.txt.
_HELLO_WORLD_TIMING = ('{"lines": [{"words": ['
                       '{"text": "hello", "start": 0.0, "end": 1.0}, '
                       '{"text": "world", "start": 1.0, "end": 2.0}]}]}')


def test_reusable_model_pristine_align_with_baseline_match(tmp_path):
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.timing_json.write_text("TIMING", encoding="utf-8")
    sp.timing_baseline.write_text("TIMING", encoding="utf-8")
    _mark_history(sp, ("align", "whisper"), ("render", "whisper"))
    assert pipeline._reusable_model(sp) == "whisper"


def test_reusable_model_baseline_mismatch_blocks(tmp_path):
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.timing_json.write_text("EDITED", encoding="utf-8")      # raw hand-edit
    sp.timing_baseline.write_text("TIMING", encoding="utf-8")
    _mark_history(sp, ("align", "whisper"))
    assert pipeline._reusable_model(sp) is None


def test_reusable_model_nudge_after_align_blocks(tmp_path):
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.timing_json.write_text("TIMING", encoding="utf-8")
    sp.timing_baseline.write_text("TIMING", encoding="utf-8")
    _mark_history(sp, ("align", "whisper"), ("nudge", "whisper"))
    assert pipeline._reusable_model(sp) is None


def test_reusable_model_no_history_blocks(tmp_path):
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.timing_json.write_text("TIMING", encoding="utf-8")
    sp.timing_baseline.write_text("TIMING", encoding="utf-8")
    assert pipeline._reusable_model(sp) is None


def test_run_ab_reuses_pristine_whisper_arm(tmp_path, monkeypatch):
    sp = _song(tmp_path)                                     # lyrics.txt = "hello world"
    sp.timing_json.write_text(_HELLO_WORLD_TIMING, encoding="utf-8")
    sp.timing_baseline.write_text(_HELLO_WORLD_TIMING, encoding="utf-8")
    _mark_history(sp, ("align", "whisper"))
    aligned = []
    monkeypatch.setattr(pipeline, "_build_aligner", lambda model, cfg: None)

    def fake_align(v, l, out, a, **kw):
        aligned.append(out.name)
        out.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(pipeline.align_mod, "align_song", fake_align)
    monkeypatch.setattr(pipeline, "run_render", lambda sp, cfg, **kw: None)
    monkeypatch.setattr(pipeline, "_reuse_initial_render", lambda sp, cfg, m: False)

    pipeline.run_ab(sp, _cfg())

    assert sp.ab_timing("whisper").read_text(encoding="utf-8") == _HELLO_WORLD_TIMING  # copied
    assert aligned == [sp.ab_timing("mms").name]            # only mms re-aligned
    assert sp.timing_json.read_text(encoding="utf-8") == _HELLO_WORLD_TIMING  # canonical untouched


def test_timing_matches_lyrics_true_and_false(tmp_path):
    sp = _song(tmp_path)                                     # lyrics.txt = "hello world"
    sp.timing_json.write_text(_HELLO_WORLD_TIMING, encoding="utf-8")
    assert pipeline._timing_matches_lyrics(sp) is True
    sp.lyrics_txt.write_text("hello brave world\n", encoding="utf-8")   # word added
    assert pipeline._timing_matches_lyrics(sp) is False


def test_run_ab_skips_reuse_when_lyrics_edited(tmp_path, monkeypatch, capsys):
    sp = _song(tmp_path)
    sp.timing_json.write_text(_HELLO_WORLD_TIMING, encoding="utf-8")
    sp.timing_baseline.write_text(_HELLO_WORLD_TIMING, encoding="utf-8")
    _mark_history(sp, ("align", "whisper"))
    sp.lyrics_txt.write_text("hello brave world\n", encoding="utf-8")   # edited after align
    aligned = []
    monkeypatch.setattr(pipeline, "_build_aligner", lambda model, cfg: None)
    monkeypatch.setattr(pipeline.align_mod, "align_song",
                        lambda v, l, out, a, **kw: (aligned.append(out.name),
                                                    out.write_text("{}", encoding="utf-8")))
    monkeypatch.setattr(pipeline, "run_render", lambda sp, cfg, **kw: None)

    pipeline.run_ab(sp, _cfg())

    # reuse skipped -> both aligners re-run against the edited lyrics
    assert set(aligned) == {sp.ab_timing("whisper").name, sp.ab_timing("mms").name}
    assert "lyrics.txt no longer matches" in capsys.readouterr().out


def test_run_ab_force_bypasses_reuse(tmp_path, monkeypatch):
    sp = _song(tmp_path)
    sp.timing_json.write_text("PRISTINE", encoding="utf-8")
    sp.timing_baseline.write_text("PRISTINE", encoding="utf-8")
    _mark_history(sp, ("align", "whisper"))
    aligned = []
    monkeypatch.setattr(pipeline, "_build_aligner", lambda model, cfg: None)
    monkeypatch.setattr(pipeline.align_mod, "align_song",
                        lambda v, l, out, a, **kw: (aligned.append(out.name),
                                                    out.write_text("{}", encoding="utf-8")))
    monkeypatch.setattr(pipeline, "run_render", lambda sp, cfg, **kw: None)

    pipeline.run_ab(sp, _cfg(), force=True)

    assert set(aligned) == {sp.ab_timing("whisper").name, sp.ab_timing("mms").name}  # both


def test_reuse_initial_render_full_copies_review(tmp_path, monkeypatch):
    sp = _song(tmp_path)
    sp.timing_json.write_text(
        '{"lines": [{"words": [{"text": "hi", "start": 1.0, "end": 5.0}]}]}',
        encoding="utf-8")
    sp.review_mp4.write_bytes(b"REVIEW")
    monkeypatch.setattr("karaoke.render.encode.audio_duration", lambda p: 10.0)  # gap 5 <= 60
    assert pipeline._reuse_initial_render(sp, _cfg(), "whisper") is True
    assert sp.ab_review("whisper").read_bytes() == b"REVIEW"


def test_reuse_initial_render_long_outro_declines(tmp_path, monkeypatch):
    sp = _song(tmp_path)
    sp.timing_json.write_text(
        '{"lines": [{"words": [{"text": "hi", "start": 1.0, "end": 5.0}]}]}',
        encoding="utf-8")
    sp.review_mp4.write_bytes(b"REVIEW")
    monkeypatch.setattr("karaoke.render.encode.audio_duration", lambda p: 200.0)  # gap 195 > 60
    assert pipeline._reuse_initial_render(sp, _cfg(), "whisper") is False
    assert not sp.ab_review("whisper").exists()


# --- ab_keep (consolidate) -------------------------------------------------

def test_ab_keep_promotes_and_cleans(tmp_path):
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.ab_timing("whisper").write_text("HYB", encoding="utf-8")
    sp.ab_timing("mms").write_text("MMS", encoding="utf-8")
    sp.ab_review("whisper").write_bytes(b"HV")
    sp.ab_review("mms").write_bytes(b"MV")

    pipeline.ab_keep(sp, "whisper")

    assert sp.timing_json.read_text(encoding="utf-8") == "HYB"
    assert sp.timing_baseline.read_text(encoding="utf-8") == "HYB"
    assert sp.review_mp4.read_bytes() == b"HV"
    assert not sp.ab_timing("whisper").exists() and not sp.ab_timing("mms").exists()
    assert not sp.ab_review("whisper").exists() and not sp.ab_review("mms").exists()


def test_ab_keep_promotes_karaoke_output_and_removes_loser_labeled(tmp_path):
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.ab_timing("mms").write_text("MMS", encoding="utf-8")
    sp.ab_output("mms").write_bytes(b"MK")       # labeled instrumental (karaoke mode)
    sp.ab_review("mms").write_bytes(b"MV")
    sp.ab_timing("whisper").write_text("HYB", encoding="utf-8")
    sp.ab_output("whisper").write_bytes(b"HK")
    sp.ab_review("whisper").write_bytes(b"HV")

    pipeline.ab_keep(sp, "mms")

    assert sp.output_mp4.read_bytes() == b"MK"   # karaoke.mp4 promoted
    assert sp.review_mp4.read_bytes() == b"MV"   # karaoke.review.mp4 promoted
    assert sp.timing_json.read_text(encoding="utf-8") == "MMS"
    # loser's labeled files all gone
    assert not sp.ab_output("whisper").exists()
    assert not sp.ab_review("whisper").exists()
    assert not sp.ab_timing("whisper").exists()
    # kept model's labeled files consumed
    assert not sp.ab_output("mms").exists() and not sp.ab_review("mms").exists()


def test_ab_keep_overwrites_existing_canonical(tmp_path):
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.timing_json.write_text("OLD", encoding="utf-8")
    sp.review_mp4.write_bytes(b"OLDV")
    sp.ab_timing("mms").write_text("MMS", encoding="utf-8")
    sp.ab_review("mms").write_bytes(b"MV")

    pipeline.ab_keep(sp, "mms")

    assert sp.timing_json.read_text(encoding="utf-8") == "MMS"
    assert sp.review_mp4.read_bytes() == b"MV"


def test_ab_keep_missing_files_raises_friendly(tmp_path):
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    with pytest.raises(FileNotFoundError) as e:
        pipeline.ab_keep(sp, "mms")
    msg = str(e.value)
    assert "timing.mms.json" in msg and "ab" in msg.lower()


def test_ab_keep_invalid_model_raises(tmp_path):
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    with pytest.raises(ValueError):
        pipeline.ab_keep(sp, "bogus")


# --- CLI wiring ------------------------------------------------------------

def test_cli_ab_generate_invokes_run_ab(tmp_path, monkeypatch):
    SongPaths.for_song(tmp_path, "A - B").ensure()
    seen = {}
    monkeypatch.setattr(cli_mod.pipeline, "run_ab", lambda sp, cfg, **kw: seen.update(kw))
    r = CliRunner().invoke(cli_mod.cli, ["ab", "A - B", "--songs-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert seen.get("render") is True and seen.get("first_line") is None


def test_cli_ab_no_render_and_first_line(tmp_path, monkeypatch):
    SongPaths.for_song(tmp_path, "A - B").ensure()
    seen = {}
    monkeypatch.setattr(cli_mod.pipeline, "run_ab", lambda sp, cfg, **kw: seen.update(kw))
    r = CliRunner().invoke(cli_mod.cli, ["ab", "A - B", "--no-render", "--first-line",
                                         "20.5", "--songs-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert seen.get("render") is False and seen.get("first_line") == 20.5


def test_cli_ab_keep_invokes_ab_keep(tmp_path, monkeypatch):
    SongPaths.for_song(tmp_path, "A - B").ensure()
    seen = {}
    monkeypatch.setattr(cli_mod.pipeline, "ab_keep", lambda sp, model, cfg=None: seen.update(model=model))
    r = CliRunner().invoke(cli_mod.cli, ["ab", "A - B", "--keep", "whisper",
                                         "--songs-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert seen["model"] == "whisper"


def test_cli_ab_keep_missing_is_friendly_not_traceback(tmp_path):
    SongPaths.for_song(tmp_path, "A - B").ensure()
    r = CliRunner().invoke(cli_mod.cli, ["ab", "A - B", "--keep", "mms",
                                         "--songs-dir", str(tmp_path)])
    assert r.exit_code != 0
    assert "timing.mms.json" in r.output
    assert "Traceback" not in r.output
