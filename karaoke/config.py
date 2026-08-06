from __future__ import annotations
import dataclasses
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path


def _merge(base, overrides: dict, section: str):
    """Apply *overrides* onto *base* dataclass, raising ValueError for unknown keys."""
    valid_keys = {f.name for f in dataclasses.fields(base)}
    unknown = set(overrides) - valid_keys
    if unknown:
        raise ValueError(f"[{section}] has unknown config key(s): {sorted(unknown)}")
    return replace(base, **overrides)


@dataclass
class RenderConfig:
    width: int = 1920
    height: int = 1080
    fps: int = 30
    background: str = "#0b0e14"
    # The active line's not-yet-sung words: bright (near-white) so the current
    # line is the brightest thing on screen; it sweeps to fill_color as it's sung.
    base_color: str = "#e5e7eb"
    fill_color: str = "#9B5DE5"          # BlueViolet — the active fill sweep
    # Already-sung lines: a dimmed MediumSlateBlue, so sung text reads as "done"
    # and is distinct from both the bright active line and the grey upcoming lines.
    past_color: str = "#4a3f9e"
    upcoming_color: str = "#4b5563"
    font_family: str = "Segoe UI, Arial, sans-serif"
    font_size: int = 52
    # Lines shown per "page". The page stays static while the active line fills
    # down it; when the active line reaches the second-to-last line, the page
    # turns and that line becomes the new top (see karaoke/fill.py).
    lines_per_page: int = 6
    # When the instrumental continues more than this many seconds past the last
    # lyric, the render asks before including the full outro.
    outro_threshold_seconds: float = 60.0
    # Seconds of instrumental kept after the last lyric when NOT playing the full song.
    tail_seconds: float = 3.0
    # Wait bar: during instrumental gaps longer than wait_min_gap_seconds (intro,
    # mid-song breaks, outro), show a filling progress bar below the dimmed lyrics
    # instead of prematurely highlighting the next line. The bar fills until
    # wait_bar_end_seconds before the next line; the next line is highlighted from
    # wait_highlight_seconds before it starts (so the highlight leads the bar's
    # disappearance). The outro bar uses a separate, warmer colour.
    wait_bar: bool = True
    wait_min_gap_seconds: float = 12.0
    wait_bar_end_seconds: float = 1.0
    wait_highlight_seconds: float = 3.0
    wait_fill_color: str = "#F2C94C"    # gold — intro / mid-song breaks
    wait_outro_color: str = "#DB7A33"   # warmer orange — end-of-song outro
    # Which outputs to render: "both" (karaoke.mp4 + review.mp4), "karaoke"
    # (instrumental only), or "review" (full-audio copy only — fast iteration).
    mode: str = "review"
    # Video encoder: "auto" (NVENC if available, else libx264), "nvenc", "libx264".
    video_codec: str = "auto"
    nvenc_cq: int = 23   # NVENC quality (lower = better/bigger), ~ x264 crf 23
    # Title card: artist + title centered over the first title_seconds. If the
    # first sung word lands before title_seconds + title_read_buffer_seconds, the
    # whole song is delayed (lead-in) so the singer always gets read time.
    title_card: bool = True
    title_seconds: float = 3.0
    title_read_buffer_seconds: float = 2.0
    title_fade_seconds: float = 0.5
    # Persistent right-edge progress bar: outline matches the sung-text colour,
    # fills dark red top->bottom across the actual track.
    progress_bar: bool = True
    progress_fill_color: str = "#8B0000"      # dark red
    progress_outline_color: str = "#4a3f9e"   # matches past_color (sung text)
    # Count-in: before the first line and before any line after a pause, show
    # three dots that fill (purple) over the final wait_highlight_seconds as a
    # visual 3-2-1. A line qualifies when the gap before it is at least
    # count_in_min_gap_seconds (decoupled from the wait bar's wait_min_gap_seconds,
    # so short 5-12s gaps get a count-in without the instrumental-break wait bar).
    count_in: bool = True
    count_in_min_gap_seconds: float = 5.0
    # Explicit TTF for the renderer; "" auto-resolves a bold system font.
    font_file: str = ""
    # Pillow draw workers: 0 = all cores, 1 = serial, N = N processes.
    jobs: int = 0
    # Fraction of the frame width a lyric line may occupy before the preflight
    # flags it and `split` wraps it. 1.0 means exactly the window (no margin);
    # lower values (e.g. 0.95 / 0.92) demand an edge margin. At the default
    # proportional font a longer line runs off the window edge (lines are
    # centre-aligned, so it overflows both sides).
    usable_width_frac: float = 0.92


@dataclass
class AudioConfig:
    sample_rate: int = 44100
    bitrate: str = "320k"


@dataclass
class ModelConfig:
    demucs_model: str = "htdemucs"
    device: str = "cuda"
    # "whisper" = Whisper ASR anchors + reconciliation against the known lyrics
    # (robust on repeated/screamed choruses); "mms" = single-pass CTC forced
    # alignment (torchaudio MMS_FA). ("torchaudio" is still accepted for "mms".)
    aligner: str = "whisper"
    whisper_model: str = "medium"


@dataclass
class AlignConfig:
    # Back each word's start up to the true onset of its sound in the vocal stem
    # (Whisper marks starts a touch late). Only moves earlier, bounded by lookback.
    onset_snap: bool = True
    onset_lookback_seconds: float = 0.25
    # Uniform head-start of the lyric fill over the voice (karaoke anticipation),
    # applied to every word after onset snapping.
    lead_seconds: float = 0.10
    # Whisper draws to take per align: 1 = greedy only (fast, reproducible).
    # >1 adds that many sampled draws and keeps whichever anchors the most known
    # words — helps screamed/messy vocals, costs N x transcription time.
    best_of_n: int = 1
    sample_temperature: float = 0.4
    # +/- padding (seconds) around the coarse line marks a human gives `nudge
    # --fill-cleared`, defining the window the forced aligner searches within.
    realign_search_margin_seconds: float = 1.0
    # Seconds of audio kept BEFORE the `--first-line` hint when seeding a re-align
    # (gives the aligner a short run-up and absorbs the +/-1s guess slop).
    first_line_pad_seconds: float = 1.0


@dataclass
class HistoryConfig:
    enabled: bool = True


@dataclass
class PathsConfig:
    # Where song folders live. Overridden by --songs-dir on the command line.
    songs_dir: str = "songs"


@dataclass
class Config:
    render: RenderConfig = field(default_factory=RenderConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    models: ModelConfig = field(default_factory=ModelConfig)
    align: AlignConfig = field(default_factory=AlignConfig)
    history: HistoryConfig = field(default_factory=HistoryConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)

    @classmethod
    def load(cls, path: Path) -> "Config":
        cfg = cls()
        path = Path(path)
        if not path.exists():
            return cfg
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        return cls(
            render=_merge(cfg.render, data.get("render", {}), "render"),
            audio=_merge(cfg.audio, data.get("audio", {}), "audio"),
            models=_merge(cfg.models, data.get("models", {}), "models"),
            align=_merge(cfg.align, data.get("align", {}), "align"),
            history=_merge(cfg.history, data.get("history", {}), "history"),
            paths=_merge(cfg.paths, data.get("paths", {}), "paths"),
        )
