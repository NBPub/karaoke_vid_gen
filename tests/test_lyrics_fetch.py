import karaoke.lyrics as lyrics
from karaoke.metadata import TrackMeta


class FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
    def json(self):
        return self._payload


def test_lrclib_hit(monkeypatch):
    def fake_get(url, params=None, timeout=None, headers=None):
        assert "lrclib.net" in url
        return FakeResp(200, {"plainLyrics": "line one\nline two"})
    monkeypatch.setattr(lyrics.requests, "get", fake_get)
    assert lyrics.fetch_from_lrclib(TrackMeta("A", "B")) == "line one\nline two"


def test_lrclib_miss_returns_none(monkeypatch):
    monkeypatch.setattr(lyrics.requests, "get",
                        lambda *a, **k: FakeResp(404, {}))
    assert lyrics.fetch_from_lrclib(TrackMeta("A", "B")) is None


def test_fetch_lyrics_falls_back_to_ovh(monkeypatch):
    monkeypatch.setattr(lyrics, "fetch_from_lrclib", lambda meta: None)
    monkeypatch.setattr(lyrics, "fetch_from_lyrics_ovh", lambda meta: "ovh words")
    assert lyrics.fetch_lyrics(TrackMeta("A", "B")) == "ovh words"


def test_fetch_lyrics_returns_none_when_all_fail(monkeypatch):
    monkeypatch.setattr(lyrics, "fetch_from_lrclib", lambda meta: None)
    monkeypatch.setattr(lyrics, "fetch_from_lyrics_ovh", lambda meta: None)
    assert lyrics.fetch_lyrics(TrackMeta("A", "B")) is None


from pathlib import Path
from karaoke.lyrics import ensure_lyrics


def test_ensure_lyrics_uses_existing_file(tmp_path, monkeypatch):
    f = tmp_path / "lyrics.txt"
    f.write_text("already here", encoding="utf-8")
    monkeypatch.setattr("karaoke.lyrics.fetch_lyrics",
                        lambda meta: (_ for _ in ()).throw(AssertionError("called")))
    assert ensure_lyrics(TrackMeta("A", "B"), f) is True
    assert f.read_text(encoding="utf-8") == "already here"


def test_ensure_lyrics_writes_fetched(tmp_path, monkeypatch):
    f = tmp_path / "lyrics.txt"
    monkeypatch.setattr("karaoke.lyrics.fetch_lyrics", lambda meta: "fetched words")
    assert ensure_lyrics(TrackMeta("A", "B"), f) is True
    assert f.read_text(encoding="utf-8") == "fetched words"


def test_ensure_lyrics_creates_placeholder_when_not_found(tmp_path, monkeypatch):
    f = tmp_path / "lyrics.txt"
    monkeypatch.setattr("karaoke.lyrics.fetch_lyrics", lambda meta: None)
    assert ensure_lyrics(TrackMeta("A", "B"), f) is False
    assert f.exists()
    assert f.read_text(encoding="utf-8").strip() == ""


def test_lyrics_ovh_missing_artist_returns_none():
    assert lyrics.fetch_from_lyrics_ovh(TrackMeta(None, "Title")) is None
    assert lyrics.fetch_from_lyrics_ovh(TrackMeta("Artist", None)) is None


def test_lyrics_ovh_hit(monkeypatch):
    def fake_get(url, params=None, timeout=None, headers=None):
        assert "lyrics.ovh" in url
        return FakeResp(200, {"lyrics": "ovh line"})
    monkeypatch.setattr(lyrics.requests, "get", fake_get)
    assert lyrics.fetch_from_lyrics_ovh(TrackMeta("A", "B")) == "ovh line"


def test_ensure_lyrics_creates_missing_parent_dirs(tmp_path, monkeypatch):
    f = tmp_path / "newsub" / "lyrics.txt"
    monkeypatch.setattr("karaoke.lyrics.fetch_lyrics", lambda meta: "words")
    assert ensure_lyrics(TrackMeta("A", "B"), f) is True
    assert f.read_text(encoding="utf-8") == "words"
