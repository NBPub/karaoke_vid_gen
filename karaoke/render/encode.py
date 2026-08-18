from __future__ import annotations
import json
import os
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import List
from karaoke.config import Config


def _audio_codec(audio_path: str) -> str:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_name", "-of", "json", str(audio_path)],
        capture_output=True, text=True, check=True,
    )
    streams = json.loads(out.stdout).get("streams", [])
    return streams[0]["codec_name"] if streams else ""


def needs_reencode(audio_path: str) -> bool:
    return _audio_codec(audio_path) != "aac"


def audio_duration(audio_path: str) -> float:
    """Duration of an audio file in seconds (via ffprobe)."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


@lru_cache(maxsize=1)
def _has_nvenc() -> bool:
    """Whether this ffmpeg build exposes the h264_nvenc encoder."""
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                             capture_output=True, text=True, check=True)
        return "h264_nvenc" in out.stdout
    except Exception:
        return False


def _video_codec(config: Config) -> str:
    """Resolve the configured video_codec ("auto"/"nvenc"/"libx264") to an ffmpeg
    encoder name. "auto" picks NVENC when available, else libx264."""
    vc = config.render.video_codec
    if vc == "nvenc":
        return "h264_nvenc"
    if vc == "libx264":
        return "libx264"
    return "h264_nvenc" if _has_nvenc() else "libx264"


def build_ffmpeg_cmd(frame_pattern: str, audio_path: str, out_mp4: str,
                     config: Config, reencode: bool, lead_in: float = 0.0,
                     video_codec: str = "libx264",
                     title: str | None = None) -> List[str]:
    # The video's title tag defaults to the song folder name (the mp4's parent).
    if title is None:
        title = Path(out_mp4).parent.name
    cmd = [
        # Quiet but with progress: drop the version/config banner and the
        # input/output stream dumps (loglevel error), but keep the single
        # updating progress line (-stats forces it on despite the log level).
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-stats", "-y",
        "-framerate", str(config.render.fps), "-i", frame_pattern,
        "-i", str(audio_path),
    ]
    if video_codec == "h264_nvenc":
        cmd += ["-c:v", "h264_nvenc", "-preset", "p4",
                "-cq", str(config.render.nvenc_cq), "-pix_fmt", "yuv420p"]
    else:
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    cmd += ["-shortest"]
    if lead_in > 0:
        # Delay the audio so it starts after the title card / read buffer. adelay
        # prepends silence; it's a filter, so the audio is re-encoded (caller sets
        # reencode=True for lead_in > 0).
        cmd += ["-af", f"adelay={int(round(lead_in * 1000))}:all=1"]
    if reencode:
        cmd += ["-c:a", "aac", "-b:a", config.audio.bitrate]
    else:
        cmd += ["-c:a", "copy"]
    if title:
        cmd += ["-metadata", f"title={title}"]
    cmd += [str(out_mp4)]
    return cmd


def encode(frame_pattern: str, audio_path: str, out_mp4: str, config: Config,
           lead_in: float = 0.0) -> str:
    reencode = needs_reencode(audio_path) or lead_in > 0
    codec = _video_codec(config)
    out_path = Path(out_mp4)
    # Encode to a sibling temp file, then os.replace() it onto the destination
    # only on success. An interrupted (Ctrl+C) or failed encode — including the
    # NVENC->libx264 fallback — then leaves any existing render untouched instead
    # of overwriting it with a partial file. A same-directory temp keeps the
    # replace atomic; ffmpeg streams to disk exactly as before (no extra memory).
    fd, tmp = tempfile.mkstemp(dir=str(out_path.parent),
                               prefix=f".{out_path.stem}-", suffix=".partial.mp4")
    os.close(fd)
    try:
        cmd = build_ffmpeg_cmd(frame_pattern, audio_path, tmp, config, reencode,
                               lead_in, video_codec=codec)
        try:
            subprocess.run(cmd, check=True)
            used = codec
        except subprocess.CalledProcessError:
            # An auto-selected NVENC encode can fail on driver/session limits;
            # retry once on CPU. A user-forced codec is not silently switched.
            if codec == "h264_nvenc" and config.render.video_codec == "auto":
                subprocess.run(build_ffmpeg_cmd(frame_pattern, audio_path, tmp,
                                                config, reencode, lead_in,
                                                video_codec="libx264"), check=True)
                used = "libx264"
            else:
                raise
        os.replace(tmp, out_mp4)
        return used
    except BaseException:
        # Includes KeyboardInterrupt: drop the partial temp, keep the old render.
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
