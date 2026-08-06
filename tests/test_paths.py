from pathlib import Path
from karaoke.paths import SongPaths


def test_ab_output_labeled_name(tmp_path):
    sp = SongPaths.for_song(tmp_path, "A - B")
    assert sp.ab_output("whisper").name == "karaoke.whisper.mp4"
    assert sp.ab_output("mms").name == "karaoke.mms.mp4"


def test_paths_for_song(tmp_path):
    sp = SongPaths.for_song(tmp_path, "Radiohead - Creep")
    assert sp.root == tmp_path / "Radiohead - Creep"
    assert sp.song.name == "song.flac"
    assert sp.instrumental.name == "instrumental.flac"
    assert sp.vocals.name == "vocals.flac"
    assert sp.lyrics_txt.name == "lyrics.txt"
    assert sp.timing_json.name == "timing.json"
    assert sp.output_mp4.name == "karaoke.mp4"
    assert sp.review_mp4.name == "karaoke.review.mp4"
    assert sp.song.parent == sp.root


def test_ensure_creates_root(tmp_path):
    sp = SongPaths.for_song(tmp_path, "A - B")
    assert not sp.root.exists()
    sp.ensure()
    assert sp.root.is_dir()
