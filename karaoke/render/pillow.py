from __future__ import annotations
import tempfile
from pathlib import Path
from typing import List, Tuple
from karaoke.config import Config
from karaoke.timing import Timing
from karaoke.render.encode import encode


def frame_times(duration: float, fps: int) -> List[float]:
    """Frame timestamps (seconds) for `duration` at `fps`: 0, 1/fps, 2/fps, …"""
    return [i / fps for i in range(int(duration * fps))]


def _draw_and_save(task):
    """Pool worker: draw one frame and write its PNG. Top-level so it pickles."""
    i, state, config, meta, frames_dir = task
    from karaoke.render.draw import draw_frame
    draw_frame(state, config, meta).save(f"{frames_dir}/{i:06d}.png")


class PillowRenderer:
    """Draw frames directly with Pillow (parallel), then reuse encode() per target."""

    def render(self, timing: Timing, targets: List[Tuple[Path, Path]],
               config: Config, duration: float, ctx=None) -> List[str]:
        if not timing.lines:
            raise ValueError("Timing has no lines to render")
        if not targets:
            raise ValueError("No render targets")
        from karaoke.render import RenderContext, build_frame_state
        if ctx is None:
            ctx = RenderContext(song_duration=duration)

        r = config.render
        times = frame_times(duration, r.fps)
        states = [build_frame_state(timing, t, config, duration, ctx).to_dict()
                  for t in times]

        with tempfile.TemporaryDirectory() as tmp:
            frames_dir = Path(tmp)
            tasks = [(i, states[i], config, ctx.meta, str(frames_dir))
                     for i in range(len(states))]
            if (r.jobs == 1) or len(tasks) <= 1:
                for task in tasks:
                    _draw_and_save(task)
            else:
                import multiprocessing as mp
                n = r.jobs if r.jobs > 0 else (mp.cpu_count() or 1)
                with mp.Pool(n) as pool:
                    pool.map(_draw_and_save, tasks, chunksize=16)

            pattern = str(frames_dir / "%06d.png")
            outputs = [encode(pattern, str(audio), str(out_mp4), config,
                              lead_in=ctx.lead_in)
                       for audio, out_mp4 in targets]
        return outputs
