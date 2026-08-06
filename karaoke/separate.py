from __future__ import annotations
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional
from karaoke.config import Config


def _mmss(t: float) -> str:
    """Seconds -> M:SS.s for the no_extract readout (e.g. 150.0 -> '2:30.0')."""
    return f"{int(t // 60)}:{t % 60:04.1f}"


def _run_demucs(song_path: Path, out_dir: Path, model: str, device: str) -> Path:
    """Run demucs two-stems (FLAC output); return the directory containing the
    stem FLACs."""
    subprocess.run(
        [sys.executable, "-m", "demucs", "--two-stems", "vocals", "--flac",
         "-n", model, "-d", device, "-o", str(out_dir), str(song_path)],
        check=True,
    )
    return out_dir / model / song_path.stem


def _resolve_instrumental_source(src: str, workdir: Path) -> Path:
    """A supplied instrumental may be a local file or a URL (downloaded)."""
    from karaoke.acquire import is_url, _download_audio
    if is_url(src):
        return _download_audio(src, workdir / "_supplied")
    return Path(src)


def separate(song: Path, instrumental_out: Path, vocals_out: Path,
             config: Config, supplied_instrumental: Optional[str] = None,
             no_extract_file: Optional[Path] = None) -> None:
    """Stage 2: produce instrumental.flac and vocals.flac."""
    song = Path(song)
    with tempfile.TemporaryDirectory() as tmp:
        stem_dir = _run_demucs(song, Path(tmp),
                               config.models.demucs_model, config.models.device)
        shutil.copyfile(stem_dir / "vocals.flac", vocals_out)

        nx_text = ""
        if no_extract_file is not None and Path(no_extract_file).exists():
            nx_text = Path(no_extract_file).read_text(encoding="utf-8")

        if supplied_instrumental:
            src = _resolve_instrumental_source(supplied_instrumental, Path(tmp))
            shutil.copyfile(src, instrumental_out)
            if nx_text.strip():
                print("[no_extract] no_extract.txt ignored (supplied instrumental "
                      "used as-is).")
            return

        no_vocals = stem_dir / "no_vocals.flac"
        if nx_text.strip():
            import soundfile as sf
            from karaoke import no_extract as nx
            song_data, sr = sf.read(str(song))
            try:
                intervals = nx.parse_intervals(nx_text, duration=len(song_data) / sr)
            except ValueError as e:
                # Malformed line / bad time / start>=end: don't crash after the
                # expensive separation — warn and ship the plain instrumental.
                print(f"[no_extract] could not read no_extract.txt: {e}")
                print("[no_extract] no spans applied - fix the file and re-run "
                      "`separate --force`.")
                intervals = []
            if intervals:
                instr, _ = sf.read(str(no_vocals))
                m = min(len(instr), len(song_data))
                spliced = nx.splice_original(instr[:m], song_data[:m], sr, intervals)
                # FLAC is integer-only; the stems are PCM_16 (Demucs --flac).
                sf.write(str(instrumental_out), spliced, sr, subtype="PCM_16")
                print(f"[no_extract] original mix kept over {len(intervals)} span(s): "
                      + ", ".join(f"{_mmss(s)}-{_mmss(e)}" for s, e in intervals))
                return
        shutil.copyfile(no_vocals, instrumental_out)
