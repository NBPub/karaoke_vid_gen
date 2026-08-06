from __future__ import annotations
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote
import requests
from karaoke.metadata import TrackMeta

_TIMEOUT = 10


def parse_lyrics(text: str) -> List[str]:
    """One display line per non-empty lyric line.

    Drops [section] headers, removes standalone dash tokens used as separators
    (keeping internal hyphens like "mental-pack" and parentheticals), and drops
    lines that become empty.
    """
    lines: List[str] = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.startswith("[") and s.endswith("]"):
            continue
        tokens = [tok for tok in s.split() if set(tok) != {"-"}]
        cleaned = " ".join(tokens)
        if cleaned:
            lines.append(cleaned)
    return lines


def fetch_from_lrclib(meta: TrackMeta) -> Optional[str]:
    try:
        resp = requests.get(
            "https://lrclib.net/api/get",
            params={"artist_name": meta.artist or "", "track_name": meta.title or ""},
            headers={"User-Agent": "karaoke-tool (personal use)"},
            timeout=_TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data.get("plainLyrics") or None
    except Exception:
        return None


def fetch_from_lyrics_ovh(meta: TrackMeta) -> Optional[str]:
    if not (meta.artist and meta.title):
        return None
    try:
        resp = requests.get(
            f"https://api.lyrics.ovh/v1/"
            f"{quote(meta.artist, safe='')}/{quote(meta.title, safe='')}",
            timeout=_TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        return resp.json().get("lyrics") or None
    except Exception:
        return None


def fetch_lyrics(meta: TrackMeta) -> Optional[str]:
    """Try sources in priority order; return raw lyric text or None."""
    for source in (fetch_from_lrclib, fetch_from_lyrics_ovh):
        text = source(meta)
        if text:
            return text
    return None


def ensure_lyrics(meta: TrackMeta, lyrics_txt: Path) -> bool:
    """Ensure lyrics.txt has content.

    Returns True if lyrics are available (existing or fetched), False if a
    blank placeholder was created for the user to paste into.
    """
    lyrics_txt = Path(lyrics_txt)
    if lyrics_txt.exists() and lyrics_txt.read_text(encoding="utf-8").strip():
        return True
    text = fetch_lyrics(meta)
    lyrics_txt.parent.mkdir(parents=True, exist_ok=True)
    if text:
        lyrics_txt.write_text(text, encoding="utf-8")
        return True
    lyrics_txt.write_text("", encoding="utf-8")
    return False
