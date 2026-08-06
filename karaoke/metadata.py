from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class TrackMeta:
    artist: Optional[str] = None
    title: Optional[str] = None


def parse_folder_name(name: str) -> TrackMeta:
    if " - " in name:
        artist, title = name.split(" - ", 1)
        return TrackMeta(artist=artist.strip(), title=title.strip())
    return TrackMeta(artist=None, title=name.strip())


def read_tags(audio_path: Path) -> TrackMeta:
    """Read artist/title from file tags via mutagen; missing tags -> None."""
    try:
        from mutagen import File as MutagenFile
        mf = MutagenFile(str(audio_path), easy=True)
        if mf is None:
            return TrackMeta()
        artist = (mf.get("artist") or [None])[0]
        title = (mf.get("title") or [None])[0]
        return TrackMeta(artist=artist, title=title)
    except Exception:
        return TrackMeta()


def _coalesce(*values):
    # Intentionally skips falsy/blank values so a blank "" tag falls through to the next source.
    for v in values:
        if v:
            return v
    return None


def resolve_metadata(override: Optional[TrackMeta],
                     tags: Optional[TrackMeta],
                     folder: Optional[TrackMeta]) -> TrackMeta:
    sources = [s for s in (override, tags, folder) if s is not None]
    artist = _coalesce(*[s.artist for s in sources])
    title = _coalesce(*[s.title for s in sources])
    return TrackMeta(artist=artist, title=title)
