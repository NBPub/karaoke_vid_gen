from pathlib import Path
import pytest
import karaoke.acquire as acquire
from karaoke.metadata import TrackMeta


def test_is_url():
    assert acquire.is_url("https://youtu.be/abc")
    assert acquire.is_url("http://example.com/a.mp3")
    assert not acquire.is_url(r"C:\music\song.mp3")
    assert not acquire.is_url("song.flac")


def test_acquire_local_calls_normalize(tmp_path, monkeypatch):
    src = tmp_path / "in.flac"
    src.write_bytes(b"x")
    out = tmp_path / "song.wav"
    calls = {}
    monkeypatch.setattr(acquire, "_normalize",
                        lambda i, o, sr: calls.setdefault("norm", (Path(i), Path(o), sr)))
    def no_download(*a, **k):
        raise AssertionError("download should not be called for local files")
    monkeypatch.setattr(acquire, "_download_audio", no_download)
    acquire.acquire(str(src), out, sample_rate=44100)
    assert calls["norm"][0] == src
    assert calls["norm"][1] == out


def test_is_playlist_url():
    assert acquire._is_playlist_url("https://www.youtube.com/watch?v=abc&list=PL1&index=4")
    assert acquire._is_playlist_url("https://www.youtube.com/playlist?list=PL1")
    assert not acquire._is_playlist_url("https://www.youtube.com/watch?v=abc")
    assert not acquire._is_playlist_url("https://youtu.be/abc")


def test_acquire_rejects_playlist_url(tmp_path, monkeypatch):
    # A playlist URL (has list=) must warn + exit BEFORE any download attempt.
    def no_download(*a, **k):
        raise AssertionError("must not download for a playlist URL")
    monkeypatch.setattr(acquire, "_download_audio", no_download)
    monkeypatch.setattr(acquire, "_normalize", no_download)
    with pytest.raises(ValueError) as exc:
        acquire.acquire("https://www.youtube.com/watch?v=abc&list=PL1&index=4",
                        tmp_path / "song.wav")
    assert "playlist" in str(exc.value).lower()


def test_acquire_url_downloads_then_normalizes(tmp_path, monkeypatch):
    out = tmp_path / "song.wav"
    downloaded = tmp_path / "dl.m4a"
    downloaded.write_bytes(b"x")
    seen = {}
    monkeypatch.setattr(acquire, "_download_audio", lambda u, d: downloaded)
    monkeypatch.setattr(acquire, "_normalize",
                        lambda i, o, sr: seen.setdefault("in", Path(i)))
    acquire.acquire("https://youtu.be/abc", out, sample_rate=44100)
    assert seen["in"] == downloaded


# --- song.flac metadata tagging ---------------------------------------------

def test_resolve_song_tags_url_uses_folder():
    # URL source (source_tags=None): folder name is the sole source.
    folder = TrackMeta("Artist", "Title")
    assert acquire.resolve_song_tags(folder, None) == TrackMeta("Artist", "Title")


def test_resolve_song_tags_local_per_field():
    folder = TrackMeta("FolderArtist", "FolderTitle")
    # fully tagged source wins both fields
    assert acquire.resolve_song_tags(folder, TrackMeta("SrcA", "SrcT")) == TrackMeta("SrcA", "SrcT")
    # partial source: keep its artist, fill the missing title from the folder
    assert acquire.resolve_song_tags(folder, TrackMeta("SrcA", None)) == TrackMeta("SrcA", "FolderTitle")
    # untagged source: folder fills both
    assert acquire.resolve_song_tags(folder, TrackMeta()) == TrackMeta("FolderArtist", "FolderTitle")


def test_acquire_url_tags_from_folder_name(tmp_path, monkeypatch):
    song_dir = tmp_path / "Jonathan Coulton - Code Monkey"
    song_dir.mkdir()
    out = song_dir / "song.flac"
    monkeypatch.setattr(acquire, "_download_audio", lambda u, d: tmp_path / "dl.m4a")
    monkeypatch.setattr(acquire, "_normalize", lambda i, o, sr: None)
    captured = {}
    monkeypatch.setattr(acquire, "_write_flac_tags", lambda p, m: captured.setdefault("m", m))
    acquire.acquire("https://youtu.be/abc", out)
    assert captured["m"] == TrackMeta("Jonathan Coulton", "Code Monkey")


def test_acquire_local_keeps_source_tags_fills_gaps(tmp_path, monkeypatch):
    song_dir = tmp_path / "Folder Artist - Folder Title"
    song_dir.mkdir()
    src = tmp_path / "in.mp3"
    src.write_bytes(b"x")
    out = song_dir / "song.flac"
    monkeypatch.setattr(acquire, "_normalize", lambda i, o, sr: None)
    monkeypatch.setattr(acquire, "read_tags", lambda p: TrackMeta("Real Artist", None))
    captured = {}
    monkeypatch.setattr(acquire, "_write_flac_tags", lambda p, m: captured.setdefault("m", m))
    acquire.acquire(str(src), out)
    # source artist kept, missing title filled from the folder name
    assert captured["m"] == TrackMeta("Real Artist", "Folder Title")


def test_write_flac_tags_roundtrip(tmp_path):
    sf = pytest.importorskip("soundfile")
    np = pytest.importorskip("numpy")
    p = tmp_path / "song.flac"
    sf.write(str(p), np.zeros((2048, 2)), 44100, format="FLAC", subtype="PCM_16")
    acquire._write_flac_tags(p, TrackMeta("A", "B"))
    from karaoke.metadata import read_tags
    assert read_tags(p) == TrackMeta("A", "B")
