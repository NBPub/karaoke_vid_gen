# Karaoke Video Generator

Python CLI to facilitate making a karaoke video from a song. 
Provide an audio source (local file or YouTube URL) and song metadata, then automatically:
 - acquire audio and fetch lyrics
 - separate vocals from instrumentals
 - sync vocal track to lyrics 
 - generate a simple video with timed filling for lyrics
   - "review" video with full audio and "karaoke" video with vocals removed 
   - hand edit word timings as needed
   - utilize other [advanced features](docs/Features.md) for fine-tuning final karaoke video

| [Quickstart](#quickstart) | [Features](#feature-overview) | [AI Acknowledgement](#ai-acknowledgement) | [Contributing](#contributing) |

---

*[MIT Licensed](LICENSE)*


<!-- badges -->
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![PyTorch](https://img.shields.io/badge/PyTorch-CUDA-EE4C2C?logo=pytorch&logoColor=white)
![Whisper](https://img.shields.io/badge/OpenAI-Whisper-412991?logo=openai&logoColor=white)
![Demucs](https://img.shields.io/badge/Demucs-htdemucs-blue)
![FFmpeg](https://img.shields.io/badge/FFmpeg-NVENC-007808?logo=ffmpeg&logoColor=white)

> **Not affiliated with YouTube or any music service.** URL ingestion uses
> [`yt-dlp`](https://github.com/yt-dlp/yt-dlp); you are responsible for having the right to download and use any
> audio you process. Intended for personal use.
>
> **Process audio you trust.** Input audio and downloads are decoded by native
> libraries ([FFmpeg](https://ffmpeg.org/), [libsndfile](https://libsndfile.github.io/libsndfile/)
> via [`soundfile`](https://github.com/bastibe/python-soundfile)); as with any
> media tool, only run it on files and URLs from sources you trust.


## Quickstart

*Set up Python, CUDA, FFmpeg, and the model stacks first; see **[Installation](docs/Installation.md#installation)** for details and UNIX commands.*

```bash
# 1. Install (see docs/Installation.md; the GPU torch build is a separate step)
python -m venv .venv && .venv/Scripts/activate      # Windows
pip install -r requirements.txt
pip install -e .                                     # the `karaoke` command

# 2. Process a song end-to-end
karaoke all "Artist - Title" "https://www.youtube.com/watch?v=..."

# 3. Watch review video, adjust timing, then render final versions
karaoke check  "Artist - Title"
karaoke render "Artist - Title" --mode both --force
```

`karaoke all ...` runs the [five stages](docs/Features.md#five-stage-pipeline) end-to-end and finishes with an initial **review render** to watch; each stage is also runnable on its own so you can re-do just one. 

The typical loop is **first pass → review the auto-aligned timing → nudge/hand-edit timing→ final render**. 

See **[Usage](docs/Usage.md)** for every command and **[Example Workflow](docs/Example%20Workflow.md)** for a full walk-through.

### Requirements

- **Python 3.12** (ML wheels for PyTorch/CUDA are most reliable here).
- **NVIDIA GPU + CUDA** strongly recommended: separation and alignment run on
  the GPU; a CPU fallback exists but is slow.
- **FFmpeg** on the PATH (audio conversion + video encode; NVENC used when
  available, `libx264` fallback).
- Python packages, [`requirements.txt`](requirements.txt): PyTorch/torchaudio,
  Demucs, OpenAI Whisper, Pillow, soundfile, yt-dlp.

Models and their functions, see **[docs](docs/Models.md)** for details:

[![Demucs](https://img.shields.io/badge/Separation-Demucs%20htdemucs-blue)](https://github.com/adefossez/demucs)
[![Whisper](https://img.shields.io/badge/Automatic_Speech_Recognition-OpenAI%20Whisper-412991)](https://github.com/openai/whisper)
[![MMS_FA](https://img.shields.io/badge/Forced%20Align-torchaudio%20MMS__FA-EE4C2C)](https://pytorch.org/audio/stable/generated/torchaudio.pipelines.MMS_FA.html)

## Feature Overview

A **Python CLI** (`karaoke`) built around a five-stage, individually re-runnable, cached pipeline. See **[Features](docs/Features.md)** for more:

- **5-stage pipeline**: acquire → separate → lyrics → align → render
  - run all together, exemplified above, or each stage in sequence
- **Two swappable aligners**: generate lyric timings for filling words in the video
  - **Whisper:** OpenAI Whisper word timestamps reconciled against the
    known lyrics ("hybrid" method).
  - **MMS:** TorchAudio MMS_FA single-pass [CTC](https://en.wikipedia.org/wiki/Connectionist_temporal_classification) forced alignment
    (frame-accurate, no transcription step).
  - built-in **A/B** command to compare and keep the better one.
- **Adjustable timing for word fills**
  - hand-editable `timing.json` (from chosen aligner)
  - `nudge` [toolkit](docs/Usage.md#nudge--hand-correct-timing)
  - preflight **[`check`](docs/Features.md#preflight-check)**, validates timing, among other things, before every render.
- **Rich rendered frames, [configurable](docs/Configuration.md#render) appearance**
  - stacked lyrics with a per-word color fill
  - title card and persistent song progress bar
  - count-in dots and a wait bar over long gaps
  - separated fill logic for background-vocal words
  - facilitated or automatic line splitting for lines that extend out of frame
- **No-extract intervals**: keep the original mix over chosen spans instead of
  the vocals-removed audio.
- **Per-song `history.csv`**: lifecycle log of every operation.
- **GPU throughout**: Demucs, Whisper, and MMS_FA on [CUDA](https://en.wikipedia.org/wiki/CUDA); [NVENC](https://en.wikipedia.org/wiki/NVENC) video
  encode with a CPU fallback.


### Future Improvements

*noted areas of improvement, probably will not be addressed in the near future as current workflow is deemed sufficient*

| Idea | Notes |
|------|-------|
| Duet Mode | Alignment and visual design support for songs with multiple singers and separate parts |
| Playlist / batch processing | Process a whole album/playlist (pairs with batch mode) |
| Lyric-artifact warnings | Auto-detect [common issues](docs/Usage.md#lyrics--fetch-the-words) with supplied lyrics, such as repeat shortcuts (`(x4)`, `[Chorus]`), and scrape footers before aligning |
| Faster render iteration | Draft (low-res) render mode; pipe raw frames to FFmpeg stdin |
| Intro trimming | Symmetric to render [`--tail`](docs/Usage.md#render--make-the-video) for long instrumentals at start of song |
| Syllable-level fill | Sub-word fill granularity |
| Alternative aligners or separators | More options or possible improvements over current models |
| Expanded language support | Automatic alignment is currently only usable for English; some of the models used have support for other languages |
| Automated instrumental search | Find official instrumental uploads instead of always separating |


### Out of Scope

Deliberately not planned for this project

- Lyric-site scraping (Genius/AZLyrics/etc.)
  - only LRCLIB and lyrics.ovh free APIs used currently
  - site scraping is a trivial addition, but not encouraged by lyric sites.
  - users can easily copy-paste from lyric sources of their choice
- GUI or web app
  - while a CLI tool represents a barrier to entry, this project was created and designed for personal use. [contributions](#contributing) are welcome to make this more user-friendly
- Real-time / live use
  - this seems very useful, but other tools exist to generate videos with direct interaction. so this project can provide an alternative method
- Advanced visual design elements
  - aim is to simply get the job done, but some functional improvements could be added. such as real-time indication on instrumental wait bars


## AI Acknowledgement

> **Built with [Claude Code](https://claude.com/claude-code) (Anthropic).** The
> architecture, feature scope, model choices, and the iterative timing/QA loops
> were human-planned and human-directed through interactive development.

## Contributing

Open to improvements, bug fixes, and ideas. See
**[CONTRIBUTING](CONTRIBUTING.md)**. A few notes:

- The rendered output is intentionally bare-bones in visual design and
  feature set. Forks with notable improvements could be linked here.
- This project was developed with Claude Code; a `CLAUDE.md` can be provided 
  to continue in that workflow.

---
