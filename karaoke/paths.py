from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SongPaths:
    root: Path

    @classmethod
    def for_song(cls, songs_dir: Path, folder_name: str) -> "SongPaths":
        return cls(root=Path(songs_dir) / folder_name)

    def ensure(self) -> "SongPaths":
        self.root.mkdir(parents=True, exist_ok=True)
        return self

    @property
    def song(self) -> Path: return self.root / "song.flac"
    @property
    def instrumental(self) -> Path: return self.root / "instrumental.flac"
    @property
    def vocals(self) -> Path: return self.root / "vocals.flac"
    @property
    def lyrics_txt(self) -> Path: return self.root / "lyrics.txt"
    @property
    def timing_json(self) -> Path: return self.root / "timing.json"
    @property
    def timing_baseline(self) -> Path: return self.root / "timing.baseline.json"
    @property
    def output_mp4(self) -> Path: return self.root / "karaoke.mp4"
    @property
    def review_mp4(self) -> Path: return self.root / "karaoke.review.mp4"

    def ab_timing(self, model: str) -> Path:
        return self.root / f"timing.{model}.json"

    def ab_review(self, model: str) -> Path:
        return self.root / f"karaoke.review.{model}.mp4"

    def ab_output(self, model: str) -> Path:
        return self.root / f"karaoke.{model}.mp4"

    @property
    def history_csv(self) -> Path: return self.root / "history.csv"

    @property
    def no_extract(self) -> Path: return self.root / "no_extract.txt"
