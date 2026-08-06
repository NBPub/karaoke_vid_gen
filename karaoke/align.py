from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Protocol, Set, Tuple
from karaoke.lyrics import parse_lyrics
from karaoke.timing import Timing, Line, Word


class Aligner(Protocol):
    def align(self, vocals_path: Path, lines: List[str]) -> Timing: ...


def _normalize_word(word: str, valid: Set[str]) -> str:
    """Reduce a display word to only characters in the aligner's vocabulary.

    The MMS_FA forced aligner rejects any token equal to the blank index, and
    maps out-of-vocabulary characters (notably hyphens) to it. Keep only valid
    characters; a word with none (e.g. a stray "-") normalizes to "".
    """
    return "".join(c for c in word.lower() if c in valid)


def _fill_word_timings(flat_words: List[str],
                       aligned: Dict[int, Tuple[float, float]]) -> List[Word]:
    """Build Words for every display word.

    Words present in `aligned` (index -> (start, end)) use those times. Words
    that could not be aligned (empty after normalization) get a zero-length span
    at the end of the most recent aligned word, so display order and per-line
    word counts are preserved without breaking timing monotonicity.
    """
    words: List[Word] = []
    last_end = 0.0
    for i, w in enumerate(flat_words):
        if i in aligned:
            start, end = aligned[i]
            words.append(Word(text=w, start=float(start), end=float(end)))
            last_end = float(end)
        else:
            words.append(Word(text=w, start=last_end, end=last_end))
    return words


def _trim_wav(vocals_wav: Path, start_seconds: float) -> Path:
    """Write a temp wav of `vocals_wav` from `start_seconds` to its end; return it."""
    import os, tempfile
    import soundfile as sf
    data, sr = sf.read(str(vocals_wav))
    start = max(0, int(start_seconds * sr))
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    sf.write(path, data[start:], sr)
    return Path(path)


def align_song(vocals_wav: Path, lyrics_txt: Path, timing_out: Path,
               aligner: Aligner, *, onset_snap: bool = False,
               onset_lookback: float = 0.25, lead_seconds: float = 0.0,
               first_line_seconds: float | None = None,
               first_line_pad: float = 1.0) -> Timing:
    lines = parse_lyrics(Path(lyrics_txt).read_text(encoding="utf-8"))
    if not lines:
        raise ValueError(f"No lyrics to align in {lyrics_txt}")
    if first_line_seconds is not None:
        # Seed the start: trim the misleading lead-in, align, then offset back so
        # times sit on the full-stem timeline. Aligner-agnostic.
        from karaoke.fill import shift_all
        trim_start = max(0.0, first_line_seconds - first_line_pad)
        clip = _trim_wav(Path(vocals_wav), trim_start)
        try:
            timing = aligner.align(clip, lines)
        finally:
            clip.unlink(missing_ok=True)
        timing = shift_all(timing, trim_start)
    else:
        timing = aligner.align(Path(vocals_wav), lines)
    if onset_snap or lead_seconds:
        from karaoke.onsets import refine_timing
        timing = refine_timing(timing, Path(vocals_wav), onset_snap=onset_snap,
                               lookback=onset_lookback, lead=lead_seconds)
    Path(timing_out).write_text(timing.to_json(), encoding="utf-8")
    return timing


def _align_mono_waveform(artifacts, waveform, words: List[str]) -> Dict[int, Tuple[float, float]]:
    """Forced-align `words` to a mono `waveform` already at the bundle sample
    rate. `artifacts` is (model, tokenizer, aligner, valid_chars, sample_rate).
    Returns {word_index: (start_sec, end_sec)} relative to the waveform start,
    for words with at least one vocabulary character (others are omitted)."""
    import torch
    model, tokenizer, aligner, valid, sample_rate = artifacts
    norm = [_normalize_word(w, valid) for w in words]
    alignable = [i for i, n in enumerate(norm) if n]
    if not alignable:
        return {}
    with torch.inference_mode():
        emission, _ = model(waveform)
        token_spans = aligner(emission[0], tokenizer([norm[i] for i in alignable]))
    sec_per_frame = waveform.size(1) / emission.size(1) / sample_rate
    return {idx: (sec_per_frame * spans[0].start, sec_per_frame * spans[-1].end)
            for idx, spans in zip(alignable, token_spans)}


class TorchAudioAligner:
    """CTC forced alignment of known text via torchaudio's MMS_FA bundle.

    Aligns the full known transcript to the audio (no seed timestamps needed),
    then groups token spans back into the original per-line word structure.
    """

    def __init__(self, device: str = "cuda"):
        self.device = device

    def align(self, vocals_path: Path, lines: List[str]) -> Timing:
        import torch, torchaudio
        from torchaudio.pipelines import MMS_FA as bundle

        device = self.device if torch.cuda.is_available() else "cpu"
        artifacts = (bundle.get_model().to(device), bundle.get_tokenizer(),
                     bundle.get_aligner(),
                     {c for c, idx in bundle.get_dict().items() if idx != 0},
                     bundle.sample_rate)

        waveform, sr = torchaudio.load(str(vocals_path))
        waveform = torchaudio.functional.resample(waveform, sr, bundle.sample_rate)
        waveform = waveform.mean(dim=0, keepdim=True).to(device)  # mono

        words_per_line = [ln.split() for ln in lines]
        flat_words = [w for line_words in words_per_line for w in line_words]
        aligned = _align_mono_waveform(artifacts, waveform, flat_words)
        if not aligned:
            raise ValueError("No alignable words after normalization")

        timed = _fill_word_timings(flat_words, aligned)

        out_lines, i = [], 0
        for line_words in words_per_line:
            n = len(line_words)
            out_lines.append(Line(words=timed[i:i + n]))
            i += n
        return Timing(lines=out_lines)


def _select_transcript(known_words: List[str], candidates: List[list],
                       margin_frac: float = 0.03) -> list:
    """Pick the best of several ASR draws (candidates[0] is the greedy draw).

    Keep the reliable greedy draw unless another draw anchors meaningfully more
    known words — at least ``margin_frac`` beyond greedy — so we don't trade a
    precise greedy result for a marginally-higher but possibly sloppier sample.
    """
    from karaoke.reconcile import anchor_count
    counts = [anchor_count(known_words, c) for c in candidates]
    base = counts[0]
    best = 0
    for i, c in enumerate(counts):
        if c > counts[best] and c >= base * (1.0 + margin_frac):
            best = i
    return candidates[best]


class WhisperAligner:
    """Whisper ASR anchors + reconciliation against the known lyrics.

    Transcribes the vocal stem with word timestamps, then maps the known lyric
    words onto those ASR timings (see karaoke.reconcile). Because anchors are
    spread across the song, a mishandled patch (repeated/screamed choruses)
    stays local instead of drifting the rest of the track, which is the failure
    mode of single-pass CTC forced alignment (TorchAudioAligner).

    The greedy (temperature 0) draw is used by default for reproducibility. With
    ``best_of_n`` > 1, that many extra sampled draws are taken and the one that
    anchors the most known words is kept (helps screamed/messy vocals; the greedy
    draw is always in the pool, so quality never drops below it).
    """

    def __init__(self, model: str = "medium", device: str = "cuda",
                 best_of_n: int = 1, sample_temperature: float = 0.4):
        self.model = model
        self.device = device
        self.best_of_n = max(1, best_of_n)
        self.sample_temperature = sample_temperature

    def align(self, vocals_path: Path, lines: List[str]) -> Timing:
        import torch
        import whisper
        from karaoke.reconcile import reconcile, AsrWord

        asr = whisper.load_model(self.model, device=self.device)
        fp16 = (self.device == "cuda")

        def draw(temperature: float, seed: int) -> list:
            torch.manual_seed(seed)
            result = asr.transcribe(str(vocals_path), word_timestamps=True,
                                    fp16=fp16, temperature=temperature)
            return [AsrWord(w["word"].strip(), float(w["start"]), float(w["end"]))
                    for seg in result.get("segments", [])
                    for w in seg.get("words", [])]

        words_per_line = [ln.split() for ln in lines]
        flat = [w for line_words in words_per_line for w in line_words]

        candidates = [draw(0.0, 0)]  # greedy, reproducible
        for s in range(1, self.best_of_n):
            candidates.append(draw(self.sample_temperature, s))
        asr_words = _select_transcript(flat, candidates)

        times = reconcile(flat, asr_words)
        timed = [Word(flat[k], float(times[k][0]), float(times[k][1]))
                 for k in range(len(flat))]

        out_lines, i = [], 0
        for line_words in words_per_line:
            n = len(line_words)
            out_lines.append(Line(words=timed[i:i + n]))
            i += n
        return Timing(lines=out_lines)
