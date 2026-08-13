# Usage

The pipeline fetches or ingests the audio, separates vocals from the backing 
with a source-separation model, fetches the lyrics, aligns lyrics to the isolated vocal to get word-level timing, lets you review and 
hand-correct that timing, and renders a video. The emphasis is accurate, editable per-word timing and full control over the result, not a one-click black box.

This page covers every command, listed in their typical order of use; `all` is a separate convenience that runs the whole sequence in one pass. For a full song
processed from start to finish, see **[Example Workflow](Example%20Workflow.md#example-workflow)**.

**Contents**

- **Background**
  - [The song folder & caching model](#the-song-folder--caching-model)
  - [Files you hand-edit](#files-you-hand-edit)
    - [lyrics](#lyricstxt) | [timing](#timingjson) | [no extract](#no_extracttxt)  
  - [Common options for commands](#common-options)
- **Commands**
  - [`all` — run the whole pipeline](#all--run-the-whole-pipeline)
  - [`acquire` — get the audio](#acquire--get-the-audio)
  - [`separate` — split vocals / instrumental](#separate--split-vocals--instrumental)
  - [`lyrics` — fetch the words](#lyrics--fetch-the-words)
  - [`align` — time the words](#align--time-the-words)
  - [`check` — preflight the timing](#check--preflight-the-timing)
  - [`nudge` — hand-correct timing](#nudge--hand-correct-timing)
  - [`ab` — compare the two aligners](#ab--compare-the-two-aligners)
  - [`split` — fit over-wide lines](#split--fit-over-wide-lines)
  - [`render` — make the video](#render--make-the-video)

---

## The song folder & caching model

Every song lives in its own folder, named `"<Artist> - <Title>"`, under the
songs directory (default [`songs/`](Configuration.md#paths)). Each stage writes
cached artifacts into that folder:

```
songs/Artist - Title/
  song.flac            # normalized source audio (acquire)
  instrumental.flac    # vocals-removed backing (separate)
  vocals.flac          # isolated vocal stem (separate)
  lyrics.txt           # plain lyric lines (lyrics)
  timing.json          # editable word-level timing (align / nudge)
  karaoke.mp4          # instrumental karaoke video (render)
  karaoke.review.mp4   # full-audio review video (render)
  history.csv          # per-song operation log (optional, see configuration)
```

The `history.csv` log is optional — enable or disable it under
[`[history]`](Configuration.md#history) in config.

The song name is the first argument to every command; it maps to the folder.
It's optional, and can be omitted while your shell is `cd`'d inside a song
folder. The command infers the song from the current directory (guarded: it
must hold a karaoke artifact, or sit directly under the songs directory). So from
`songs/Artist - Title/` you can just run `karaoke render`, `karaoke check`, etc.
An explicit name always wins.

*generate final render of a finished song*

```bash
# operating within project root with virtual environment activated
cd "songs/<artist> - <title>"
karaoke check
karaoke render --mode both --force
```

A stage skips when its output already exists, pass `--force` to redo it.
This makes each stage independently re-runnable, so you can iterate on one part
(re-align, re-render) without repeating the rest.

## Files you hand-edit

Beyond the commands, three files in the song folder are yours to edit directly —
this is where the "full control over per-word timing" lives. For *why* each
exists, see [Features](Features.md#features); this is the *how*.

### `lyrics.txt`

Plain text, one lyric line per line (blank lines separate sections). A few
conventions:

- **Spell out numerals** (`5'll` → `five'll`, `2` → `two`): both aligners handle
  digits poorly, so spelled-out words align far better. See
  [Models](Models.md#models).
- **To hand-split a too-wide line**, break it into two lines here, then run
  [`split`](#split--fit-over-wide-lines): it re-segments `timing.json` to match,
  losslessly (each word keeps its time — no re-alignment).
- **If you change the *words* after aligning** (fix a misheard lyric, spell out a
  numeral), mirror the same edit in `timing.json` or re-run
  [`align`](#align--time-the-words) — otherwise `check` reports a mismatch and
  `split` refuses (both files must hold identical words). Changing only a line
  *break* is safe; that's exactly what `split` handles.

### `timing.json`

The editable word-level timing: **the file that drives the per-word fill in the
rendered video**. It's a `lines` array; each line holds a list of `words`, and
each word is `{"text", "start", "end"}` in seconds. Words also take two optional
keys: `"bg": true` marks a background-vocal word, and `"wrap": true` marks a
continuation row produced by line [`split`](#split--fit-over-wide-lines).

```json
{
  "lines": [
    { "words": [
        { "text": "Code",   "start": 12.40, "end": 12.63 },
        { "text": "Monkey", "start": 12.66, "end": 13.10 }
    ] }
  ]
}
```

- **Adjust timing**
  - edit a word's `start` / `end`, then
  [`check`](#check--preflight-the-timing) and re-render with `--force`.
- **Background-vocal words** 
  - add `"bg": true` to backing-vocals (that may overlap the lead). 
  - they render and fill like any word but are excluded from
  line-transition timing and from nudge reflows. See
  [Features → background-vocal words](Features.md#background-vocal-words).
- **Mark a line for reflow:** 
  - set the line's first word's  `end` to `0` and its `start` to the line's approximate start
  - optionally bound the end too, by setting the last  word's `start` to
  `0` and its `end` to the approximate end
  - run [`nudge --fill-cleared`](#nudge--hand-correct-timing) — the aligner re-times the line's words within that window

### `no_extract.txt`

Optional per-song file. Each line names a span where the karaoke
`instrumental.flac` keeps the original mix (vocals included) instead of the
vocals-removed audio — for echoes, ad-libs, or spoken parts you don't want to
karaoke:

```text
# START-END, in seconds or m:ss. '#' comments and blank lines are ignored.
4.03-7.05    # plain seconds (fractional OK)
2:30-2:38    # m:ss (fractional OK too, e.g. 2:30.5)
```

Plain seconds (`7`, `7.05`) or `m:ss` (`2:38`, `2:38.5`) formats are accepted, 
same time format [`nudge`](#nudge--hand-correct-timing) uses.

Edit the file, then separate audio again, [`separate --force`](#separate--split-vocals--instrumental),
to apply it. Each edge gets a short crossfade. `separate` prints a readout of the intervals it applied or a clear warning if the file is
malformed. 

If you edit this file but forget to re-separate the [`render`](#render--make-the-video) preflight warns (`stale_no_extract`) and offers to run `separate` for you first. See [Features → no-extract intervals](Features.md#no-extract-intervals).

## Common options

Available on every command:

- `--force` 
  - redo a stage/output that would otherwise be skipped
  - for example, required to render with updating timings
- `SONG` (first argument) — optional
  - inferred from the current directory when [omitted](#the-song-folder--caching-model)
  - typically given as `"<Artist> - <Title>"` — it maps to the song folder of that name
- `--songs-dir DIR`
  - directory containing folder for each processed song
  - precedence: this flag >`[paths].songs_dir` in config > the built-in default `songs`
- `--config FILE`
  - point to a separate configuration file, for example `config2.toml`
    - could be useful for render comparisons
  - default `config.toml`

---

## `all` — run the whole pipeline

Runs acquire → lyrics → separate → align → render in one pass and ends with an
initial render you can watch: reviewing the timing from a video is far easier than
reading `timing.json`. The render follows your `render.mode` config (default
`review`, the full-audio review copy); set it to `both` or `karaoke` if you'd
rather `all` produce those outputs.

```bash
karaoke all "Artist - Title" "https://www.youtube.com/watch?v=..."   # from a URL
karaoke all "Artist - Title" "path/to/song.mp3"                      # from a local file
```

- **Prompts only when needed (resume).**
  - `all` prompts for the audio source only when acquire still has to run, and for
    a supplied instrumental (file or URL; blank = AI separation) only when separate
    still has to run.
  - on a re-run, finished stages are skipped silently and their prompts don't
    appear, so `all` resumes where it left off (`--force` re-does every stage and
    re-asks).
- `--first-line M:SS`
  - seed alignment with the approximate start of the first sung line (see
    [`align`](#align--time-the-words)).
- `--model whisper|mms`
  - override the aligner for this run (see [`align`](#align--time-the-words));
    mutually exclusive with `--ab` (which runs both).
  - an unrecognized name stops the command and prints the valid options
    (`whisper`, `mms`), your configured default, and a hint to use `--ab` if you
    wanted both.
- `--ab`
  - run both aligners in one pass (equivalent to
    [`ab`](#ab--compare-the-two-aligners)) instead of the single align+render:
    acquire → lyrics → separate → both timings + review videos, then stop at the
    keep gate.
  - nothing becomes canonical until you `ab --keep` the winner.

The only forced stop is when the lyrics can't be auto-fetched: `all` tells you to
paste them into `lyrics.txt`, then re-run `karaoke all <...>`; finished stages are
cached, so it resumes where it left off. After watching the review video and making
adjustments, run [`check`](#check--preflight-the-timing) /
[`split`](#split--fit-over-wide-lines) / [`nudge`](#nudge--hand-correct-timing),
then re-render with `--force`.

## `acquire` — get the audio

Takes a URL (via `yt-dlp`) or a local file (MP3/FLAC/WAV/…) and produces
`song.flac`. It resolves artist/title (from the folder name, embedded tags, or
source metadata) to seed the lyric search. For what `song.flac` is and how the
audio moves through the pipeline, see
[Code → Audio format and flow](Code.md#audio-format-and-flow).

```bash
karaoke acquire "Artist - Title" "https://www.youtube.com/watch?v=..."
karaoke acquire "Artist - Title" "path/to/song.mp3"
```

Playlist URLs are refused (any `list=` parameter): supply a single-video URL or a
local file.

## `separate` — split vocals / instrumental

Runs source separation (Demucs `htdemucs`, GPU) to produce `instrumental.flac`
(vocals removed) and `vocals.flac` (isolated vocal, used for alignment).

```bash
karaoke separate "Artist - Title"
karaoke separate "Artist - Title" --instrumental "path-or-URL"   # supply your own
```

- `--instrumental FILE|URL`
  - use a supplied instrumental as-is instead of separating.
- **No-extract intervals**
  - keep the original mix over chosen spans (echoes, spoken parts) instead of the
    vocals-removed audio: add a `no_extract.txt` and re-run this stage with
    `--force`.
  - see [Files you hand-edit → `no_extract.txt`](#no_extracttxt).

## `lyrics` — fetch the words

Fetches plain-text lyrics (LRCLIB, then lyrics.ovh), falling back to manual
paste, and writes `lyrics.txt`.

```bash
karaoke lyrics "Artist - Title"
```

<details>
<summary><strong>Common lyric issues</strong> to watch for</summary>

Lyric sites often add non-sung text that corrupts alignment. Watch for:

<ul>
<li>section markers (<code>[Chorus]</code>, <code>[Verse 2]</code>)</li>
<li>repeat shortcuts (<code>(x4)</code>, <code>Chorus 2x</code>)</li>
<li>stray footer lines ("you might also like …")</li>
</ul>

Also spell out numerals (`5` → `five`): both aligners handle digits poorly.
`check` flags common artifacts, but a quick read of `lyrics.txt` before aligning
is worth it.

</details>

## `align` — time the words

Aligns the known lyric text to the vocal stem, producing an editable `timing.json`
with per-word start/end times. This is the human-review gate of the pipeline.

```bash
karaoke align "Artist - Title"
karaoke align "Artist - Title" --first-line 0:18   # seed the first sung line
karaoke align "Artist - Title" --model mms         # force this aligner for this run
```

- `--first-line M:SS`
  - re-run the first pass seeded by the first sung line's approximate time; trims a
    misleading intro and helps songs whose cold pass starts late or drifts.
  - aligner-agnostic, which is what enables clean Whisper-vs-MMS comparisons (see
    [`ab`](#ab--compare-the-two-aligners)).
- `--model whisper|mms`
  - override the aligner for this run only. Omit it to use the configured default
    (`models.aligner`); an unrecognized value stops with the valid options and that
    default.
  - handy for one-off `whisper` vs `mms` runs without editing config.

The aligner is selectable in [config](Configuration.md#models) (`models.aligner`):
the default Whisper aligner (Whisper ASR + reconciliation against the known
lyrics), or the MMS forced aligner (MMS_FA, single-pass CTC). See
[Models](Models.md#alignment--two-approaches).

## `check` — preflight the timing

Validates `timing.json` and its neighboring files: JSON syntax and structure,
timing semantics, timing↔lyrics consistency, stale renders, over-wide lines, and
more. It runs automatically before `nudge` and `render` (errors halt; warnings
inform; `--skip-check` bypasses). One warning, a stale `no_extract.txt`, is
interactive at `render`, offering to run `separate` first (see
[`render`](#render--make-the-video)). The full list of checks, with severities, is
in [Features → preflight check](Features.md#preflight-check).

```bash
karaoke check "Artist - Title"
```

## `nudge` — hand-correct timing

Manual timing correction for passages the aligner gets wrong. Every mutating
operation rewrites `timing.json` in place and backs the previous version up to
`timing.json.bak`. The `--anchor` and `--fill-cleared` reflows re-time the affected
lead words by localized forced alignment (`MMS_FA`) inside a bounded window,
falling back to length-based interpolation when torch/the model isn't available
(or when you pass `--interpolate`); `--shift`/`--copy` are coarse moves that don't
re-align.

Two shared conventions:

- **Line numbers** (`L`, `SRC`, `DST`): the 0-based indices printed by `--list`.
- **Times** (`T`): accept `M:SS`, `M:SS.mmm`, or plain seconds (`1:06`, `66`, and
  `66.5` all work).

```bash
karaoke nudge "Artist - Title" --list        # print numbered lines + start/end times
```

`--list` is read-only: it just prints each line's index and current start/end, so
you can see the timing and pick line numbers for the operations below without
opening `timing.json`.

### Coarse moves (snapped to the nearest vocal onset)

- `--shift L=T`
  - slide line `L` so it starts at `T`, keeping the line's words at their existing
    duration and relative spacing. Repeatable.
  - example: `--shift 8=1:06` starts line 8 at 1:06.
- `--copy SRC>DST=T`
  - copy line `SRC`'s internal word timing onto line `DST` and place it starting at
    `T`. Useful for a repeated line (e.g. a chorus) one instance already nails.
    Repeatable.
  - example (quote it in your shell): `karaoke nudge --copy "12>40=2:15"`. The `>`
    is an output-redirect operator in PowerShell and bash, so an unquoted
    `--copy 12>40=2:15` writes to a file named `40=2:15` and the command receives
    only `12`.

Both snap the given time to the nearest onset in the vocal stem; add `--no-snap`
to use your time exactly as given.

### Anchored reflow

- `--anchor L=T`
  - pin line `L`'s first word to time `T`. Pass at least two anchors (each is one
    line's start), in increasing line and time order.
  - the lead words on lines *between* consecutive anchors are re-timed across that
    window (forced alignment, or `--interpolate` to space them by character
    length). Repeatable.
  - example: `--anchor 4=0:31 --anchor 9=0:45`.
  - invalid: a single anchor (no window to fill), or anchors whose line numbers or
    times run backwards.

### Marked-line reflow

- `--fill-cleared`
  - reflow every line you've marked in `timing.json` (no values on the command
    line).
  - mark a line by setting its first word's `end` to `0` and its `start` to where
    the line should begin (the anchor); optionally bound the tail by setting the
    last non-bg word's `start` to `0` and its `end` to the approximate line end.
  - the start you set is approximate: the reflow searches a margin around it, so it
    needn't be exact. Each marked line's lead is then re-timed within that window
    (plus a small [search margin](Configuration.md#align)).
  - a full worked example is in the [Example Workflow](Example%20Workflow.md)
    (step 7).

### Hand-edit, then snap

- `--snap-edits`
  - after you hand-edit word times directly in `timing.json`, snap just the phrases
    you moved onto the true vocal onsets. It finds them by diffing against a
    baseline (the timing straight out of `align`).
- `--save-baseline`
  - snapshot the current `timing.json` as that baseline. `align` seeds one
    automatically, so you only need this for songs aligned before the baseline
    existed, or to re-anchor the reference before a fresh round of edits.

### Modifiers

- `--interpolate`
  - reflow by character-length interpolation instead of forced alignment (also the
    automatic fallback when torch/the model can't load).
- `--no-snap`
  - use the times you give as-is; skip onset snapping.
- `--skip-check`
  - skip the preflight gate that otherwise runs first.

After any mutating op, `nudge` re-runs the preflight check and 
reports (without halting) issues the reflow introduced — e.g. a 
reflowed line whose end runs past the next line's start — so you catch 
them before rendering. Background-vocal words (`"bg": true` in 
`timing.json`) may overlap the lead and are excluded from all reflow 
and line-transition timing. See
[Features → background-vocal words](Features.md#background-vocal-words).

## `ab` — compare the two aligners

Generates both aligners' timings (**Whisper** + **MMS_FA**) to labeled files
(`timing.whisper.json` + `timing.mms.json`) and renders labeled karaoke videos, without touching the canonical `timing.json` or previously generated karaoke videos. Review the two, then keep the winner.

`ab` renders per your `render.mode` (default `review`), so by default you get the
two review copies; set `render.mode` to `both` or `karaoke` to also get the
instrumental cuts labeled per model.

```bash
karaoke ab "Artist - Title"                    # generate both + review videos
karaoke ab "Artist - Title" --first-line 0:21  # seed both the same way
# after reviewing results and picking a winner
karaoke ab "Artist - Title" --keep mms         # promote one to canonical, remove the rest
```

- **Reuse of the initial pass.**
  - if you already ran [`all`](#all--run-the-whole-pipeline) (which aligns with one
    model and renders) and haven't edited the timing since, `ab` reuses that
    alignment (and its render, when it's full-length) as that model's arm, so only
    the other aligner runs.
  - it's automatic (detected from the history log plus a check that `timing.json`
    is unmodified); pass `--force` to recompute both arms instead.
  - this detection reads the [history log](Configuration.md#history); with
    `[history] enabled = false` there's nothing to read, so the reuse is skipped
    and both arms are always computed fresh.
- **The canonical files stay put during A/B.**
  - your existing `timing.json` and review video are left untouched while you
    compare; `ab --keep <model>` replaces them with the chosen model (and removes
    the labeled `*.whisper.*` / `*.mms.*` files). Keep the winner before nudging or
    a final render.

See **[Models](Models.md#ab-whisper-vs-mms_fa)** for when each aligner tends to win.

## `split` — fit over-wide lines

Fits lines too wide for the frame, two ways:

- **Manual-assist**
  - split a line in `lyrics.txt`; `split` re-segments the existing `timing.json`
    words to match (lossless, no re-align).
- **Auto-split**
  - any line still too wide is balanced into the fewest rows that fit, with
    continuation rows rendered as a left-justified block.

```bash
karaoke split "Artist - Title"
```

## `render` — make the video

Draws frames and encodes the MP4(s). NVENC (GPU) by default, `libx264` fallback.

```bash
karaoke render "Artist - Title"                      # default mode (review copy)
karaoke render "Artist - Title" --mode both --force  # both outputs, redo
```

- `--mode both|karaoke|review`
  - `both` writes `karaoke.mp4` (instrumental) and `karaoke.review.mp4` (full
    audio); `karaoke` / `review` write just one.
  - defaults to `review` (per [`render.mode`](Configuration.md#render)) for fast
    iteration.
- `--force`
  - re-render even if the video exists. Always pass `--force` after a timing
    change, or you ship the stale video.
- `--full` / `--tail SECONDS`
  - control how much instrumental outro to include, useful for songs with a long
    closing instrumental.
  - e.g. a song that ends on a ~2-minute instrumental outro: `--tail 30` keeps just
    30 s of it, while `--full` keeps the whole tail.

The preflight runs first (errors halt unless `--skip-check`). If it finds a stale
`no_extract.txt` (edited since the last `separate`), an interactive render asks
whether to run `separate` first: answer yes and it re-separates, then renders in
one go; answer no and it asks whether to render the current instrumental anyway.
Non-interactive runs just print the warning and proceed.

See **[Configuration](Configuration.md#configuration)** for resolution, colors,
fonts, and encoder settings.