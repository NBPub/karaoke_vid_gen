from pathlib import Path
import csv
from karaoke import history
from karaoke.history import _pristine_align_model
from karaoke.config import Config
from karaoke.paths import SongPaths


def test_pristine_align_model_align_only():
    assert _pristine_align_model([{"op": "align", "model": "whisper"}]) == "whisper"


def test_pristine_align_model_align_then_render_still_pristine():
    assert _pristine_align_model(
        [{"op": "align", "model": "mms"}, {"op": "render", "model": "mms"}]) == "mms"


def test_pristine_align_model_nudge_after_align_disqualifies():
    assert _pristine_align_model(
        [{"op": "align", "model": "whisper"}, {"op": "nudge", "model": "whisper"}]) is None


def test_pristine_align_model_split_or_abkeep_after_align_disqualifies():
    assert _pristine_align_model(
        [{"op": "align", "model": "whisper"}, {"op": "split", "model": "whisper"}]) is None
    assert _pristine_align_model(
        [{"op": "align", "model": "mms"}, {"op": "ab-keep", "model": "mms"}]) is None


def test_pristine_align_model_last_align_wins():
    assert _pristine_align_model(
        [{"op": "align", "model": "whisper"}, {"op": "render", "model": "whisper"},
         {"op": "align", "model": "mms"}]) == "mms"


def test_pristine_align_model_empty_or_no_align():
    assert _pristine_align_model([]) is None
    assert _pristine_align_model([{"op": "render", "model": "whisper"}]) is None


def _sp(tmp_path):
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    sp.timing_json.write_text('{"lines": []}', encoding="utf-8")
    return sp


def _cfg(enabled=True):
    c = Config.load(Path("missing.toml"))
    c.history.enabled = enabled
    return c


def test_format_duration():
    assert history.format_duration(8) == "8s"
    assert history.format_duration(64) == "1m04s"
    assert history.format_duration(192) == "3m12s"


def test_append_writes_header_then_row(tmp_path):
    sp = _sp(tmp_path)
    history.append_row(sp, _cfg(), "align", duration_s=192, model="whisper",
                       seed="20.5", source="align-seeded", whisper_params="medium;bestof1")
    rows = list(csv.DictReader(sp.history_csv.open(encoding="utf-8")))
    assert len(rows) == 1
    r = rows[0]
    assert r["op"] == "align" and r["model"] == "whisper" and r["seed"] == "20.5"
    assert r["duration"] == "3m12s"
    assert r["timing_mtime"]  # filled from timing.json mtime
    assert r["timestamp"]
    # appending again does not re-write the header
    history.append_row(sp, _cfg(), "nudge", duration_s=8, model="whisper")
    assert len(list(csv.DictReader(sp.history_csv.open(encoding="utf-8")))) == 2


def test_append_disabled_writes_nothing(tmp_path):
    sp = _sp(tmp_path)
    history.append_row(sp, _cfg(enabled=False), "align", duration_s=1)
    assert not sp.history_csv.exists()


def test_current_provenance_latest_nonempty_within_model(tmp_path):
    sp = _sp(tmp_path)
    history.append_row(sp, _cfg(), "align", model="whisper", seed="34",
                       whisper_params="medium;bestof3")
    history.append_row(sp, _cfg(), "render", model="whisper", source="ab-cold")
    prov = history.current_provenance(sp)
    assert prov["model"] == "whisper"
    assert prov["seed"] == "34"                    # from the align row (same model)
    assert prov["source"] == "ab-cold"
    assert prov["whisper_params"] == "medium;bestof3"


def test_current_provenance_is_model_coherent(tmp_path):
    """Switching whisper -> mms must NOT leak the whisper Whisper params / seed onto
    the mms provenance (the Lil Wyte 'Acid' history bug)."""
    sp = _sp(tmp_path)
    history.append_row(sp, _cfg(), "align", model="whisper", seed="34",
                       whisper_params="medium;bestof3")
    history.append_row(sp, _cfg(), "render", model="mms", source="ab-cold", notes="ab-gen")
    history.append_row(sp, _cfg(), "ab-keep", model="mms", source="ab-keep")
    prov = history.current_provenance(sp)          # model=None -> latest (mms)
    assert prov["model"] == "mms"
    assert prov["whisper_params"] == ""            # NOT medium;bestof3
    assert prov["seed"] == ""                      # NOT 34 (whisper-only)
    assert prov["source"] == "ab-keep"
    # Explicitly scoping to whisper still recovers its params (for a whisper keep).
    hy = history.current_provenance(sp, model="whisper")
    assert hy["whisper_params"] == "medium;bestof3" and hy["seed"] == "34"


def test_current_provenance_empty_when_no_file(tmp_path):
    sp = SongPaths.for_song(tmp_path, "A - B").ensure()
    assert history.current_provenance(sp) == {
        "model": "", "seed": "", "source": "", "whisper_params": ""}
