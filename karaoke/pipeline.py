from __future__ import annotations
import os
from pathlib import Path
from typing import Callable, Optional
from karaoke.config import Config
from karaoke.paths import SongPaths
from karaoke.metadata import TrackMeta, parse_folder_name, read_tags, resolve_metadata
from karaoke import acquire as acquire_mod
from karaoke import separate as separate_mod
from karaoke import lyrics as lyrics_mod
from karaoke import align as align_mod
from karaoke import history
from karaoke.render import get_renderer


def run_stage(name: str, output: Path, work: Callable[[], None], force: bool) -> bool:
    """Run ``work`` for ``name``, unless its output already exists and not forced.
    Returns True if the work actually ran, False if it was skipped."""
    if output.exists() and not force:
        print(f"[skip] {name}: {output} exists (use --force to redo)")
        return False
    print(f"[run]  {name}")
    work()
    return True


def run_stage_multi(name: str, outputs, work: Callable[[], None], force: bool) -> None:
    """Like run_stage, but the stage produces several outputs; skip only when
    all of them already exist."""
    outputs = list(outputs)
    if outputs and all(Path(o).exists() for o in outputs) and not force:
        print(f"[skip] {name}: {len(outputs)} output(s) exist (use --force to redo)")
        return
    print(f"[run]  {name}")
    work()


def run_acquire(source, sp: SongPaths, cfg: Config, force=False):
    sp.ensure()
    run_stage("acquire", sp.song,
              lambda: acquire_mod.acquire(source, sp.song, cfg.audio.sample_rate),
              force)


def run_separate(sp: SongPaths, cfg: Config, supplied_instrumental=None, force=False):
    run_stage("separate", sp.instrumental,
              lambda: separate_mod.separate(sp.song, sp.instrumental, sp.vocals,
                                            cfg, supplied_instrumental,
                                            no_extract_file=sp.no_extract),
              force)


def run_lyrics(sp: SongPaths, meta: TrackMeta, force=False):
    if sp.lyrics_txt.exists() and sp.lyrics_txt.read_text(encoding="utf-8").strip() and not force:
        print(f"[skip] lyrics: {sp.lyrics_txt} exists (use --force to redo)")
        return
    if force and sp.lyrics_txt.exists():
        sp.lyrics_txt.unlink()
    print("[run]  lyrics")
    ok = lyrics_mod.ensure_lyrics(meta, sp.lyrics_txt)
    if not ok:
        print(f"[action needed] paste lyrics into {sp.lyrics_txt}, then re-run")


def _build_aligner(model: str, cfg: Config):
    """The single aligner factory, keyed by model name: "mms" (or legacy
    "torchaudio") -> MMS_FA single-pass CTC forced alignment; anything else ->
    Whisper (ASR word-timestamp anchors + reconciliation against the lyrics)."""
    if model in ("mms", "torchaudio"):
        return align_mod.TorchAudioAligner(cfg.models.device)
    return align_mod.WhisperAligner(
        cfg.models.whisper_model, cfg.models.device,
        best_of_n=cfg.align.best_of_n,
        sample_temperature=cfg.align.sample_temperature)


def make_aligner(cfg: Config):
    """Construct the aligner backend named in config (default: Whisper)."""
    return _build_aligner(cfg.models.aligner, cfg)


def _whisper_params(cfg: Config, model: str) -> str:
    """History tag for the Whisper aligner's settings ("" for MMS)."""
    return (f"{cfg.models.whisper_model};bestof{cfg.align.best_of_n}"
            if model == "whisper" else "")


def run_align(sp: SongPaths, cfg: Config, force=False, first_line=None, model=None):
    """Align to timing.json. `model` ("whisper"/"mms") overrides the aligner for
    this run; None uses the configured default (cfg.models.aligner)."""
    import time

    def work():
        t0 = time.monotonic()
        chosen = model or ("mms" if cfg.models.aligner in ("mms", "torchaudio") else "whisper")
        align_mod.align_song(
            sp.vocals, sp.lyrics_txt, sp.timing_json, _build_aligner(chosen, cfg),
            onset_snap=cfg.align.onset_snap,
            onset_lookback=cfg.align.onset_lookback_seconds,
            lead_seconds=cfg.align.lead_seconds,
            first_line_seconds=first_line,
            first_line_pad=cfg.align.first_line_pad_seconds)
        sp.timing_baseline.write_text(
            sp.timing_json.read_text(encoding="utf-8"), encoding="utf-8")
        history.append_row(
            sp, cfg, "align", duration_s=time.monotonic() - t0,
            model=chosen,
            seed=("" if first_line is None else str(first_line)),
            source=("align-seeded" if first_line is not None else "align-cold"),
            whisper_params=_whisper_params(cfg, chosen))
    run_stage("align", sp.timing_json, work, force)


def resolve_render_duration(last_word_end: float, audio_duration: float, *,
                            full: bool = False, tail: Optional[float] = None,
                            threshold: float = 60.0) -> Optional[float]:
    """Decide how long the rendered video should be.

    - explicit ``tail``: end ``tail`` seconds after the last lyric (capped at audio).
    - ``full``: the entire song.
    - otherwise: the full song when the trailing instrumental is within
      ``threshold`` seconds of the last lyric; if it's longer, return None to
      signal the caller should ask the user.
    """
    if tail is not None:
        return min(last_word_end + tail, audio_duration)
    if full:
        return audio_duration
    if audio_duration - last_word_end <= threshold:
        return audio_duration
    return None


def _targets_by_mode(karaoke, review, mode: str):
    """Select (audio, output) pairs by output mode: "karaoke" → just the
    instrumental video, "review" → just the full-audio copy, "both" → both."""
    if mode == "karaoke":
        return [karaoke]
    if mode == "review":
        return [review]
    return [karaoke, review]


def render_targets(sp: SongPaths, cfg: Config, mode: str):
    """Audio/output pairs to mux from the shared frames, by output mode."""
    return _targets_by_mode((sp.instrumental, sp.output_mp4),
                            (sp.song, sp.review_mp4), mode)


def ab_render_targets(sp: SongPaths, model: str, mode: str):
    """Like render_targets but to labeled A/B names, so canonical files stay
    untouched."""
    return _targets_by_mode((sp.instrumental, sp.ab_output(model)),
                            (sp.song, sp.ab_review(model)), mode)


def _encoder_label(codec: str) -> str:
    if codec == "h264_nvenc":
        return "nvenc (GPU)"
    if codec == "libx264":
        return "libx264 (CPU)"
    return codec or ""


def run_render(sp: SongPaths, cfg: Config, force=False, full=False, tail=None,
               mode=None, confirm_full_outro=None, timing_path=None, targets=None,
               review_outs=None, history_extra=None):
    from karaoke.render import RenderContext
    from karaoke.render.encode import audio_duration
    from karaoke.timing import Timing
    from karaoke.fill import lead_in_seconds, shift_all
    from karaoke.metadata import parse_folder_name

    # Defaults reproduce normal behavior; the `ab` command overrides these to
    # render a labeled timing (e.g. timing.whisper.json) to a labeled output
    # without touching the canonical files.
    targets = targets if targets is not None else render_targets(sp, cfg, mode or cfg.render.mode)
    review_outs = review_outs if review_outs is not None else {sp.review_mp4}

    def work():
        timing = Timing.from_json((timing_path or sp.timing_json).read_text(encoding="utf-8"))
        last = timing.lines[-1].end
        adur = audio_duration(str(sp.instrumental))
        song_duration = resolve_render_duration(
            last, adur, full=full, tail=tail,
            threshold=cfg.render.outro_threshold_seconds)
        if song_duration is None:
            gap = adur - last
            use_full = confirm_full_outro(gap) if confirm_full_outro else True
            song_duration = adur if use_full else min(last + cfg.render.tail_seconds, adur)

        r = cfg.render
        w0 = timing.lines[0].words[0].start
        base_lead_in = (lead_in_seconds(w0, r.title_seconds, r.title_read_buffer_seconds)
                        if r.title_card else 0.0)
        meta = parse_folder_name(sp.root.name)
        renderer = get_renderer(cfg)

        # The review copy keeps timing.json's time-base so times read off it map
        # straight back to the file. The prepended lead-in (and the title card it
        # buys read-time for) is the only thing that breaks that mapping, so the
        # review pass drops both — but only when a lead-in would actually apply
        # (lyrics start early). When it wouldn't, review and karaoke are identical
        # and share one frame pass.
        variants: dict = {}
        for audio, out in targets:
            review = out in review_outs
            lead_in = 0.0 if (review and base_lead_in > 0) else base_lead_in
            title = not (review and base_lead_in > 0)
            variants.setdefault((lead_in, title), []).append((audio, out))

        import time
        t0 = time.monotonic()
        used_codecs = []
        for (lead_in, title), grp in variants.items():
            shifted = shift_all(timing, lead_in)
            ctx = RenderContext(meta=meta, lead_in=lead_in,
                                song_duration=song_duration, title=title)
            codecs = renderer.render(shifted, grp, cfg, song_duration + lead_in, ctx)
            if codecs:
                used_codecs.extend(codecs)
        # Normal renders describe themselves from the song's prior history
        # (the canonical align/keep row). The `ab` command renders labeled
        # timings instead, so it passes explicit provenance + an "ab-gen" note
        # via history_extra (read-back would mislabel the MMS render as the
        # canonical whisper).
        notes = ""
        if history_extra is not None:
            extra = dict(history_extra)
            notes = extra.pop("notes", "")
            prov = {f: extra.get(f, "") for f in history.PROV_FIELDS}
        else:
            prov = history.current_provenance(sp)
        history.append_row(
            sp, cfg, "render", duration_s=time.monotonic() - t0, **prov,
            render_mode=(mode or cfg.render.mode),
            encoder=_encoder_label(used_codecs[0] if used_codecs else ""),
            notes=notes)

    run_stage_multi("render", [out for _, out in targets], work, force)


def resolve_song_meta(sp: SongPaths, override: Optional[TrackMeta]) -> TrackMeta:
    tags = read_tags(sp.song) if sp.song.exists() else TrackMeta()
    return resolve_metadata(override, tags, parse_folder_name(sp.root.name))


# --- aligner A/B (Whisper vs MMS) -----------------------------------------

AB_MODELS = ("whisper", "mms")


def _reusable_model(sp: SongPaths) -> str | None:
    """The model whose pristine initial alignment can be reused as an A/B arm:
    history shows an unmodified `align` (its model) AND timing.json is byte-
    identical to timing.baseline.json (guards against raw hand-edits that skip
    history). None otherwise."""
    m = history.pristine_align_model(sp)
    if m is None:
        return None
    if not (sp.timing_json.exists() and sp.timing_baseline.exists()):
        return None
    if sp.timing_json.read_text(encoding="utf-8") != sp.timing_baseline.read_text(encoding="utf-8"):
        return None
    return m


def _reuse_initial_render(sp: SongPaths, cfg: Config, model: str) -> bool:
    """Copy the canonical render(s) to `model`'s labeled A/B names when the
    initial render was full-length (trailing gap <= outro threshold, matching
    run_ab's full render) and every needed output exists. All-or-nothing; returns
    whether renders were reused."""
    import shutil
    from karaoke.timing import Timing
    from karaoke.render.encode import audio_duration
    timing = Timing.from_json(sp.timing_json.read_text(encoding="utf-8"))
    last = timing.lines[-1].end
    if audio_duration(str(sp.instrumental)) - last > cfg.render.outro_threshold_seconds:
        return False
    pairs = []
    for _audio, out in ab_render_targets(sp, model, cfg.render.mode):
        src = sp.output_mp4 if out == sp.ab_output(model) else sp.review_mp4
        if not src.exists():
            return False
        pairs.append((src, out))
    for src, out in pairs:
        shutil.copyfile(src, out)
    return True


def _timing_matches_lyrics(sp: SongPaths) -> bool:
    """True when the canonical timing's words still equal lyrics.txt's — the
    precondition for reusing the alignment. A word-level lyric edit makes this
    False (the timing is stale relative to the lyrics), so reuse is skipped and
    both aligners re-run. Cosmetic edits that keep the same words (line breaks,
    whitespace) still match — those are a `split` concern, not an alignment one."""
    from karaoke import linesplit
    from karaoke.lyrics import parse_lyrics
    from karaoke.timing import Timing
    if not sp.lyrics_txt.exists():
        return False
    lyrics_lines = parse_lyrics(sp.lyrics_txt.read_text(encoding="utf-8"))
    if not lyrics_lines:
        return False
    try:
        timing = Timing.from_json(sp.timing_json.read_text(encoding="utf-8"))
    except Exception:
        return False
    return linesplit.words_match(timing, lyrics_lines)


def _reuse_initial_arm(sp: SongPaths, cfg: Config, *, render: bool = True) -> str | None:
    """If the canonical timing is a pristine align (see _reusable_model), its
    words still match lyrics.txt, and its labeled arm isn't already materialized,
    seed that arm by copying: the timing always, the render(s) when full-length.
    Returns the reused model, else None. Canonical files are never modified."""
    import shutil
    m = _reusable_model(sp)
    if m is None or sp.ab_timing(m).exists():
        return None
    if not _timing_matches_lyrics(sp):
        # lyrics.txt was edited since the alignment (word change) — the initial
        # timing is stale, so re-align both arms instead of reusing it.
        print("[ab] lyrics.txt no longer matches the initial alignment; "
              "re-aligning both models.")
        return None
    shutil.copyfile(sp.timing_json, sp.ab_timing(m))
    reused_render = _reuse_initial_render(sp, cfg, m) if render else False
    print(f"[ab] reusing the initial {m} alignment"
          + (" + render" if reused_render else "")
          + "; only the other aligner will run")
    return m


def run_ab(sp: SongPaths, cfg: Config, *, first_line=None, render=True, force=False):
    """Generate both aligners' timings (and, by default, review videos) under
    labeled names (timing.<model>.json / karaoke.review.<model>.mp4). Never
    creates or overwrites the canonical timing.json, timing.baseline.json, or
    karaoke.review.mp4 — use `ab_keep` to consolidate the chosen one."""
    seed = "" if first_line is None else str(first_line)
    if not force:
        _reuse_initial_arm(sp, cfg, render=render)
    for model in AB_MODELS:
        tpath = sp.ab_timing(model)
        run_stage(
            f"ab align [{model}]", tpath,
            lambda tpath=tpath, model=model: align_mod.align_song(
                sp.vocals, sp.lyrics_txt, tpath, _build_aligner(model, cfg),
                onset_snap=cfg.align.onset_snap,
                onset_lookback=cfg.align.onset_lookback_seconds,
                lead_seconds=cfg.align.lead_seconds,
                first_line_seconds=first_line,
                first_line_pad=cfg.align.first_line_pad_seconds),
            force)
        if render:
            # Render per the configured mode, to labeled targets. Each labeled
            # render logs its own history row tagged "ab-gen", so the model
            # column distinguishes whisper from mms; there is no separate ab-gen
            # op row. (Per-render wall-times won't sum to the whole A/B run —
            # they're a rough reference, not exact accounting.)
            run_render(sp, cfg, force=force, full=True,
                       timing_path=tpath,
                       targets=ab_render_targets(sp, model, cfg.render.mode),
                       review_outs={sp.ab_review(model)},
                       history_extra={
                           "model": model, "seed": seed,
                           "source": ("ab-seeded" if first_line is not None
                                      else "ab-cold"),
                           "whisper_params": _whisper_params(cfg, model),
                           "notes": "ab-gen"})
    labeled = ", ".join(sp.ab_timing(m).name for m in AB_MODELS)
    print(f"[ab] generated {labeled}" + (" + videos" if render else ""))
    print(f"[ab] review them, then you MUST run "
          f"karaoke ab \"{sp.root.name}\" --keep {'|'.join(AB_MODELS)} "
          f"before nudging or finalizing.")
    print("[ab] the current timing.json + review video stay untouched until "
          "--keep replaces them with the chosen model (and removes the labeled files).")


def run_split(sp: SongPaths, cfg: Config, force: bool = False) -> None:
    """Fit too-wide lines. (1) Re-segment timing.json to lyrics.txt's line
    structure when the words match (else refuse -> re-align). (2) Auto-split any
    line still wider than usable into balanced rows, marking continuation rows
    wrap=True (timing.json only). Backs up to .bak; logs a `split` history row."""
    import time
    from karaoke import linesplit, preflight
    from karaoke.timing import Timing, Line
    from karaoke.lyrics import parse_lyrics
    if not sp.timing_json.exists():
        raise FileNotFoundError(
            f"no timing.json for '{sp.root.name}'; run `align` first.")
    t0 = time.monotonic()
    original = sp.timing_json.read_text(encoding="utf-8")
    timing = Timing.from_json(original)

    resegmented = 0
    if sp.lyrics_txt.exists():
        lyrics_lines = parse_lyrics(sp.lyrics_txt.read_text(encoding="utf-8"))
        if lyrics_lines:
            if not linesplit.words_match(timing, lyrics_lines):
                raise ValueError(
                    "lyrics.txt words differ from timing.json — run `align` to "
                    "rebuild timing from the new lyrics. (A split only moves line "
                    "boundaries; word edits need re-alignment.)")
            counts = [len(l.split()) for l in lyrics_lines]
            before = len(timing.lines)
            timing = linesplit.resegment(timing, counts)
            resegmented = len(timing.lines) - before

    measure = preflight._line_measurer(cfg)
    usable = cfg.render.width * cfg.render.usable_width_frac
    out_lines, wrapped = [], 0
    for ln in timing.lines:
        text = "".join(w.text + " " for w in ln.words)
        if measure(text) > usable:
            rows = linesplit.balanced_wrap(ln.words, measure, usable)
            if len(rows) > 1:
                wrapped += 1
                out_lines.append(Line(words=rows[0]))
                out_lines.extend(Line(words=r, wrap=True) for r in rows[1:])
                continue
        out_lines.append(ln)
    result = Timing(lines=out_lines)

    sp.timing_json.with_suffix(".json.bak").write_text(original, encoding="utf-8")
    sp.timing_json.write_text(result.to_json(), encoding="utf-8")
    history.append_row(sp, cfg, "split", duration_s=time.monotonic() - t0,
                       **history.current_provenance(sp),
                       notes=f"re-segment {resegmented:+d} line(s), "
                             f"auto-wrapped {wrapped} line(s)")
    print(f"[split] re-segment {resegmented:+d} line(s); auto-wrapped {wrapped} "
          f"line(s); backup at {sp.timing_json.name}.bak")


def ab_keep(sp: SongPaths, model: str, cfg: Config = None):  # cfg added for history logging
    """Promote the chosen A/B model to canonical (timing.json + baseline +
    karaoke.review.mp4) and remove the other model's labeled files."""
    if model not in AB_MODELS:
        raise ValueError(
            f"unknown model '{model}'; choose one of: {', '.join(AB_MODELS)}")
    tpath = sp.ab_timing(model)
    if not tpath.exists():
        raise FileNotFoundError(
            f"no {tpath.name} for '{sp.root.name}'. "
            f"Run `karaoke ab \"{sp.root.name}\"` first to generate the A/B versions.")
    content = tpath.read_text(encoding="utf-8")
    sp.timing_json.write_text(content, encoding="utf-8")
    sp.timing_baseline.write_text(content, encoding="utf-8")
    tpath.unlink()
    promoted = []
    for src, dst in ((sp.ab_output(model), sp.output_mp4),
                     (sp.ab_review(model), sp.review_mp4)):
        if src.exists():
            os.replace(src, dst)
            promoted.append(dst.name)
    removed = []
    for other in AB_MODELS:
        if other == model:
            continue
        for p in (sp.ab_timing(other), sp.ab_output(other), sp.ab_review(other)):
            if p.exists():
                p.unlink()
                removed.append(p.name)
    if cfg is not None:
        # Scope to the KEPT model's ab-gen rows, so a whisper keep carries its
        # Whisper params and an mms keep carries none (not the other model's).
        prov = history.current_provenance(sp, model=model)
        history.append_row(sp, cfg, "ab-keep", model=model, source="ab-keep",
                           seed=prov.get("seed", ""), whisper_params=prov.get("whisper_params", ""),
                           notes=f"kept {model}")
    print(f"[ab] kept {model} -> {sp.timing_json.name}"
          + (f" + {', '.join(promoted)}" if promoted else "")
          + (f"; removed {', '.join(removed)}" if removed else ""))
