from pathlib import Path
import karaoke.separate as separate
from karaoke.config import Config


def test_separate_runs_demucs_and_places_stems(tmp_path, monkeypatch):
    song = tmp_path / "song.wav"; song.write_bytes(b"x")
    instrumental = tmp_path / "instrumental.wav"
    vocals = tmp_path / "vocals.flac"

    def fake_run_demucs(song_path, out_dir, model, device):
        stem_dir = Path(out_dir) / model / song_path.stem
        stem_dir.mkdir(parents=True)
        (stem_dir / "vocals.flac").write_bytes(b"v")
        (stem_dir / "no_vocals.flac").write_bytes(b"n")
        return stem_dir
    monkeypatch.setattr(separate, "_run_demucs", fake_run_demucs)

    separate.separate(song, instrumental, vocals, Config())
    assert vocals.read_bytes() == b"v"
    assert instrumental.read_bytes() == b"n"


def test_separate_uses_supplied_instrumental(tmp_path, monkeypatch):
    song = tmp_path / "song.wav"; song.write_bytes(b"x")
    supplied = tmp_path / "mine.wav"; supplied.write_bytes(b"SUP")
    instrumental = tmp_path / "instrumental.wav"
    vocals = tmp_path / "vocals.flac"

    def fake_run_demucs(song_path, out_dir, model, device):
        d = Path(out_dir) / model / song_path.stem; d.mkdir(parents=True)
        (d / "vocals.flac").write_bytes(b"v"); (d / "no_vocals.flac").write_bytes(b"n")
        return d
    monkeypatch.setattr(separate, "_run_demucs", fake_run_demucs)
    monkeypatch.setattr(separate, "_resolve_instrumental_source",
                        lambda src, workdir: supplied)

    separate.separate(song, instrumental, vocals, Config(),
                      supplied_instrumental=str(supplied))
    assert vocals.read_bytes() == b"v"
    assert instrumental.read_bytes() == b"SUP"
