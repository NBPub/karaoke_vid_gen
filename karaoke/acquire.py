from __future__ import annotations
import subprocess
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from karaoke.metadata import TrackMeta, parse_folder_name, read_tags


def is_url(source: str) -> bool:
    return source.startswith("http://") or source.startswith("https://")


def _is_playlist_url(url: str) -> bool:
    """True when the URL carries a playlist (a `list=` query parameter). We
    process one song at a time, so these are refused up front rather than ripped."""
    return "list" in parse_qs(urlparse(url).query)


def _download_audio(url: str, dest_dir: Path) -> Path:
    """Download best audio with yt-dlp into dest_dir; return the file path."""
    from yt_dlp import YoutubeDL
    dest_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(dest_dir / "source.%(ext)s"),
        "quiet": True,
        "noprogress": True,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return Path(ydl.prepare_filename(info))


def _normalize(in_path: Path, out_path: Path, sample_rate: int) -> None:
    """Transcode to the output format (extension-driven) at the given sample
    rate, stereo. For FLAC, `-sample_fmt s16` keeps it bit-exact PCM_16."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(in_path),
         "-ar", str(sample_rate), "-ac", "2", "-sample_fmt", "s16", str(out_path)],
        check=True,
    )


def resolve_song_tags(folder: TrackMeta,
                      source_tags: TrackMeta | None) -> TrackMeta:
    """Decide the artist/title to tag `song.flac` with. `source_tags` is None for a
    URL (or when the local file carries no tags), so the folder name is the only
    source. For a local file, tags win per-field and the folder name fills any gap."""
    st = source_tags or TrackMeta()
    return TrackMeta(artist=st.artist or folder.artist,
                     title=st.title or folder.title)


def _write_flac_tags(path: Path, meta: TrackMeta) -> None:
    """Write ARTIST/TITLE Vorbis comments onto a FLAC, leaving other tags intact.
    Best-effort: a tagging failure must never fail the acquire stage."""
    if not (meta.artist or meta.title):
        return
    try:
        from mutagen.flac import FLAC
        f = FLAC(str(path))
        if meta.artist:
            f["artist"] = meta.artist
        if meta.title:
            f["title"] = meta.title
        f.save()
    except Exception as e:  # noqa: BLE001 - tagging is a nicety, not a hard step
        print(f"[acquire] could not tag {Path(path).name} ({e}); leaving untagged")


def acquire(source: str, out_audio: Path, sample_rate: int = 44100) -> Path:
    """Stage 1: produce a normalized FLAC (PCM_16) from a URL or local file, then
    tag it with artist/title (folder name for a URL; source tags win, folder fills,
    for a local file)."""
    out_audio = Path(out_audio)
    if is_url(source):
        if _is_playlist_url(source):
            raise ValueError(
                "Refusing a playlist URL (it has a 'list=' parameter):\n"
                f"  {source}\n"
                "Karaoke processes one song at a time. Supply a single-video URL "
                "(no '&list=...') or a local audio file.")
        downloaded = _download_audio(source, out_audio.parent / "_download")
        _normalize(downloaded, out_audio, sample_rate)
        source_tags = None
    else:
        _normalize(Path(source), out_audio, sample_rate)
        source_tags = read_tags(Path(source))
    folder = parse_folder_name(out_audio.parent.name)
    _write_flac_tags(out_audio, resolve_song_tags(folder, source_tags))
    return out_audio
