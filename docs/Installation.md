# Installation

**Contents**

- [Prerequisites](#prerequisites)
- [Python environment](#python-environment)
- [PyTorch + CUDA (GPU)](#pytorch--cuda-gpu)
- [FFmpeg](#ffmpeg)
- [YouTube & a JavaScript runtime](#youtube--a-javascript-runtime)
- [Models](#models)
- [Per-OS notes](#per-os-notes)
- [Expected warnings](#expected-warnings)
- [Verify](#verify)

> Developed and tested on **Windows 11 with an NVIDIA GPU (CUDA)**. Linux with an
> NVIDIA GPU should work the same way; other setups are untested. See
> [Per-OS notes](#per-os-notes).

## Prerequisites

- **Python 3.12.** The ML wheels this project depends on (PyTorch/CUDA,
  torchaudio, Demucs) are most reliable on 3.12; newer versions are not
  recommended.
- **An NVIDIA GPU + CUDA**, strongly recommended. Separation and alignment run on
  the GPU; there is a CPU fallback, but it is slow.
- **FFmpeg** available on your `PATH`.

## Python environment

First get the code: clone the repository (or download it as a ZIP from GitHub
and extract):

```bash
git clone https://github.com/NBPub/karaoke_vid_gen.git
cd karaoke_vid_gen
```

Then create a virtual environment:

```bash
python -m venv .venv
# activate:
.venv\Scripts\activate         # Windows
source .venv/bin/activate      # Linux / macOS
```

**Before installing, pick your Whisper model size.** The aligner downloads the
`models.whisper_model` weights (default `medium`, ~1.5 GB) on first use, so if you
want a [different size](Models.md#whisper-parameters), set it in [`config.toml`](Configuration.md#models) first.

> **Alignment needs both model stacks.** It requires **OpenAI `Whisper`** (for the
> hybrid aligner) and **torchaudio's `MMS_FA`** (the forced aligner), both
> installed via [`requirements.txt`](../requirements.txt). Their model weights
> download automatically on first use (see [Models](#models)).

Finally, install the dependencies and the `karaoke` command:

```bash
pip install -r requirements.txt   # dependencies
pip install -e .                  # the karaoke CLI (entry point from pyproject.toml)
```

`requirements.txt` pulls the Python dependencies (PyTorch / torchaudio, Demucs,
OpenAI Whisper, Pillow, soundfile, yt-dlp, and support libraries); `pip install -e .`
installs the `karaoke` command itself. To run the test suite, add the dev extra:
`pip install -e ".[dev]"` (pytest).

## PyTorch + CUDA (GPU)

PyTorch must match your CUDA toolkit. Install the CUDA build from the official
selector at **[pytorch.org](https://pytorch.org/get-started/locally/)** rather
than a plain `pip install torch`. This project was developed against
**torch 2.6.0 + cu124**, matching `torchaudio`. For example:

```bash
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
```

Confirm the GPU is visible:

```bash
python -c "import torch; print(torch.cuda.is_available())"   # -> True
```

If this prints `False`, alignment/separation will fall back to CPU (slow). Set
`models.device` in [`config.toml`](Configuration.md#models) accordingly.

## FFmpeg

FFmpeg handles audio conversion and video encoding (including NVENC). Install it
and ensure it's on your `PATH` (official builds and instructions:
[ffmpeg.org/download](https://ffmpeg.org/download.html)):

- **Windows:** `winget install Gyan.FFmpeg` (or Chocolatey `choco install ffmpeg`).
  If it isn't picked up automatically, add its `bin` directory to `PATH`.
- **Linux:** `sudo apt install ffmpeg` (or your distro's package manager).
- **macOS:** `brew install ffmpeg`.

Verify: `ffmpeg -version`.

## YouTube & a JavaScript runtime

URL ingestion uses **yt-dlp**. Recent yt-dlp versions extract YouTube far more
reliably when a **JavaScript runtime** is available: it's used to solve YouTube's
signature challenges. Without one you'll see:

```text
WARNING: [youtube] No supported JavaScript runtime could be found. ...
YouTube extraction without a JS runtime has been deprecated, and some formats may
be missing.
```

Audio-only downloads often still succeed, but this is getting more fragile as
YouTube tightens. The simplest fix is to install **[Deno](https://deno.land/)**,
which yt-dlp **auto-detects on your `PATH`**, no flag or config needed:

- **Windows:** `winget install DenoLand.Deno`
- **Linux / macOS:** `curl -fsSL https://deno.land/install.sh | sh` (or your
  package manager)

For other supported runtimes and details, see yt-dlp's
**[EJS wiki page](https://github.com/yt-dlp/yt-dlp/wiki/EJS)**. 

*This is not needed if you only ingest local audio files.*

**Keep yt-dlp current.** YouTube changes often and yt-dlp ships fixes to match, so
a stale yt-dlp is the most common cause of extraction failures and `HTTP 403`
errors. If a download fails, update it first: `pip install -U yt-dlp` (or, for the
freshest fixes, the nightly `pip install -U --pre "yt-dlp[default]"`).

## Models

No manual weight downloads are needed; each model fetches its weights on first
use and caches them:

- **Demucs `htdemucs`**: source separation.
- **OpenAI Whisper `medium`**: the Whisper aligner's ASR (a ~1.5 GB download the
  first time; [other sizes](https://github.com/openai/whisper#available-models-and-languages)).
- **torchaudio `MMS_FA`**: the forced aligner.

The first `separate` / `align` run will be slower while weights download. Discussion on model selection and parameters is located in the **[Models](Models.md#models)** documentation page.

## Per-OS notes

- **Windows 11 + NVIDIA (tested).** 
  - The primary development platform. PowerShell and CMD both work; ensure FFmpeg's `bin` is on `PATH`.
- **Linux + NVIDIA.** *(Untested but expected to work)*
  - same steps; install the CUDA PyTorch build matching your driver, and FFmpeg from your package manager.
- **macOS.** *(Untested)* 
  - modern macOS has no CUDA (Apple hasn't shipped NVIDIA
  support in years), so even with an NVIDIA eGPU you'd fall back to CPU, slow for
  separation and alignment. Not a recommended path for regular use.
- **AMD/Intel GPUs.** (*not supported*) 
  - the project targets CUDA. The only theoretical
  route is a ROCm build of PyTorch on Linux; otherwise you're on
  the CPU fallback (set `models.device = "cpu"`).

## Expected warnings

A couple of warnings are normal and safe to ignore:

- **Whisper Triton kernel (Windows).** During Whisper alignment you may see
  `Failed to launch Triton kernels ... falling back to a slower median kernel`.
  Whisper's word-timestamp step prefers a Triton-compiled CUDA kernel, which needs
  a CUDA toolkit and has no reliable Windows support, so it falls back to a
  pure-PyTorch median filter. **The model still runs on the GPU** and the timing is
  identical; only that one step is slower. It does not appear with the `MMS_FA`
  aligner.
- **yt-dlp "No supported JavaScript runtime".** See
  [YouTube & a JavaScript runtime](#youtube--a-javascript-runtime): install Deno
  to clear it and keep YouTube extraction robust.

## Verify

```bash
python -c "import torch; print('cuda', torch.cuda.is_available())"
ffmpeg -version
karaoke --help
```

Expected on success:

- the first prints `cuda True` (a `False` means Torch can't see the GPU, so alignment and separation will run on the slow CPU fallback).
- `ffmpeg -version` prints a version banner, e.g. `ffmpeg version 8.1.1 ...`.
- `karaoke --help` prints the CLI usage and the command list (`acquire`, `separate`, `lyrics`, `align`, `nudge`, `render`, `check`, `ab`, `split`, `all`).

If all three succeed, you're ready: head to **[Usage](Usage.md#usage)** or the
**[Example Workflow](Example%20Workflow.md#example-workflow)**.
