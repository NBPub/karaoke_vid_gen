# Code

Exploration of how the code is organized, with brief discussion and explanation of test coverage.

**Contents**

- [Data Flow](#data-flow)
- [Module Map](#module-map)
- [Design Notes](#design-notes)
- [Tests](#tests)

## Data Flow

```mermaid
flowchart TD
    src["audio file / URL"] --> acquire
    words["lyrics: auto-fetched or user-supplied"] --> lyrics
    acquire["acquire → song.flac"] --> separate
    separate["separate → instrumental.flac + vocals.flac"] --> align
    lyrics["lyrics → lyrics.txt"] --> align
    align["align → timing.json (ab: compare aligners)"] --> review{"review / nudge / check"}
    review -->|edits| review
    review --> render["render → karaoke.mp4 / karaoke.review.mp4"]

    instr["provided instrumental (file / URL)"] -. "used as-is" .-> separate
    separate -. "no_extract.txt" .-> separate
```

## Module Map

The `karaoke` package is organized by responsibility:

| Area | Modules | Responsibility |
|------|---------|----------------|
| **Entry** | `cli.py`, `pipeline.py` | Command parsing; stage orchestration + caching. |
| **Config / paths** | `config.py`, `paths.py`, `metadata.py`, `timeparse.py` | Settings, per-song file locations, artist/title resolution, `M:SS` time parsing. |
| **Acquire / separate / lyrics** | `acquire.py`, `separate.py`, `no_extract.py`, `lyrics.py` | Get audio, split stems (+ original-mix splicing), fetch lyrics. |
| **Alignment** | `align.py`, `reconcile.py`, `onsets.py`, `realign.py` | Whisper + `MMS_FA` aligners, lyric↔ASR reconciliation, onset snapping, windowed forced alignment. |
| **Timing model** | `timing.py`, `nudge.py`, `preflight.py`, `linesplit.py`, `fill.py` | `timing.json` data model, manual correction, validation, line splitting, per-word fill interpolation. |
| **Render** | `render/` (`__init__.py`, `draw.py`, `pillow.py`, `encode.py`) | Frame-state assembly → Pillow drawing → FFmpeg encode. |
| **Bookkeeping** | `history.py` | Per-song `history.csv` logging. |

Between them these cover every module in the package (`__init__.py` is just the package marker); there is no leftover "other" bucket.

## Design Notes

- **Stages are thin wrappers over cached artifacts.** Each stage reads its inputs from the song folder and writes its output there; re-running skips when the output exists (`--force` redoes). This keeps stages independently runnable.
- **Pure logic is separated from I/O.** Timing math, fill interpolation, parsing, and config are pure and unit-tested; the heavy ML/network stages and rendering
  sit behind thin, mockable interfaces.
- **The aligner is a swappable interface** ([Whisper](Models.md#alignment--two-approaches) vs [`MMS_FA`](Models.md#alignment--two-approaches)), which is what makes the A/B aligner comparison possible; rendering sits behind a small `Renderer` interface, too.

## Tests

The suite is [`pytest`](https://docs.pytest.org)-based and lives in [`tests/`](../tests). Run it from the project root with the virtual environment active:

```bash
pytest            # or: python -m pytest
```

Because pure logic is kept separate from the heavy ML and I/O (see [Design Notes](#design-notes)), most tests are fast and deterministic: the ML and network stages are exercised through mocks rather than real model runs, so the suite needs no GPU, no downloads, and no sample audio.

Coverage by area:

- **Timing logic** (`test_timing`, `test_fill`, `test_linesplit`, `test_nudge`, `test_preflight`): the timing model and its validation, per-word fill interpolation, line splitting, nudge operations, and the preflight checks.
- **Alignment** (`test_align`, `test_reconcile`, `test_realign`, `test_onsets`): aligner behavior, lyric↔ASR reconciliation, windowed forced-alignment reflow, and onset snapping.
- **Initial processing** (`test_acquire`, `test_separate`, `test_separate_no_extract`, `test_no_extract`, `test_lyrics`, `test_lyrics_fetch`, `test_metadata`): audio ingest, stem separation and no-extract splicing, lyric fetch and parsing, and artist/title resolution.
- **Render** (`test_draw`, `test_render_pillow`, `test_encode`): frame drawing, the Pillow renderer, and the FFmpeg encode step.
- **Orchestration** (`test_cli`, `test_pipeline`, `test_ab`, `test_paths`, `test_config`, `test_history`, `test_history_integration`): command parsing, stage caching and orchestration, the A/B workflow, path resolution, config loading, and history logging.