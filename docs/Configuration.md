# Configuration

All settings live in **[`config.toml`](../config.toml)** at the project root; omit
any key to fall back to its built-in default. Pass a different file with
`--config FILE`. Values here are the shipped defaults.

**Contents**

- [`[render]`](#render)
  - video, layout, colors, on-screen elements
- [`[audio]`](#audio)
- [`[align]`](#align)
  - onset snapping, lead, best-of-N
- [`[models]`](#models)
  - separation + alignment model choices
- [`[history]`](#history)
- [`[paths]`](#paths)

## `[render]`

Video output and everything drawn on the frame: resolution and frame rate, fonts and colors, and the on-screen elements (title card, progress bar, wait bar, count-in dots).

| Key | Default | Description |
|-----|---------|--------------|
| `width` / `height` | `1920` / `1080` | Frame size (1080p 16:9). |
| `fps` | `30` | Frames per second. |
| `font_size` | `48` | Lyric font size (px). |
| `lines_per_page` | `6` | Stacked lyric lines visible at once. |
| `fill_color` | `#22D3EE` (bright cyan) | The color each letter **sweeps to as it's sung** (the per-word fill). |
| `past_color` | `#2C7F93` (darker cyan) | Color of already-sung lines. |
| `wait_bar` | `true` | Show a filling bar over long instrumental gaps. |
| `wait_min_gap_seconds` | `10.0` | Gap length that triggers the wait bar. |
| `wait_bar_end_seconds` | `1.0` | How long before the next line the wait bar finishes filling. |
| `wait_highlight_seconds` | `3.0` | How long before it starts the next line begins highlighting. |
| `mode` | `review` | Default render outputs: `both` \| `karaoke` \| `review`. |
| `video_codec` | `auto` | `auto` (NVENC if available, else libx264) \| `nvenc` \| `libx264`. |
| `nvenc_cq` | `23` | NVENC quality (lower = better/bigger), ~ x264 crf 23. |
| `title_card` | `true` | Show the artist/title card over the opening. |
| `title_seconds` | `3.0` | Title-card duration. |
| `title_read_buffer_seconds` | `2.0` | Min read time before singing may start (drives the lead-in delay). |
| `title_fade_seconds` | `0.5` | Title fade in/out. |
| `progress_bar` | `true` | Persistent song-progress bar down the right edge. |
| `progress_fill_color` | `#DD2C11` (red) | Progress-bar fill. |
| `progress_outline_color` | `#22D3EE` (cyan) | Progress-bar outline. |
| `count_in` | `true` | Show `●  ●  ●` count-in dots. |
| `count_in_min_gap_seconds` | `5.0` | Gap length that triggers a count-in (decoupled from the wait bar). |
| `font_file` | `""` | Explicit TTF path; `""` auto-resolves a bold system font. |
| `jobs` | `0` | Pillow draw workers: `0` = all cores, `1` = serial, `N` = N processes. |
| `usable_width_frac` | `0.9` | Fraction of frame width a line may use before it's flagged too-wide / [auto-split](Features.md#line-splitting). |

The remaining text colors (`base_color`, `upcoming_color`, `background`) have
built-in defaults and can be added to `[render]` to override them.

**Colors.** The palette is deliberately simple and easy to retheme. The
**`fill_color`** is the most visible choice: it's the sweep that tracks the
singing across each word. Keep it high-contrast against the dark background and
distinct from `progress_fill_color` so the two bars/sweeps don't blur together.

<img src="images/code_monkey_final.png" alt="Default palette: cyan per-word fill on a dark background" width="480">

**`usable_width_frac`.** Lowering this demands a wider safe margin before a line
is flagged too-wide (and auto-split). `1.0` uses the full frame; `0.9` leaves a
10% margin. See [`split`](Usage.md#split--fit-over-wide-lines).

**Wait bar vs count-in thresholds.** `wait_min_gap_seconds` and
`count_in_min_gap_seconds` are independent: a gap past the count-in threshold but
below the wait-bar threshold gets a 3-2-1 without the full instrumental-break bar.

**Encoder.** `video_codec = auto` uses NVENC when a compatible GPU is present and
falls back to `libx264`; force one explicitly if needed.

## `[audio]`

| Key | Default | Description |
|-----|---------|--------------|
| `bitrate` | `320k` | AAC audio bitrate in the final MP4. |

**AAC in MP4** is the default because it's the broadly compatible pairing for H.264 video: it plays natively in browsers, media players, and the video sites these files usually end up on. `320k` is effectively transparent. Lowering it saves little next to the video stream, so it's worth doing only when the source audio is already below 320 kbps (common for YouTube rips, where the true audio bitrate is often lower than the reported one). For how audio is stored and flows through the pipeline stages, see [Code → Audio format and flow](Code.md#audio-format-and-flow).

## `[align]`

Fine-tuning for the alignment stage: onset snapping, the fill's head-start, and
Whisper's best-of-N decoding.

| Key | Default | Description |
|-----|---------|--------------|
| `onset_snap` | `true` | Back each word's start up to the true vocal onset (only moves earlier). |
| `onset_lookback_seconds` | `0.25` | How far back onset-snapping may search. |
| `lead_seconds` | `0.10` | Constant head-start of the fill over the voice (anticipation). |
| `best_of_n` | `3` | Whisper draws per align; keeps the one anchoring the most known words. `3` tested best, so don't exceed it; `1` = greedy (fastest, fully deterministic). |
| `realign_search_margin_seconds` | `1.0` | Padding around your [`nudge --fill-cleared`](Usage.md#nudge--hand-correct-timing) marks that the forced aligner searches. |

 **Most users won't need to touch these;** the
defaults are tuned (see [Models](Models.md#whisper-parameters) for the reasoning), and this section is really for power-users. Adjust only if a song's timing is consistently off in a way editing `timing.json` can't fix.

## `[models]`

| Key | Default | Description |
|-----|---------|--------------|
| `demucs_model` | `htdemucs` | Source-separation model. Changeable to other Demucs variants in principle, but only `htdemucs` is tested/supported here. |
| `device` | `cuda` | Compute device: `cuda` (GPU) or `cpu` (works, but much slower for separation and alignment). |
| `aligner` | `whisper` | `whisper` (Whisper ASR + reconciliation against the known lyrics) \| `mms` (single-pass CTC forced alignment, `MMS_FA`; `torchaudio` is also accepted as an alias). |
| `whisper_model` | `medium` | Whisper size (see [Models](Models.md#whisper-parameters)). |

**`whisper_model` and `best_of_n`.** Bigger isn't always better for timing;
`medium` is the sweet spot, and `best_of_n` (in [`[align]`](#align)) claws back
hard passages without changing size. See [Models](Models.md#whisper-parameters)
for the reasoning.

## `[history]`

| Key | Default | Description |
|-----|---------|--------------|
| `enabled` | `true` | Write the per-song `history.csv` lifecycle log. |

Each real operation (align / ab-keep / nudge / render / split) appends a row:
model, seed, source, parameters, timing mtime, render mode, encoder, and
wall-time. See [Features → history log](Features.md#per-song-history-log).

## `[paths]`

Choose where work is saved.

| Key | Default | Description |
|-----|---------|--------------|
| `songs_dir` | `songs` | Directory that holds the per-song folders. |

`songs_dir` is resolved **relative to the directory you run `karaoke` from**: the
project root in normal use, so songs land in `<project>/songs/`. If you run a command from a different folder, a `songs/` (or your configured name) is created there instead. Use an absolute path, or the `--songs-dir` flag, to pin it.

The `--songs-dir` flag overrides this per-invocation; precedence is
`--songs-dir` > `[paths].songs_dir` > the built-in `songs`. When you run a
command from *inside* a song folder, the `SONG` argument can be omitted. See
[Usage → the song folder model](Usage.md#the-song-folder--caching-model).
