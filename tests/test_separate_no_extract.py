import numpy as np
import soundfile as sf
from pathlib import Path
from karaoke import separate as sep
from karaoke.config import Config


def _cfg():
    return Config.load(Path("missing.toml"))


def _write(path, data, sr=100):
    # PCM_16 (FLAC is integer-only); 0.5/0.25/0.0 are exactly representable in
    # 16-bit, so the round-trip assertions below stay exact without tolerances.
    sf.write(str(path), data, sr, subtype="PCM_16")


def _fake_demucs_factory(stem_root, instr_value=0.0, sr=100, n=200):
    """Return a _run_demucs replacement that writes synthetic FLAC stems and
    returns their dir. no_vocals = constant instr_value, vocals = zeros."""
    def fake(song_path, out_dir, model, device):
        d = Path(stem_root)
        d.mkdir(parents=True, exist_ok=True)
        _write(d / "no_vocals.flac", np.full(n, instr_value), sr)
        _write(d / "vocals.flac", np.zeros(n), sr)
        return d
    return fake


def test_no_extract_splices_original_into_instrumental(tmp_path, monkeypatch):
    sr, n = 100, 200
    # song = 0.5 everywhere; demucs no_vocals = 0.0 everywhere
    _write(tmp_path / "song.flac", np.full(n, 0.5), sr)
    monkeypatch.setattr(sep, "_run_demucs",
                        _fake_demucs_factory(tmp_path / "stems", sr=sr, n=n))
    nx_file = tmp_path / "no_extract.txt"
    nx_file.write_text("0.5-1.0\n", encoding="utf-8")  # samples ~50..100

    instr_out = tmp_path / "instrumental.flac"
    voc_out = tmp_path / "vocals.flac"
    sep.separate(tmp_path / "song.flac", instr_out, voc_out, _cfg(),
                 no_extract_file=nx_file)

    instr, _ = sf.read(str(instr_out))
    assert instr[70] == 0.5     # inside interval -> original (song)
    assert instr[10] == 0.0     # outside -> vocals-removed
    voc, _ = sf.read(str(voc_out))
    assert voc[70] == 0.0       # vocals untouched


def test_no_file_copies_no_vocals_unchanged(tmp_path, monkeypatch):
    sr, n = 100, 200
    _write(tmp_path / "song.flac", np.full(n, 0.5), sr)
    monkeypatch.setattr(sep, "_run_demucs",
                        _fake_demucs_factory(tmp_path / "stems", sr=sr, n=n))
    instr_out = tmp_path / "instrumental.flac"
    sep.separate(tmp_path / "song.flac", instr_out, tmp_path / "vocals.flac",
                 _cfg(), no_extract_file=tmp_path / "no_extract.txt")  # absent
    instr, _ = sf.read(str(instr_out))
    assert np.allclose(instr, 0.0)   # all vocals-removed, no splice


def test_no_extract_prints_interval_readout(tmp_path, monkeypatch, capsys):
    sr, n = 100, 200
    _write(tmp_path / "song.flac", np.full(n, 0.5), sr)
    monkeypatch.setattr(sep, "_run_demucs",
                        _fake_demucs_factory(tmp_path / "stems", sr=sr, n=n))
    nx_file = tmp_path / "no_extract.txt"
    nx_file.write_text("0.5-1.0\n", encoding="utf-8")
    sep.separate(tmp_path / "song.flac", tmp_path / "instrumental.flac",
                 tmp_path / "vocals.flac", _cfg(), no_extract_file=nx_file)
    out = capsys.readouterr().out.lower()
    assert "[no_extract]" in out and "span" in out       # readout confirms it was applied


def test_no_extract_malformed_warns_and_falls_back(tmp_path, monkeypatch, capsys):
    sr, n = 100, 200
    _write(tmp_path / "song.flac", np.full(n, 0.5), sr)
    monkeypatch.setattr(sep, "_run_demucs",
                        _fake_demucs_factory(tmp_path / "stems", sr=sr, n=n))
    nx_file = tmp_path / "no_extract.txt"
    nx_file.write_text("1.0-0.5\n", encoding="utf-8")     # start >= end -> malformed
    instr_out = tmp_path / "instrumental.flac"
    sep.separate(tmp_path / "song.flac", instr_out, tmp_path / "vocals.flac",
                 _cfg(), no_extract_file=nx_file)          # no crash
    out = capsys.readouterr().out.lower()
    assert "no_extract" in out and "could not" in out
    instr, _ = sf.read(str(instr_out))
    assert np.allclose(instr, 0.0)                        # fell back to plain instrumental


def test_supplied_instrumental_ignores_no_extract(tmp_path, monkeypatch, capsys):
    sr, n = 100, 200
    _write(tmp_path / "song.flac", np.full(n, 0.5), sr)
    _write(tmp_path / "supplied.flac", np.full(n, 0.25), sr)
    monkeypatch.setattr(sep, "_run_demucs",
                        _fake_demucs_factory(tmp_path / "stems", sr=sr, n=n))
    nx_file = tmp_path / "no_extract.txt"
    nx_file.write_text("0.5-1.0\n", encoding="utf-8")
    instr_out = tmp_path / "instrumental.flac"
    sep.separate(tmp_path / "song.flac", instr_out, tmp_path / "vocals.flac",
                 _cfg(), supplied_instrumental=str(tmp_path / "supplied.flac"),
                 no_extract_file=nx_file)
    instr, _ = sf.read(str(instr_out))
    assert np.allclose(instr, 0.25)                 # supplied, unspliced
    assert "ignored" in capsys.readouterr().out.lower()
