from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Protocol, Tuple
from pathlib import Path
from karaoke.config import Config
from karaoke.timing import Timing
from karaoke.metadata import TrackMeta

# (audio_path, output_mp4): one muxing target sharing the rendered frames.
Target = Tuple[Path, Path]


@dataclass
class RenderContext:
    """Render-time extras beyond the timing: title-card text, the lead-in delay,
    and the actual-track length the progress bar fills across. `title` lets one
    render pass suppress the title card (the review pass drops it along with the
    lead-in it depends on) without mutating the shared config."""
    meta: TrackMeta = field(default_factory=TrackMeta)
    lead_in: float = 0.0
    song_duration: Optional[float] = None
    title: bool = True


class Renderer(Protocol):
    def render(self, timing: Timing, targets: List[Target], config: Config,
               duration: float, ctx: "RenderContext | None" = None) -> List[str]:
        """Render the frames once, then mux them against each target's audio.
        Returns the video codec actually used for each target (e.g.
        "h264_nvenc" / "libx264"), in target order — for history logging."""
        ...


def get_renderer(config: Config) -> Renderer:
    from karaoke.render.pillow import PillowRenderer
    return PillowRenderer()


def build_frame_state(timing, t: float, config, duration: float, ctx):
    """The single per-frame `frame_state` call shared by every renderer, so the
    backends can't drift. Applies the render config's feature toggles."""
    from karaoke.fill import frame_state
    r = config.render
    return frame_state(
        timing, t, r.lines_per_page,
        duration=(duration if r.wait_bar else None),
        wait_threshold=r.wait_min_gap_seconds,
        wait_bar_end=r.wait_bar_end_seconds,
        wait_highlight=r.wait_highlight_seconds,
        lead_in=ctx.lead_in,
        song_duration=(ctx.song_duration if r.progress_bar else None),
        title_seconds=(r.title_seconds if (r.title_card and ctx.title) else 0.0),
        title_fade=r.title_fade_seconds,
        count_in=r.count_in,
        count_in_threshold=r.count_in_min_gap_seconds,
    )
