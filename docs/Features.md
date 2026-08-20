# Features

This page describes what **karaoke_vid_gen** does, feature by feature. For help invoking the CLI, see **[Usage](Usage.md#usage)**; for the models behind separation and alignment, see **[Models](Models.md#models)**.

Core features used in creating a karaoke video are described in the [pipeline](#five-stage-pipeline) section below, and their application is shown in the [Example Workflow](Example%20Workflow.md#example-workflow) doc. Background information and description of auxiliary features are provided in the rest of the sections.

**Contents**

- [Five-stage pipeline](#five-stage-pipeline)
- [Two aligners + A/B](#two-aligners--ab)
- [Timing review & correction](#timing-review--correction)
  - [`timing.json`](#timingjson)
  - [`nudge` toolkit](#nudge-toolkit)
  - [Background-vocal words](#background-vocal-words)
  - [Preflight check](#preflight-check)
- [Line splitting](#line-splitting)
- [No-extract intervals](#no-extract-intervals)
- [Rendered frame elements](#rendered-frame-elements)
- [Render outputs & encoding](#render-outputs--encoding)
- [Per-song history log](#per-song-history-log)

## Five-stage pipeline

The pipeline's five stages are each cached and independently re-runnable, so
earlier work is never repeated.

### Acquire
 - a URL or local file is normalized into `song.flac`; artist/title are resolved from the folder name (or embedded tags / source metadata) to seed the lyric search.
 - on the audio format and how it moves through the stages: [Code → Audio format and flow](Code.md#audio-format-and-flow).
 
### Separate
 - audio file is [separated](Models.md#source-separation--demucs) into `instrumental.flac` + `vocals.flac`; or a user-supplied instrumental used as-is.

### Lyrics
 - auto-fetch plain text (LRCLIB → lyrics.ovh) OR manual-paste fallback into `lyrics.txt`.

### Align
 - force-align the known lyrics to the vocal stem and save word timings into editable [`timing.json`](#timingjson).
 - [two alignment models](#two-aligners--ab) and methods are available, and can be used at once (A/B)

### Render
 - [draw frames](#rendered-frame-elements) and encode into `karaoke.mp4` / `karaoke.review.mp4`.
 - review video used to edit timings, with [advanced features](#nudge-toolkit) as needed to finalize video.


## Two aligners + A/B

Alignment sits behind a swappable interface with two implementations:

- **Whisper** 
  - OpenAI Whisper ASR word timestamps reconciled against the known
  lyrics, the so-called "hybrid" approach.
- **MMS** 
  - TorchAudio MMS_FA CTC forced aligner; frame-accurate over the
  window it's given, and reused for localized reflow during [`nudge`](#nudge-toolkit).

The two take different methods, so they fail differently — which is the point of keeping both. An [`ab` command](Usage.md#ab--compare-the-two-aligners) runs both aligners to labeled outputs without touching the canonical timing, so you can watch each and keep the winner. The [Models doc](Models.md#alignment--two-approaches) captures 
[typical differences](Models.md#ab-whisper-vs-mms_fa) between the two models and additional information about the models.

An optional `--first-line` start hint re-seeds either
aligner for songs whose cold pass starts late or drifts.

## Timing review & correction

Alignment is imperfect; the tool treats the auto-timing as a **first draft** for
you to review and correct.

- [`timing.json`](#timingjson)
- [`nudge` toolkit](#nudge-toolkit)
- [Background-vocal words](#background-vocal-words)
- [Preflight check](#preflight-check)

### `timing.json`

Word-level timing is an editable JSON file: each line is a list of words with
`start`/`end` seconds. You can hand-edit it directly, and every downstream stage
reads from it. Because the review video keeps this file's time-base, a timestamp
read off the video maps straight back into the file.

Accurate timestamps for hand-editing `timing.json` can be determined using [**Song Timing Marker**](https://github.com/NBPub/song_timing_marker#song-timing-marker).

### `nudge` toolkit

Coarse-to-fine manual correction:

- **Coarse moves**
  - shift a line to a time, or copy one line's internal timing
  onto another, snapped to the vocal onset.
- **Anchors**
  - pin per-line starts; words between anchors are placed across the
  window by localized forced alignment (or length interpolation).
- **Marked-line reflow**
  - mark a line and let the **MMS_FA** aligner re-time its words within a bounded window seeded by your mark.
- **Snap-edits**
  - hand-edit `timing.json`, then snap your edited phrases onto
  the true vocal onsets.

After any mutating op, `nudge` re-runs the preflight and reports issues the reflow itself introduced — e.g. a reflowed line whose end runs past the next line's start — so they surface immediately rather than at the
next render.

### Background-vocal words

Words marked `"bg": true` in `timing.json` are backing vocals that may
overlap the lead. They render and fill like any word, but are excluded from
alignment/nudge reflow and from line-transition timing; the lead drives
transitions. This feature can be useful for echoes or call-and-response backing parts.

### Preflight check

A `check` validates `timing.json` (and its neighbouring files) before it's
used. It runs automatically before `render` (errors halt, so malformed timing never reaches a render) and before `nudge` (there, content errors are reported as non-halting warnings so a nudge can fix them; structural JSON errors still halt). Warnings always inform. Messages are 1-indexed with surrounding context. The initial `all` and `ab` renders are intentionally ungated and instead print a non-halting report of what `check` would flag.

Bypass the preflight check by adding the `--skip-check` option to a command.

<details>
<summary><strong>All preflight checks</strong> (name · severity · what it flags)</summary>

| Check | Severity | Flags |
|-------|----------|-------|
| `missing_timing` | Error | No `timing.json` in the song folder. |
| `json_parse` / syntax (`missing_comma`, `trailing_comma`, `empty_value`, `unbalanced_braces`) | Error | `timing.json` isn't valid JSON; a heuristic scan pinpoints the offending line even when it won't parse. |
| structure (`bad_shape`, `missing_key`, `bad_type`) | Error | Wrong shape — missing `lines`/`words`, or a word missing `text`/`start`/`end` (or of the wrong type). |
| `end_before_start` | Error | A word's `end` precedes its `start` (outside a valid reflow mark). |
| `zero_width_line` | Error | A line has zero duration (start == end). |
| `out_of_order` | Error | Word or line times run backwards. |
| `mark_no_anchor` | Error | A line marked for `--fill-cleared` reflow has no anchor start time set. |
| `bg_only_marked` | Warning | Only background-vocal words carry a reflow mark — nothing for the aligner to place. |
| `unprocessed_marker` | Warning | A section marker / repeat shortcut (e.g. `[Chorus]`, `(x4)`) survived into the timing. |
| `lyrics_count_mismatch` | Warning | `lyrics.txt` and `timing.json` have different line counts. |
| `lyrics_text_mismatch` | Warning | Their words differ — blocks `split`; re-align or hand-match the words. |
| `lyric_artifact` | Warning | Likely non-sung text in `lyrics.txt` (section headers, repeat shortcuts, scrape footers). |
| `past_song_end` | Warning | A word is timed past the end of the audio. |
| `line_too_wide` | Error at render / Warning at nudge | A line would run past the video width at the configured font — fix with `split`. |
| `count_in_density` | Warning | An unusually high share of lines would trigger count-in dots (consider raising `count_in_min_gap_seconds`). |
| `stale_render` | Warning | `timing.json` changed after the rendered video — re-render with `--force`. |
| `stale_no_extract` | Warning (prompts at render) | `no_extract.txt` changed after separation — re-run `separate` to apply the spans. |

</details>

## Line splitting

Lines deemed [too wide](Configuration.md#render) for the frame are handled two
ways by a **`split`** command:

- **Manual-assist**
  - split a line in `lyrics.txt`; `split` re-segments the
  existing `timing.json` words to match (lossless — each word keeps its time, no
  re-align). These render centered like normal lines.
- **Auto-split**
  - any line still too wide is balanced into the fewest rows that
  fit, with continuation rows marked and rendered as a left-justified block.

The over-wide check is also part of preflight, so you're warned before shipping a cut-off line.

## No-extract intervals

A per-song `no_extract.txt` lists segments where the karaoke
instrumental keeps the original mix (vocals included) instead of the vocals-removed audio. It can be used for echoes, ad-libs, or spoken parts you don't want to karaoke. The mix is spliced back over those spans with a short crossfade.

The [Usage](Usage.md#no_extracttxt) doc details how to specify these intervals.

## Rendered frame elements

Frames use a stacked-lyrics layout with per-word fill. Letters fill by
linear interpolation across each word's start→end. 

A few more visual elements are included and [configurable](Configuration.md#configuration):

- **Title card**
  - artist / title over the opening, with a conditional delay so singing never starts before there's time to read.
- **Song progress bar**
  - a persistent bar that fills across the track.
- **Count-in dots** (`●  ●  ●`)
  - a 3-2-1 before the first line and before any line after a [long enough](Configuration.md#render) gap.
- **Instrumental wait bar**
  - a fill bar indicates wait time over long breaks in the singing, with a warmer color for the outro.
- **Background-vocals**
  - separate fill logic to allow overlapping, secondary words

## Render outputs & encoding

- **Output modes**
  - Instrumental `karaoke.mp4`, full-audio `karaoke.review.mp4`,  or both at once.
  - Frames are drawn once and shared across targets when possible.
- **Encoding**
  - 1080p 16:9 H.264 + AAC
  - *NVENC* (GPU) by default with an automatic *libx264* (CPU) fallback.

See **[Configuration](Configuration.md#configuration)** for resolution, colors,
fonts, thresholds, and encoder options.

## Per-song history log

Each real operation (align / ab-keep / nudge / render / split) appends a row to a
per-song `history.csv` — model, seed, source, parameters, timing mtime,
render mode, encoder, and wall-time. Cached/skipped stages log nothing. It's a
human-readable lifecycle record of how a song's timing was produced; toggle it
on/off in config.

[History log example table](Example%20Workflow.md#history-log)
