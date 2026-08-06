import csv
from pathlib import Path
from karaoke import pipeline
from karaoke.config import Config
from karaoke.paths import SongPaths


def _cfg():
    return Config.load(Path("missing.toml"))


def _rows(sp):
    if not sp.history_csv.exists():
        return []
    return list(csv.DictReader(sp.history_csv.open(encoding="utf-8")))


def _song(tmp_path):
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.vocals.write_bytes(b"x")
    sp.lyrics_txt.write_text("hi\n", encoding="utf-8")
    return sp


def test_align_logs_row(tmp_path, monkeypatch):
    sp = _song(tmp_path)
    monkeypatch.setattr(pipeline.align_mod, "align_song",
                        lambda *a, **k: sp.timing_json.write_text('{"lines": []}', encoding="utf-8"))
    pipeline.run_align(sp, _cfg(), first_line=20.5)
    rows = _rows(sp)
    assert len(rows) == 1 and rows[0]["op"] == "align"
    assert rows[0]["model"] == "whisper" and rows[0]["seed"] == "20.5"
    assert rows[0]["source"] == "align-seeded"


def test_align_skipped_logs_nothing(tmp_path, monkeypatch):
    sp = _song(tmp_path)
    sp.timing_json.write_text('{"lines": []}', encoding="utf-8")  # already exists -> [skip]
    monkeypatch.setattr(pipeline.align_mod, "align_song",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not run")))
    pipeline.run_align(sp, _cfg(), force=False)
    assert _rows(sp) == []


def test_nudge_row_copies_provenance(tmp_path):
    from karaoke import history
    sp = _song(tmp_path)
    sp.timing_json.write_text('{"lines": []}', encoding="utf-8")
    history.append_row(sp, _cfg(), "align", duration_s=1, model="mms", source="ab-keep")
    # simulate the nudge logging call the CLI will make
    prov = history.current_provenance(sp)
    history.append_row(sp, _cfg(), "nudge", duration_s=5, notes="reflowed 2 lines", **prov)
    last = _rows(sp)[-1]
    assert last["op"] == "nudge" and last["model"] == "mms" and last["notes"] == "reflowed 2 lines"


def test_run_ab_logs_no_op_row_itself(tmp_path, monkeypatch):
    """run_ab no longer writes a separate ab-gen op row; history lives in the
    render rows. With rendering disabled it logs nothing of its own."""
    sp = _song(tmp_path)
    monkeypatch.setattr(pipeline, "_build_aligner", lambda model, cfg: None)

    def fake_align(vocals, lyrics, out, aligner, **kw):
        out.write_text('{"lines": []}', encoding="utf-8")

    monkeypatch.setattr(pipeline.align_mod, "align_song", fake_align)
    monkeypatch.setattr(pipeline, "run_render", lambda sp, cfg, **kw: None)

    pipeline.run_ab(sp, _cfg(), render=False, force=False)

    assert _rows(sp) == [], "run_ab wrote its own row; logging should be in render rows"


def test_run_ab_render_rows_reflect_each_model(tmp_path, monkeypatch):
    """Each A/B render gets its own render row tagged 'ab-gen', with the model
    column distinguishing whisper from mms — no separate ab-gen op row."""
    sp = _song(tmp_path)
    monkeypatch.setattr(pipeline, "_build_aligner", lambda model, cfg: None)

    def fake_align(vocals, lyrics, out, aligner, **kw):
        out.write_text('{"lines": []}', encoding="utf-8")

    monkeypatch.setattr(pipeline.align_mod, "align_song", fake_align)
    calls = []
    monkeypatch.setattr(pipeline, "run_render",
                        lambda sp, cfg, **kw: calls.append(kw))

    pipeline.run_ab(sp, _cfg(), first_line=24.0, render=True, force=False)

    assert all(r["op"] != "ab-gen" for r in _rows(sp))   # no separate op row
    extras = [c["history_extra"] for c in calls]
    assert {e["model"] for e in extras} == {"whisper", "mms"}
    assert all(e["notes"] == "ab-gen" for e in extras)
    assert all(e["seed"] == "24.0" and e["source"] == "ab-seeded" for e in extras)
    whisper = next(e for e in extras if e["model"] == "whisper")
    mms = next(e for e in extras if e["model"] == "mms")
    assert whisper["whisper_params"] and mms["whisper_params"] == ""


def test_render_logs_self_describing_row(tmp_path, monkeypatch):
    sp = _song(tmp_path)
    sp.timing_json.write_text(
        '{"lines": [{"words": [{"text": "hi", "start": 1.0, "end": 2.0}]}]}',
        encoding="utf-8")
    sp.instrumental.write_bytes(b"x"); sp.song.write_bytes(b"x")
    from karaoke import history
    history.append_row(sp, _cfg(), "align", duration_s=1, model="mms", source="ab-keep")

    # stub the renderer + duration source so no real encode runs
    class FakeRenderer:
        def render(self, timing, targets, config, dur, ctx):
            return ["h264_nvenc"]
    monkeypatch.setattr(pipeline, "get_renderer", lambda cfg: FakeRenderer())
    monkeypatch.setattr("karaoke.render.encode.audio_duration", lambda p: 5.0)

    pipeline.run_render(sp, _cfg(), full=True, mode="review")
    row = _rows(sp)[-1]
    assert row["op"] == "render"
    assert row["model"] == "mms" and row["source"] == "ab-keep"   # self-describing
    assert row["render_mode"] == "review"
    assert "nvenc" in row["encoder"] and "GPU" in row["encoder"]


def test_render_history_extra_overrides_provenance(tmp_path, monkeypatch):
    """history_extra (used by `ab`) replaces the read-back provenance so a
    labeled render is tagged with its own model/seed/notes, not the canonical
    align's."""
    sp = _song(tmp_path)
    sp.timing_json.write_text(
        '{"lines": [{"words": [{"text": "hi", "start": 1.0, "end": 2.0}]}]}',
        encoding="utf-8")
    sp.instrumental.write_bytes(b"x"); sp.song.write_bytes(b"x")
    from karaoke import history
    # Canonical history says whisper/medium — the labeled render must NOT inherit it.
    history.append_row(sp, _cfg(), "align", duration_s=1, model="whisper",
                       source="align-cold", whisper_params="medium;bestof3")

    class FakeRenderer:
        def render(self, timing, targets, config, dur, ctx):
            return ["h264_nvenc"]
    monkeypatch.setattr(pipeline, "get_renderer", lambda cfg: FakeRenderer())
    monkeypatch.setattr("karaoke.render.encode.audio_duration", lambda p: 5.0)

    pipeline.run_render(sp, _cfg(), full=True, mode="review",
                        history_extra={"model": "mms", "seed": "24.0",
                                       "source": "ab-seeded", "whisper_params": "",
                                       "notes": "ab-gen"})
    row = _rows(sp)[-1]
    assert row["op"] == "render" and row["model"] == "mms"
    assert row["seed"] == "24.0" and row["source"] == "ab-seeded"
    assert row["whisper_params"] == "" and row["notes"] == "ab-gen"
