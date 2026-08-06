from __future__ import annotations
import time
from pathlib import Path
import click
from karaoke.config import Config
from karaoke.paths import SongPaths
from karaoke.metadata import TrackMeta
from karaoke.timeparse import parse_time as _parse_time
from karaoke import pipeline


_SONG_ARTIFACTS = ("song.flac", "vocals.flac", "instrumental.flac",
                   "lyrics.txt", "timing.json", "history.csv")


def _looks_like_song_folder(root: Path, songs_dir: str) -> bool:
    """A folder is plausibly a song folder if it holds a known karaoke artifact,
    or it sits directly under the configured songs directory."""
    if any((root / name).exists() for name in _SONG_ARTIFACTS):
        return True
    return root.parent.name == Path(songs_dir).name


def _resolve_song_paths(song, songs_dir, cfg) -> SongPaths:
    """Resolve the song folder. Precedence for the songs directory: explicit
    --songs-dir > [paths].songs_dir in config > built-in default. When SONG is
    omitted, infer it from the current directory (guarded)."""
    effective = songs_dir if songs_dir is not None else cfg.paths.songs_dir
    if song:                                   # explicit arg always wins
        return SongPaths.for_song(Path(effective), song)
    root = Path.cwd()
    if _looks_like_song_folder(root, effective):
        return SongPaths(root=root)
    raise click.ClickException(
        "Not inside a song folder. Pass the song name (e.g. \"Artist - Title\") "
        "or cd into songs/<Artist - Title>.")


def _ctx(song, songs_dir, config, *, announce=False):
    cfg = Config.load(Path(config))
    sp = _resolve_song_paths(song, songs_dir, cfg)
    if announce:
        # Surface where files will be written (catches e.g. a stray songs/songs/
        # from running in the wrong directory). Only the create/populate commands
        # pass announce=True.
        click.echo(f"[song]  {sp.root.resolve()}")
    return cfg, sp


def _interactive() -> bool:
    """True when stdin is a real terminal (so prompting the user is sensible).
    False for piped/non-interactive runs, where prompts would hang or error."""
    import sys
    return sys.stdin.isatty()


def _preflight_gate(sp, cfg, context: str, skip: bool, *, force: bool = False):
    """Run the preflight; print findings; abort on errors unless `skip`. Returns
    the (post-filter) findings so callers can act on prompting warnings; returns
    [] when skipped. When `force` (a --force render), the stale_render warning is
    dropped — a forced re-render is exactly its fix, so reporting it is just
    noise."""
    if skip:
        return []
    from karaoke import preflight
    findings = preflight.run_preflight(sp, cfg, context=context)
    if force:
        findings = [f for f in findings if f.code != "stale_render"]
    if findings:
        click.echo(preflight.format_report(findings))
    if preflight.has_errors(findings):
        raise click.ClickException(
            "preflight found problems (above). Fix them, or re-run with --skip-check.")
    return findings


def _maybe_reseparate_for_no_extract(sp, cfg, findings) -> None:
    """Interactive render gate for prompting warnings. Today the only one is
    `stale_no_extract`: offer to run `separate --force` (applying no_extract)
    before rendering; if declined, ask whether to render the stale instrumental
    anyway, else abort. No-op when non-interactive (the warning was still
    printed) or when there's no prompting warning."""
    if not any(f.prompt for f in findings) or not _interactive():
        return
    if not any(f.code == "stale_no_extract" for f in findings):
        return
    if click.confirm("no_extract.txt changed since separation - run `separate` now "
                     "to apply it before rendering?", default=True):
        pipeline.run_separate(sp, cfg, None, force=True)
    elif not click.confirm("Render anyway with the current instrumental?",
                           default=False):
        raise click.ClickException("Aborted. Run `separate --force`, then re-render.")


def _load_forced(sp, cfg):
    """Build a ForcedAligner and read the vocal samples for windowed alignment.
    Returns (forced, samples, sr), or (None, None, None) if torch/torchaudio or
    the model can't be loaded — callers then fall back to interpolation."""
    try:
        import soundfile as sf
        from karaoke.realign import ForcedAligner
        samples, sr = sf.read(str(sp.vocals))
        return ForcedAligner(cfg.models.device), samples, sr
    except Exception:
        return None, None, None


def _log_nudge(sp, cfg, duration_s: float, notes: str) -> None:
    """Append a nudge history row, carrying forward the most-recent provenance."""
    from karaoke import history
    prov = history.current_provenance(sp)
    history.append_row(sp, cfg, "nudge", duration_s=duration_s, **prov, notes=notes)


def _post_nudge_report(sp, cfg) -> None:
    """After a mutating nudge, re-run the preflight and REPORT (never halt) any
    issue the op introduced — e.g. a reflow/shift pushing a line's end past the
    next line's start, which the pre-op gate ran too early to see. The render
    preflight stays the hard gate. stale_render is dropped (a timing write always
    makes the old video stale — expected, not news here)."""
    from karaoke import preflight
    findings = [f for f in preflight.run_preflight(sp, cfg, context="nudge")
                if f.code != "stale_render"]
    if findings:
        click.echo("\npost-nudge check found issue(s) to fix before your next render:")
        click.echo(preflight.format_report(findings))
    else:
        click.echo("post-nudge check: no new issues.")


def _finish_nudge(sp, cfg, old, new, t0, summary, note, idxs) -> None:
    """Shared tail for the mutating nudge ops: back the old timing up to .bak,
    write the new timing, echo `summary`, log a nudge history row with `note`,
    and print each affected line's new start/end + text (in `idxs` order)."""
    sp.timing_json.with_suffix(".json.bak").write_text(old.to_json(), encoding="utf-8")
    sp.timing_json.write_text(new.to_json(), encoding="utf-8")
    click.echo(summary)
    _log_nudge(sp, cfg, time.monotonic() - t0, note)
    for L in idxs:
        ln = new.lines[L]
        click.echo(f"  line {L}: {ln.start:.2f}-{ln.end:.2f}  "
                   f"{' '.join(w.text for w in ln.words)}")
    _post_nudge_report(sp, cfg)


common = [
    click.option("--songs-dir", default=None,
                 help="songs directory [default: [paths].songs_dir in config, or 'songs']"),
    click.option("--config", default="config.toml", show_default=True),
    click.option("--force", is_flag=True, default=False),
]


def add_common(f):
    for opt in reversed(common):
        f = opt(f)
    return f


@click.group()
def cli():
    """Karaoke video generator."""


@cli.command(name="all")
@click.argument("song", required=False, default=None)
@click.argument("source", required=False, default=None)
@click.option("--artist", default=None)
@click.option("--title", default=None)
@click.option("--first-line", "first_line", default=None, metavar="T",
              help="re-align seeded by the first sung line's approx start (m:ss|ss)")
@click.option("--ab", "ab", is_flag=True, default=False,
              help="A/B both aligners (Whisper + MMS) instead of a single "
                   "align+render; stops at the keep gate")
@click.option("--model", default=None,
              help="aligner: whisper | mms (default: models.aligner in config; "
                   "use --ab for both)")
@add_common
def run_all(song, source, artist, title, first_line, ab, model, songs_dir, config, force):
    """Run the full pipeline for SONG (the '<artist> - <title>' folder name),
    ending with an initial review render you can watch before hand-correcting.

    SOURCE is the audio: a URL (e.g. YouTube) or a local audio file path. It's
    prompted for only when acquire still needs to run; the instrumental is
    prompted the same way (blank = AI separation). --ab runs both aligners +
    review videos and stops at the keep gate instead of rendering a single
    canonical timing. The only forced stop is when lyrics can't be auto-fetched:
    add them to lyrics.txt and re-run (finished stages are cached, so it resumes
    where it left off)."""
    cfg, sp = _ctx(song, songs_dir, config, announce=True)
    if ab and model:
        raise click.ClickException(
            "--model selects one aligner; --ab runs both. Use one or the other.")
    _validate_model(model, cfg, ab_hint=True)
    name = sp.root.name
    if not source and (not sp.song.exists() or force):
        source = click.prompt("Audio source (URL or local file path)")
    pipeline.run_acquire(source, sp, cfg, force)
    meta = pipeline.resolve_song_meta(sp, TrackMeta(artist, title))
    pipeline.run_lyrics(sp, meta, force)
    if not sp.lyrics_txt.read_text(encoding="utf-8").strip():
        raise click.ClickException(
            f"Lyrics could not be fetched. Add them to {sp.lyrics_txt}, then "
            f"re-run `karaoke all \"{name}\"` (finished stages are skipped).")
    if sp.instrumental.exists() and not force:
        instrumental = None
    else:
        instrumental = click.prompt(
            "Supplied instrumental (file/URL) or blank for AI",
            default="", show_default=False) or None
    pipeline.run_separate(sp, cfg, instrumental, force)
    fl = _parse_time(first_line) if first_line else None
    if ab:
        pipeline.run_ab(sp, cfg, first_line=fl, render=True, force=force)
        return
    pipeline.run_align(sp, cfg, force, first_line=fl, model=model)
    # Render straight through to an initial copy (output mode follows
    # render.mode in config) — reviewing the timing from a rendered video is
    # easier than reading timing.json. The preflight check is intentionally
    # skipped here (this render is *for* spotting problems); run `check` /
    # `split` / `nudge` before the final render.
    pipeline.run_render(sp, cfg, force=force, confirm_full_outro=_confirm_full_outro)
    outs = ", ".join(out.name for _, out in pipeline.render_targets(sp, cfg, cfg.render.mode))
    click.echo(
        f"Initial render ({cfg.render.mode}): {outs}\n"
        f"Watch it, then refine with `karaoke nudge \"{name}\"` (or hand-edit "
        f"{sp.timing_json.name}) and re-render with "
        f"`karaoke render \"{name}\" --force`.")


@cli.command()
@click.argument("song", required=False, default=None)
@click.argument("source")
@add_common
def acquire(song, source, songs_dir, config, force):
    """Acquire audio for SONG from SOURCE — a URL (e.g. YouTube) or a local audio
    file path — normalizing it to song.flac."""
    cfg, sp = _ctx(song, songs_dir, config, announce=True)
    pipeline.run_acquire(source, sp, cfg, force)


@cli.command()
@click.argument("song", required=False, default=None)
@click.option("--instrumental", default=None, help="file or URL to use as-is")
@add_common
def separate(song, instrumental, songs_dir, config, force):
    cfg, sp = _ctx(song, songs_dir, config, announce=True)
    pipeline.run_separate(sp, cfg, instrumental, force)


@cli.command()
@click.argument("song", required=False, default=None)
@click.option("--artist", default=None)
@click.option("--title", default=None)
@add_common
def lyrics(song, artist, title, songs_dir, config, force):
    cfg, sp = _ctx(song, songs_dir, config, announce=True)
    meta = pipeline.resolve_song_meta(sp, TrackMeta(artist, title))
    pipeline.run_lyrics(sp, meta, force)


@cli.command()
@click.argument("song", required=False, default=None)
@click.option("--first-line", "first_line", default=None, metavar="T",
              help="re-align seeded by the first sung line's approx start (m:ss|ss)")
@click.option("--model", default=None,
              help="aligner for this run: whisper | mms (default: models.aligner in config)")
@add_common
def align(song, first_line, model, songs_dir, config, force):
    cfg, sp = _ctx(song, songs_dir, config, announce=True)
    _validate_model(model, cfg)
    fl = _parse_time(first_line) if first_line else None
    pipeline.run_align(sp, cfg, force, first_line=fl, model=model)


@cli.command()
@click.argument("song", required=False, default=None)
@add_common
def check(song, songs_dir, config, force):
    """Validate SONG's timing.json (+ lyrics/audio) and report problems."""
    from karaoke import preflight
    cfg, sp = _ctx(song, songs_dir, config)
    findings = preflight.run_preflight(sp, cfg, context="standalone")
    click.echo(preflight.format_report(findings))
    if preflight.has_errors(findings):
        raise SystemExit(1)


@cli.command()
@click.argument("song", required=False, default=None)
@click.option("--first-line", "first_line", default=None, metavar="T",
              help="seed both aligns by the first sung line's approx start (m:ss|ss)")
@click.option("--no-render", "no_render", is_flag=True, default=False,
              help="generate timings only; skip the review videos")
@click.option("--keep", "keep", type=click.Choice(["whisper", "mms"]), default=None,
              help="consolidate: promote this model to canonical, remove the other")
@add_common
def ab(song, first_line, no_render, keep, songs_dir, config, force):
    """A/B the two aligners for SONG.

    Generate: `ab "<song>"` writes timing.whisper.json / timing.mms.json (+ review
    videos), never touching the canonical files. Consolidate: `ab "<song>"
    --keep whisper|mms` promotes the chosen one to canonical and removes the rest.
    """
    cfg, sp = _ctx(song, songs_dir, config)
    if keep:
        try:
            pipeline.ab_keep(sp, keep, cfg)
        except (FileNotFoundError, ValueError) as e:
            raise click.ClickException(str(e))
        return
    fl = _parse_time(first_line) if first_line else None
    pipeline.run_ab(sp, cfg, first_line=fl, render=not no_render, force=force)


@cli.command()
@click.argument("song", required=False, default=None)
@click.option("--full", is_flag=True, default=False,
              help="render to the full song length (skip the outro prompt)")
@click.option("--tail", type=float, default=None,
              help="end this many seconds after the last lyric")
@click.option("--mode", type=click.Choice(["both", "karaoke", "review"]), default=None,
              help="which outputs to render: both | karaoke | review [default: from config]")
@click.option("--skip-check", is_flag=True, default=False,
              help="skip the timing.json preflight check")
@add_common
def render(song, full, tail, mode, skip_check, songs_dir, config, force):
    cfg, sp = _ctx(song, songs_dir, config)
    findings = _preflight_gate(sp, cfg, "render", skip_check, force=force)
    _maybe_reseparate_for_no_extract(sp, cfg, findings)
    pipeline.run_render(sp, cfg, force=force, full=full, tail=tail, mode=mode,
                        confirm_full_outro=_confirm_full_outro)


_ALIGNER_MODELS = ("whisper", "mms")


def _validate_model(model, cfg, *, ab_hint=False):
    """Validate an explicit --model (or None). Returns it, or raises a clean error
    listing the options, the configured default, and the config knob."""
    if model is None or model in _ALIGNER_MODELS:
        return model
    default = "mms" if cfg.models.aligner in ("mms", "torchaudio") else "whisper"
    msg = (f"Unknown --model '{model}'. Choose 'whisper' or 'mms'. Omit --model to "
           f"use the configured default (models.aligner = '{default}'), which you "
           f"can change in config.toml.")
    if ab_hint:
        msg += " Use --ab to run both."
    raise click.ClickException(msg)


def _confirm_full_outro(gap):
    """Ask whether to include a long trailing instrumental in the render."""
    return click.confirm(
        f"The instrumental continues {gap:.0f}s after the last lyric. "
        f"Include the full outro?", default=True)


@cli.command()
@click.argument("song", required=False, default=None)
@click.option("--list", "list_lines", is_flag=True, help="print numbered lines + timings")
@click.option("--shift", "shifts", multiple=True, metavar="L=T",
              help="shift line L so it starts at time T (e.g. 8=1:06); repeatable")
@click.option("--copy", "copies", multiple=True, metavar="SRC>DST=T",
              help="copy line SRC's timing onto line DST at time T; repeatable")
@click.option("--anchor", "anchors", multiple=True, metavar="L=T",
              help="pin line L's first word to time T; words between anchors are "
                   "interpolated by length. Repeatable (>=2).")
@click.option("--fill-cleared", "fill_cleared", is_flag=True,
              help="reflow lines you marked in timing.json (first word's end set to 0): "
                   "spread each from its first-word start to the next line")
@click.option("--save-baseline", is_flag=True,
              help="snapshot the current timing.json as the snap-edits baseline")
@click.option("--snap-edits", "snap_edits_flag", is_flag=True,
              help="snap your hand-edited phrases in timing.json onto vocal onsets")
@click.option("--no-snap", is_flag=True, help="use the given times as-is (skip onset snapping)")
@click.option("--interpolate", is_flag=True,
              help="reflow by char-length interpolation instead of forced alignment")
@click.option("--skip-check", is_flag=True, default=False,
              help="skip the timing.json preflight check")
@add_common
def nudge(song, list_lines, shifts, copies, anchors, fill_cleared, save_baseline,
          snap_edits_flag, no_snap, interpolate, skip_check, songs_dir, config, force):
    """Hand-correct timing.json with coarse times snapped to the vocal onset."""
    from karaoke.timing import Timing
    from karaoke import nudge as nudge_mod

    cfg, sp = _ctx(song, songs_dir, config)
    if not list_lines:                      # --list is read-only; no gate
        _preflight_gate(sp, cfg, "nudge", skip_check)
    timing = Timing.from_json(sp.timing_json.read_text(encoding="utf-8"))

    if list_lines:
        for i, ln in enumerate(timing.lines):
            text = " ".join(w.text for w in ln.words)
            click.echo(f"{i:>3} {ln.start:7.2f}-{ln.end:6.2f}  {text}")
        return

    if save_baseline:
        sp.timing_baseline.write_text(timing.to_json(), encoding="utf-8")
        click.echo(f"baseline saved to {sp.timing_baseline.name}")
        return

    if snap_edits_flag:
        if not sp.timing_baseline.exists():
            raise click.ClickException(
                "no baseline to compare against - run `--save-baseline` before editing, "
                "or re-run `align` (which now seeds one).")
        _t0 = time.monotonic()
        baseline = Timing.from_json(sp.timing_baseline.read_text(encoding="utf-8"))
        new_timing, runs, deltas = nudge_mod.snap_edits(
            baseline, timing, sp.vocals, snap=not no_snap)
        if not runs:
            click.echo("no edits detected vs baseline; nothing to do.")
            return
        flat = [w for ln in timing.lines for w in ln.words]
        sp.timing_json.with_suffix(".json.preedit").write_text(
            timing.to_json(), encoding="utf-8")
        sp.timing_json.write_text(new_timing.to_json(), encoding="utf-8")
        sp.timing_baseline.write_text(new_timing.to_json(), encoding="utf-8")
        click.echo(f"snapped {len(runs)} edited phrase(s); raw edit backed up to "
                   f"{sp.timing_json.name}.preedit, baseline updated.")
        _log_nudge(sp, cfg, time.monotonic() - _t0, f"snap-edits: {len(runs)} phrase(s)")
        for run in runs:
            d = deltas.get(run[0], 0.0)
            click.echo(f"  '{flat[run[0]].text}..{flat[run[-1]].text}'  "
                       f"first word {flat[run[0]].start:.2f} -> "
                       f"{flat[run[0]].start + d:.2f}  ({d:+.2f}s)")
        _post_nudge_report(sp, cfg)
        return

    if fill_cleared:
        _t0 = time.monotonic()
        marked = {i: ln.words[0].start for i, ln in enumerate(timing.lines)
                  if nudge_mod.is_marked_for_reflow(ln)}
        if not marked:
            raise click.ClickException(
                "no marked lines - set a line's first-word end to 0 and its "
                "first-word start to the anchor time, then re-run.")
        no_anchor = sorted(L for L, t in marked.items() if t <= 0)
        if no_anchor:
            raise click.ClickException(
                f"line(s) {no_anchor} are marked but have no first-word start time set.")
        forced, samples, sr = (None, None, None) if interpolate else _load_forced(sp, cfg)
        if forced is None and not no_snap:
            # Interpolation path: pre-snap each coarse start to its onset (the
            # forced path doesn't pre-snap — the model owns the search).
            from karaoke.onsets import snap_marks
            marked = snap_marks(sp.vocals, marked)
        new_timing = nudge_mod.reflow_marked(
            timing, marked, forced=forced, samples=samples, sr=sr,
            search_margin=cfg.align.realign_search_margin_seconds)
        summary = (f"reflowed {len(marked)} marked line(s) "
                   f"[{'interpolation' if forced is None else 'forced alignment'}]; "
                   f"backup at {sp.timing_json.name}.bak")
        _finish_nudge(sp, cfg, timing, new_timing, _t0, summary,
                      f"reflowed {len(marked)} line(s)", sorted(marked))
        return

    if anchors:
        _t0 = time.monotonic()
        parsed = {}
        for spec in anchors:
            lhs, t = spec.split("=", 1)
            parsed[int(lhs)] = _parse_time(t)
        forced, samples, sr = (None, None, None) if interpolate else _load_forced(sp, cfg)
        if forced is None and not no_snap:
            from karaoke.onsets import snap_marks
            parsed = snap_marks(sp.vocals, parsed)
        new_timing = nudge_mod.reflow_anchors(timing, parsed, forced=forced,
                                              samples=samples, sr=sr)
        summary = (f"reflowed {len(parsed)} anchored line(s); backup at "
                   f"{sp.timing_json.name}.bak")
        _finish_nudge(sp, cfg, timing, new_timing, _t0, summary,
                      f"anchor: {len(parsed)} line(s)", sorted(parsed))
        return

    edits = []
    for spec in shifts:
        lhs, t = spec.split("=", 1)
        edits.append(("shift", int(lhs), _parse_time(t)))
    for spec in copies:
        lhs, t = spec.split("=", 1)
        src, dst = lhs.split(">", 1)
        edits.append(("copy", int(src), int(dst), _parse_time(t)))
    if not edits:
        marked = [i for i, ln in enumerate(timing.lines)
                  if nudge_mod.is_marked_for_reflow(ln)]
        hint = (f"\nLine(s) {marked} look marked for reflow "
                f"(first word end=0) - did you mean --fill-cleared?" if marked else "")
        raise click.ClickException(
            "nothing to do: pass an operation - --shift / --copy / --anchor / "
            "--fill-cleared / --snap-edits (or --list to inspect)" + hint)

    _t0 = time.monotonic()
    new_timing = nudge_mod.apply_edits(timing, sp.vocals, edits, snap=not no_snap)
    idxs = [edit[2] if edit[0] == "copy" else edit[1] for edit in edits]
    summary = f"applied {len(edits)} edit(s); backup at {sp.timing_json.name}.bak"
    _finish_nudge(sp, cfg, timing, new_timing, _t0, summary,
                  f"shift/copy: {len(edits)} edit(s)", idxs)


@cli.command()
@click.argument("song", required=False, default=None)
@add_common
def split(song, songs_dir, config, force):
    """Fit too-wide lines: re-segment timing to lyrics.txt's splits, then
    auto-split (balanced) any line still past the window."""
    cfg, sp = _ctx(song, songs_dir, config)
    try:
        pipeline.run_split(sp, cfg, force=force)
    except (FileNotFoundError, ValueError) as e:
        raise click.ClickException(str(e))


if __name__ == "__main__":
    cli()
