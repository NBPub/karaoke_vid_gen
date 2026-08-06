import json as _json
from click.testing import CliRunner
from karaoke import cli as cli_mod
from karaoke.paths import SongPaths


def test_cli_help_lists_commands():
    r = CliRunner().invoke(cli_mod.cli, ["--help"])
    assert r.exit_code == 0
    for cmd in ("acquire", "align", "all", "lyrics", "render", "separate"):
        assert cmd in r.output


def test_cli_align_passes_first_line(monkeypatch, tmp_path):
    seen = {}
    def fake_run_align(sp, cfg, force=False, first_line=None, model=None):
        seen["first_line"] = first_line
    monkeypatch.setattr(cli_mod.pipeline, "run_align", fake_run_align)
    r = CliRunner().invoke(cli_mod.cli, ["align", "A - B", "--first-line", "1:07",
                                         "--songs-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert seen["first_line"] == 67.0


def test_cli_all_passes_first_line(monkeypatch, tmp_path):
    from karaoke.paths import SongPaths
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.lyrics_txt.write_text("hello world", encoding="utf-8")
    seen = {}
    monkeypatch.setattr(cli_mod.pipeline, "run_acquire", lambda *a, **k: None)
    monkeypatch.setattr(cli_mod.pipeline, "run_lyrics", lambda *a, **k: None)
    monkeypatch.setattr(cli_mod.pipeline, "run_separate", lambda *a, **k: None)
    monkeypatch.setattr(cli_mod.pipeline, "run_render", lambda *a, **k: None)
    monkeypatch.setattr(cli_mod.pipeline, "resolve_song_meta", lambda sp, m: m)
    monkeypatch.setattr("click.prompt", lambda *a, **k: "")
    def fake_run_align(sp, cfg, force=False, first_line=None, model=None):
        seen["first_line"] = first_line
    monkeypatch.setattr(cli_mod.pipeline, "run_align", fake_run_align)
    r = CliRunner().invoke(cli_mod.cli, ["all", "A - B", "--first-line", "67",
                                         "--songs-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert seen["first_line"] == 67.0


def _mock_all_stages(monkeypatch, tmp_path, seen, prompts):
    from karaoke.paths import SongPaths
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.lyrics_txt.write_text("hello world", encoding="utf-8")
    monkeypatch.setattr(cli_mod.pipeline, "run_acquire",
                        lambda source, *a, **k: seen.__setitem__("source", source))
    monkeypatch.setattr(cli_mod.pipeline, "run_lyrics", lambda *a, **k: None)
    monkeypatch.setattr(cli_mod.pipeline, "run_separate", lambda *a, **k: None)
    monkeypatch.setattr(cli_mod.pipeline, "run_align", lambda *a, **k: None)
    monkeypatch.setattr(cli_mod.pipeline, "run_render",
                        lambda *a, **k: seen.__setitem__("rendered", True))
    monkeypatch.setattr(cli_mod.pipeline, "resolve_song_meta", lambda sp, m: m)
    monkeypatch.setattr("click.prompt",
                        lambda *a, **k: (prompts.append(a[0]) or "")
                        if "Audio source" not in a[0] else (prompts.append(a[0]) or "PROMPTED"))


def test_cli_all_uses_source_arg_when_given(monkeypatch, tmp_path):
    seen, prompts = {}, []
    _mock_all_stages(monkeypatch, tmp_path, seen, prompts)
    r = CliRunner().invoke(cli_mod.cli, ["all", "A - B", "https://ex/v",
                                         "--songs-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert seen["source"] == "https://ex/v"                     # arg used
    assert not any("Audio source" in p for p in prompts)        # not prompted


def test_cli_all_prompts_for_source_when_omitted(monkeypatch, tmp_path):
    seen, prompts = {}, []
    _mock_all_stages(monkeypatch, tmp_path, seen, prompts)
    r = CliRunner().invoke(cli_mod.cli, ["all", "A - B", "--songs-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert seen["source"] == "PROMPTED"                         # prompt fallback
    assert any("Audio source" in p for p in prompts)


def test_all_skips_prompts_for_cached_stages(monkeypatch, tmp_path):
    from karaoke.paths import SongPaths
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.song.write_bytes(b"x")            # acquire done
    sp.instrumental.write_bytes(b"x")    # separate done
    sp.lyrics_txt.write_text("hello world", encoding="utf-8")
    prompts = []
    monkeypatch.setattr("click.prompt", lambda *a, **k: prompts.append(a[0]) or "")
    for fn in ("run_acquire", "run_lyrics", "run_separate", "run_align", "run_render"):
        monkeypatch.setattr(cli_mod.pipeline, fn, lambda *a, **k: None)
    monkeypatch.setattr(cli_mod.pipeline, "resolve_song_meta", lambda sp, m: m)
    r = CliRunner().invoke(cli_mod.cli, ["all", "A - B", "--songs-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert prompts == []                 # no source prompt, no instrumental prompt


def test_all_prompts_when_stages_missing(monkeypatch, tmp_path):
    from karaoke.paths import SongPaths
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.lyrics_txt.write_text("hello world", encoding="utf-8")   # so no lyrics halt
    prompts = []
    monkeypatch.setattr("click.prompt", lambda *a, **k: prompts.append(a[0]) or "")
    for fn in ("run_acquire", "run_lyrics", "run_separate", "run_align", "run_render"):
        monkeypatch.setattr(cli_mod.pipeline, fn, lambda *a, **k: None)
    monkeypatch.setattr(cli_mod.pipeline, "resolve_song_meta", lambda sp, m: m)
    r = CliRunner().invoke(cli_mod.cli, ["all", "A - B", "--songs-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert any("Audio source" in p for p in prompts)
    assert any("instrumental" in p.lower() for p in prompts)


def test_all_ab_dispatches_to_run_ab_and_skips_align_render(monkeypatch, tmp_path):
    from karaoke.paths import SongPaths
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.song.write_bytes(b"x")
    sp.instrumental.write_bytes(b"x")
    sp.lyrics_txt.write_text("hello world", encoding="utf-8")
    seen = {}
    monkeypatch.setattr("click.prompt", lambda *a, **k: "")
    monkeypatch.setattr(cli_mod.pipeline, "run_acquire", lambda *a, **k: None)
    monkeypatch.setattr(cli_mod.pipeline, "run_lyrics", lambda *a, **k: None)
    monkeypatch.setattr(cli_mod.pipeline, "run_separate", lambda *a, **k: None)
    monkeypatch.setattr(cli_mod.pipeline, "resolve_song_meta", lambda sp, m: m)
    monkeypatch.setattr(cli_mod.pipeline, "run_ab",
                        lambda sp, cfg, **k: seen.setdefault("ab", k))
    monkeypatch.setattr(cli_mod.pipeline, "run_align",
                        lambda *a, **k: seen.setdefault("align", True))
    monkeypatch.setattr(cli_mod.pipeline, "run_render",
                        lambda *a, **k: seen.setdefault("render", True))
    r = CliRunner().invoke(cli_mod.cli, ["all", "A - B", "--ab", "--songs-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert "ab" in seen and "align" not in seen and "render" not in seen


def test_cli_all_renders(monkeypatch, tmp_path):
    seen, prompts = {}, []
    _mock_all_stages(monkeypatch, tmp_path, seen, prompts)
    r = CliRunner().invoke(cli_mod.cli, ["all", "A - B", "https://ex/v",
                                         "--songs-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert seen.get("rendered") is True                         # all ends in a render


def test_songs_dir_precedence(tmp_path):
    from karaoke.config import Config
    from karaoke import cli as c
    cfg = Config()  # built-in default songs_dir == "songs"
    sp = c._resolve_song_paths("A - B", str(tmp_path / "flagdir"), cfg)   # flag wins
    assert sp.root == (tmp_path / "flagdir" / "A - B")
    cfg2 = Config()
    cfg2.paths.songs_dir = str(tmp_path / "cfgdir")
    sp2 = c._resolve_song_paths("A - B", None, cfg2)                      # config used
    assert sp2.root == (tmp_path / "cfgdir" / "A - B")


def test_cwd_inference_when_artifact_present(tmp_path, monkeypatch):
    from karaoke.config import Config
    from karaoke import cli as c
    folder = tmp_path / "songs" / "Artist - Song"
    folder.mkdir(parents=True)
    (folder / "timing.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(folder)
    assert c._resolve_song_paths(None, None, Config()).root == folder


def test_cwd_inference_when_parent_is_songs_dir(tmp_path, monkeypatch):
    from karaoke.config import Config
    from karaoke import cli as c
    folder = tmp_path / "songs" / "Artist - Song"   # empty, but parent == "songs"
    folder.mkdir(parents=True)
    monkeypatch.chdir(folder)
    assert c._resolve_song_paths(None, None, Config()).root == folder


def test_cwd_inference_errors_when_not_song_folder(tmp_path, monkeypatch):
    import click
    import pytest
    from karaoke.config import Config
    from karaoke import cli as c
    plain = tmp_path / "somewhere"
    plain.mkdir()
    monkeypatch.chdir(plain)
    with pytest.raises(click.ClickException):
        c._resolve_song_paths(None, None, Config())


def test_explicit_song_overrides_cwd(tmp_path, monkeypatch):
    from karaoke.config import Config
    from karaoke import cli as c
    folder = tmp_path / "songs" / "Artist - Song"
    folder.mkdir(parents=True)
    (folder / "timing.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(folder)
    sp = c._resolve_song_paths("Other - Name", str(tmp_path / "songs"), Config())
    assert sp.root == (tmp_path / "songs" / "Other - Name")


def test_nudge_nothing_to_do_lists_all_operations(tmp_path):
    from karaoke.paths import SongPaths
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.timing_json.write_text(
        '{"lines": [{"words": [{"text": "hi", "start": 1.0, "end": 2.0}]}]}',
        encoding="utf-8")
    r = CliRunner().invoke(cli_mod.cli, ["nudge", "A - B", "--skip-check",
                                         "--songs-dir", str(tmp_path)])
    assert r.exit_code != 0
    for op in ("--shift", "--copy", "--anchor", "--fill-cleared", "--list"):
        assert op in r.output


def test_nudge_nothing_to_do_hints_fill_cleared_when_line_marked(tmp_path):
    from karaoke.paths import SongPaths
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    # A line marked for reflow: first word end == 0.
    sp.timing_json.write_text(
        '{"lines": [{"words": [{"text": "hi", "start": 1.0, "end": 0}]}]}',
        encoding="utf-8")
    r = CliRunner().invoke(cli_mod.cli, ["nudge", "A - B", "--skip-check",
                                         "--songs-dir", str(tmp_path)])
    assert r.exit_code != 0
    assert "--fill-cleared" in r.output
    assert "marked" in r.output.lower()


def test_cli_align_model_override(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(cli_mod.pipeline, "run_align",
                        lambda sp, cfg, force=False, first_line=None, model=None: seen.update(model=model))
    r = CliRunner().invoke(cli_mod.cli, ["align", "A - B", "--model", "mms",
                                         "--songs-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert seen["model"] == "mms"


def test_cli_align_bad_model_errors_with_options_and_config(tmp_path):
    r = CliRunner().invoke(cli_mod.cli, ["align", "A - B", "--model", "bogus",
                                         "--songs-dir", str(tmp_path)])
    assert r.exit_code != 0
    assert "whisper" in r.output and "mms" in r.output
    assert "config.toml" in r.output
    assert "Traceback" not in r.output
    assert "--ab" not in r.output          # align has no --ab hint


def test_cli_all_model_override(monkeypatch, tmp_path):
    from karaoke.paths import SongPaths
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.song.write_bytes(b"x")
    sp.instrumental.write_bytes(b"x")
    sp.lyrics_txt.write_text("hello world", encoding="utf-8")
    seen = {}
    monkeypatch.setattr("click.prompt", lambda *a, **k: "")
    for fn in ("run_acquire", "run_lyrics", "run_separate", "run_render"):
        monkeypatch.setattr(cli_mod.pipeline, fn, lambda *a, **k: None)
    monkeypatch.setattr(cli_mod.pipeline, "resolve_song_meta", lambda sp, m: m)
    monkeypatch.setattr(cli_mod.pipeline, "run_align",
                        lambda sp, cfg, force=False, first_line=None, model=None: seen.update(model=model))
    r = CliRunner().invoke(cli_mod.cli, ["all", "A - B", "--model", "mms",
                                         "--songs-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert seen["model"] == "mms"


def test_cli_all_bad_model_hints_ab(tmp_path):
    r = CliRunner().invoke(cli_mod.cli, ["all", "A - B", "--model", "bogus",
                                         "--songs-dir", str(tmp_path)])
    assert r.exit_code != 0
    assert "whisper" in r.output and "mms" in r.output and "config.toml" in r.output
    assert "--ab" in r.output              # all mentions the --ab alternative


def test_cli_all_model_and_ab_mutually_exclusive(tmp_path):
    r = CliRunner().invoke(cli_mod.cli, ["all", "A - B", "--model", "mms", "--ab",
                                         "--songs-dir", str(tmp_path)])
    assert r.exit_code != 0
    assert "one or the other" in r.output.lower()


def test_populating_command_announces_song_folder(monkeypatch, tmp_path):
    from karaoke.paths import SongPaths
    SongPaths.for_song(tmp_path, "A - B").ensure()
    monkeypatch.setattr(cli_mod.pipeline, "run_align", lambda *a, **k: None)
    r = CliRunner().invoke(cli_mod.cli, ["align", "A - B", "--songs-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert "[song]" in r.output
    assert str((tmp_path / "A - B").resolve()) in r.output


def test_editinplace_command_does_not_announce_song_folder(tmp_path):
    from karaoke.paths import SongPaths
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.timing_json.write_text(
        '{"lines": [{"words": [{"text": "hi", "start": 0.0, "end": 1.0}]}]}',
        encoding="utf-8")
    r = CliRunner().invoke(cli_mod.cli, ["nudge", "A - B", "--list",
                                         "--songs-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert "[song]" not in r.output


def _mock_render_with_stale_nx(monkeypatch, tmp_path, seen, interactive=True):
    from karaoke.paths import SongPaths
    from karaoke.preflight import Finding, WARNING
    SongPaths.for_song(tmp_path, "A - B").ensure()
    monkeypatch.setattr("karaoke.preflight.run_preflight",
                        lambda sp, cfg, *, context: [Finding(
                            WARNING, "stale_no_extract", "stale nx", prompt=True)])
    monkeypatch.setattr(cli_mod, "_interactive", lambda: interactive)
    monkeypatch.setattr(cli_mod.pipeline, "run_separate",
                        lambda *a, **k: seen.__setitem__("separated", k))
    monkeypatch.setattr(cli_mod.pipeline, "run_render",
                        lambda *a, **k: seen.__setitem__("rendered", True))


def test_render_reseparates_on_stale_no_extract(monkeypatch, tmp_path):
    seen = {}
    _mock_render_with_stale_nx(monkeypatch, tmp_path, seen)
    r = CliRunner().invoke(cli_mod.cli, ["render", "A - B", "--songs-dir", str(tmp_path)],
                           input="y\n")
    assert r.exit_code == 0, r.output
    assert seen.get("separated", {}).get("force") is True   # separate --force ran
    assert seen.get("rendered") is True


def test_render_stale_no_extract_render_anyway(monkeypatch, tmp_path):
    seen = {}
    _mock_render_with_stale_nx(monkeypatch, tmp_path, seen)
    r = CliRunner().invoke(cli_mod.cli, ["render", "A - B", "--songs-dir", str(tmp_path)],
                           input="n\ny\n")               # no separate, yes render anyway
    assert r.exit_code == 0, r.output
    assert "separated" not in seen
    assert seen.get("rendered") is True


def test_render_stale_no_extract_abort(monkeypatch, tmp_path):
    seen = {}
    _mock_render_with_stale_nx(monkeypatch, tmp_path, seen)
    r = CliRunner().invoke(cli_mod.cli, ["render", "A - B", "--songs-dir", str(tmp_path)],
                           input="n\nn\n")               # no separate, no render -> abort
    assert r.exit_code != 0
    assert "separated" not in seen and "rendered" not in seen


def test_render_no_prompt_when_noninteractive(monkeypatch, tmp_path):
    seen = {}
    _mock_render_with_stale_nx(monkeypatch, tmp_path, seen, interactive=False)
    r = CliRunner().invoke(cli_mod.cli, ["render", "A - B", "--songs-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert "separated" not in seen and seen.get("rendered") is True


def test_cli_acquire_invokes_pipeline(monkeypatch, tmp_path):
    seen = {}
    def fake_run_acquire(source, sp, cfg, force):
        seen["source"] = source
        seen["root"] = sp.root.name
        seen["force"] = force
    monkeypatch.setattr(cli_mod.pipeline, "run_acquire", fake_run_acquire)
    r = CliRunner().invoke(
        cli_mod.cli,
        ["acquire", "Artist - Title", "http://example.com/a", "--songs-dir", str(tmp_path)],
    )
    assert r.exit_code == 0, r.output
    assert seen["source"] == "http://example.com/a"
    assert seen["root"] == "Artist - Title"
    assert seen["force"] is False


def _marked_song(tmp_path):
    from karaoke.paths import SongPaths
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    # line 0 marked (first word end=0), line 1 a normal following line
    sp.timing_json.write_text(
        '{"lines":[{"words":[{"text":"x","start":5.0,"end":0.0}]},'
        '{"words":[{"text":"z","start":13.0,"end":14.0}]}]}', encoding="utf-8")
    sp.vocals.write_bytes(b"x")
    return sp


def test_nudge_interpolate_flag_skips_forced(monkeypatch, tmp_path):
    import karaoke.nudge as nudge_mod
    _marked_song(tmp_path)
    captured = {}
    monkeypatch.setattr(nudge_mod, "reflow_marked",
                        lambda timing, anchors, **kw: captured.update(kw) or timing)
    r = CliRunner().invoke(cli_mod.cli, ["nudge", "A - B", "--fill-cleared",
                                         "--interpolate", "--no-snap",
                                         "--songs-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert captured["forced"] is None


def test_nudge_post_check_reports_reflow_overlap(monkeypatch, tmp_path):
    """Wiring: a reflow that pushes line 0's end past line 1's start is reported
    by the post-nudge check (non-halting), even though the pre-op gate passed."""
    import karaoke.nudge as nudge_mod
    from karaoke.timing import Timing, Line, Word
    _marked_song(tmp_path)
    overlapped = Timing(lines=[
        Line(words=[Word("x", 5.0, 14.0)]),      # reflowed end 14.0 ...
        Line(words=[Word("z", 13.0, 15.0)]),     # ... past line 1 start 13.0
    ])
    monkeypatch.setattr(nudge_mod, "reflow_marked",
                        lambda timing, anchors, **kw: overlapped)
    r = CliRunner().invoke(cli_mod.cli, ["nudge", "A - B", "--fill-cleared",
                                         "--interpolate", "--no-snap",
                                         "--songs-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output            # reports, does not halt
    assert "post-nudge" in r.output.lower()
    assert "out_of_order" in r.output


def test_preflight_gate_suppresses_stale_render_on_force(tmp_path, capsys):
    """`render --force` shouldn't print the stale_render warning — the forced
    re-render is exactly its fix."""
    import os, time
    from karaoke.paths import SongPaths
    from karaoke.config import Config
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.review_mp4.write_text("x", encoding="utf-8")
    old = time.time() - 100
    os.utime(sp.review_mp4, (old, old))               # video older than timing
    sp.timing_json.write_text(
        '{"lines":[{"words":[{"text":"a","start":1.0,"end":2.0}]}]}', encoding="utf-8")
    cli_mod._preflight_gate(sp, Config(), "render", skip=False, force=False)
    assert "stale_render" in capsys.readouterr().out    # shown without --force
    cli_mod._preflight_gate(sp, Config(), "render", skip=False, force=True)
    assert "stale_render" not in capsys.readouterr().out   # suppressed with --force


def test_post_nudge_report_clean_when_no_issues(tmp_path, capsys):
    from karaoke.paths import SongPaths
    from karaoke.config import Config
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.timing_json.write_text(_json.dumps({"lines": [
        {"words": [{"text": "a", "start": 1.0, "end": 2.0}]},
        {"words": [{"text": "b", "start": 2.0, "end": 3.0}]}]}), encoding="utf-8")
    cli_mod._post_nudge_report(sp, Config())
    out = capsys.readouterr().out
    assert "no new issues" in out.lower()


def test_post_nudge_report_ignores_stale_render(tmp_path, capsys):
    """A timing write always makes the old video stale — that's expected, so the
    post-nudge report must not surface stale_render as an issue."""
    import os, time
    from karaoke.paths import SongPaths
    from karaoke.config import Config
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.review_mp4.write_text("x", encoding="utf-8")
    old = time.time() - 100
    os.utime(sp.review_mp4, (old, old))          # video older than the timing
    sp.timing_json.write_text(_json.dumps({"lines": [
        {"words": [{"text": "a", "start": 1.0, "end": 2.0}]}]}), encoding="utf-8")
    cli_mod._post_nudge_report(sp, Config())
    out = capsys.readouterr().out
    assert "stale_render" not in out
    assert "no new issues" in out.lower()


def test_cli_render_passes_mode(monkeypatch, tmp_path):
    seen = {}

    def fake_run_render(sp, cfg, force=False, full=False, tail=None, mode=None,
                        confirm_full_outro=None):
        seen["mode"] = mode
        seen["full"] = full

    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.timing_json.write_text(
        _json.dumps({"lines": [{"words": [{"text": "x", "start": 1.0, "end": 2.0}]}]}),
        encoding="utf-8")
    monkeypatch.setattr(cli_mod.pipeline, "run_render", fake_run_render)
    r = CliRunner().invoke(cli_mod.cli, ["render", "A - B", "--mode", "review",
                                         "--full", "--songs-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert seen["mode"] == "review"


def test_cli_render_default_mode_none(monkeypatch, tmp_path):
    seen = {}
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.timing_json.write_text(
        _json.dumps({"lines": [{"words": [{"text": "x", "start": 1.0, "end": 2.0}]}]}),
        encoding="utf-8")
    monkeypatch.setattr(cli_mod.pipeline, "run_render",
                        lambda sp, cfg, **kw: seen.update(kw))
    r = CliRunner().invoke(cli_mod.cli, ["render", "A - B", "--songs-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert seen["mode"] is None   # resolves from config inside run_render


def test_nudge_default_builds_forced(monkeypatch, tmp_path):
    import karaoke.nudge as nudge_mod
    _marked_song(tmp_path)
    captured = {}
    monkeypatch.setattr(cli_mod, "_load_forced", lambda sp, cfg: ("FORCED", "SAMP", 44100))
    monkeypatch.setattr(nudge_mod, "reflow_marked",
                        lambda timing, anchors, **kw: captured.update(kw) or timing)
    r = CliRunner().invoke(cli_mod.cli, ["nudge", "A - B", "--fill-cleared",
                                         "--songs-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert captured["forced"] == "FORCED"
    assert captured["samples"] == "SAMP" and captured["sr"] == 44100


def test_cli_check_clean_exits_zero(tmp_path):
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.timing_json.write_text(_json.dumps({"lines": [
        {"words": [{"text": "hi", "start": 1.0, "end": 2.0}]}]}), encoding="utf-8")
    sp.lyrics_txt.write_text("hi\n", encoding="utf-8")
    r = CliRunner().invoke(cli_mod.cli, ["check", "A - B", "--songs-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert "no problems" in r.output.lower()


def test_cli_check_errors_exit_one(tmp_path):
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.timing_json.write_text('{\n  "start": 0\n  "end": 5\n}\n', encoding="utf-8")
    r = CliRunner().invoke(cli_mod.cli, ["check", "A - B", "--songs-dir", str(tmp_path)])
    assert r.exit_code == 1
    assert "missing_comma" in r.output


def test_nudge_halts_on_broken_timing(tmp_path):
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.timing_json.write_text('{\n  "start": 0\n  "end": 5\n}\n', encoding="utf-8")
    r = CliRunner().invoke(cli_mod.cli, ["nudge", "A - B", "--fill-cleared",
                                         "--songs-dir", str(tmp_path)])
    assert r.exit_code != 0
    assert "missing_comma" in r.output


def test_skip_check_bypasses_gate_on_nudge(tmp_path, monkeypatch):
    # broken JSON, but --skip-check should bypass preflight and reach the
    # command body (which then fails its own way, not via the preflight report)
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.timing_json.write_text('{\n  "start": 0\n  "end": 5\n}\n', encoding="utf-8")
    r = CliRunner().invoke(cli_mod.cli, ["nudge", "A - B", "--fill-cleared",
                                         "--skip-check", "--songs-dir", str(tmp_path)])
    assert "missing_comma" not in r.output  # the preflight report did NOT run


def test_render_proceeds_on_warnings(tmp_path, monkeypatch):
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.timing_json.write_text(_json.dumps({"lines": [
        {"words": [{"text": "ship", "start": 1.0, "end": 2.0}]}]}), encoding="utf-8")
    sp.lyrics_txt.write_text("shit\n", encoding="utf-8")  # text mismatch = warning
    called = {}
    monkeypatch.setattr(cli_mod.pipeline, "run_render",
                        lambda *a, **k: called.setdefault("ran", True))
    r = CliRunner().invoke(cli_mod.cli, ["render", "A - B", "--songs-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert called.get("ran") is True            # warning did not block
    assert "lyrics_text_mismatch" in r.output   # but was reported


def _two_line_song(tmp_path):
    """A song fixture with two normal (non-marked) timing lines."""
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.timing_json.write_text(
        '{"lines":['
        '{"words":[{"text":"hello","start":1.0,"end":2.0}]},'
        '{"words":[{"text":"world","start":5.0,"end":6.0}]}'
        ']}',
        encoding="utf-8")
    sp.vocals.write_bytes(b"x")
    return sp


def test_nudge_anchor_logs_history_row(monkeypatch, tmp_path):
    """--anchor branch must append a nudge row to history.csv."""
    import csv
    import karaoke.nudge as nudge_mod
    sp = _two_line_song(tmp_path)

    monkeypatch.setattr(cli_mod, "_load_forced", lambda sp, cfg: (None, None, None))
    monkeypatch.setattr(nudge_mod, "reflow_anchors",
                        lambda timing, parsed, **kw: timing)

    r = CliRunner().invoke(
        cli_mod.cli,
        ["nudge", "A - B", "--anchor", "0=1.0", "--anchor", "1=5.0",
         "--no-snap", "--songs-dir", str(tmp_path)],
    )
    assert r.exit_code == 0, r.output

    assert sp.history_csv.exists(), "history.csv was not created"
    rows = list(csv.DictReader(sp.history_csv.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["op"] == "nudge"
    assert "anchor" in rows[0]["notes"]


def test_nudge_shift_logs_history_row(monkeypatch, tmp_path):
    """--shift branch must append a nudge row to history.csv."""
    import csv
    import karaoke.nudge as nudge_mod
    sp = _two_line_song(tmp_path)

    monkeypatch.setattr(nudge_mod, "apply_edits",
                        lambda timing, vocals, edits, **kw: timing)

    r = CliRunner().invoke(
        cli_mod.cli,
        ["nudge", "A - B", "--shift", "0=1.0", "--no-snap",
         "--songs-dir", str(tmp_path)],
    )
    assert r.exit_code == 0, r.output

    assert sp.history_csv.exists(), "history.csv was not created"
    rows = list(csv.DictReader(sp.history_csv.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["op"] == "nudge"
    assert "shift" in rows[0]["notes"]


def test_cli_split_invokes_run_split(monkeypatch, tmp_path):
    from click.testing import CliRunner
    import karaoke.cli as cli_mod
    from karaoke.paths import SongPaths
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.timing_json.write_text('{"lines": []}', encoding="utf-8")
    seen = {}
    monkeypatch.setattr(cli_mod.pipeline, "run_split",
                        lambda sp, cfg, force=False: seen.setdefault("ran", True))
    r = CliRunner().invoke(cli_mod.cli, ["split", "A - B", "--songs-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert seen.get("ran") is True
