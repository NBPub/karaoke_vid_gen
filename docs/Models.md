# Models

This page describes the machine-learning models the pipeline uses, why they were chosen, how their
parameters were set, and what head-to-head testing showed. A guiding constraint
shapes everything here: **the lyrics are already known.** The job is never
speech-to-text; it is to attach accurate start/end times to words contained in `lyrics.txt` for each song folder.

**Contents**

- [Source separation — Demucs](#source-separation--demucs)
  - [Known limitation](#known-limitation)
- [Alignment — two approaches](#alignment--two-approaches)
- [Whisper parameters](#whisper-parameters)
- [A/B: Whisper vs MMS_FA](#ab-whisper-vs-mms_fa)
- [Alternative models](#alternative-models)

## Source separation — Demucs

Splitting a song into a vocal stem and a vocals-removed backing is done with
**[Demucs](https://github.com/adefossez/demucs)** (`htdemucs`, on GPU). The
vocal stem feeds alignment; the backing becomes the karaoke instrumental. Demucs
was chosen for strong, widely-used music source separation with a simple Python
API and reliable CUDA support.

### Known limitation

Demucs separates into four stems (vocals / drums / bass /
other), and vocal-like production elements, such as a recurring "woah" hook,  get routed into the *vocals* stem and thus removed from the karaoke
instrumental. 

Where such an element sits in a lead-free span you can recover it
with a [no-extract interval](Features.md#no-extract-intervals); but where it overlaps the lead vocal there is no clean way to keep only the hook.

## Alignment — two approaches

**Alignment** here means attaching a start/end time to each *already-known* lyric
word: matching the known text to where it occurs in the audio, never transcribing
it. It runs on the **isolated vocal stem** and is swappable between two
implementations with different methods, and so different failure modes.

### Whisper aligner (Whisper ASR + reconciliation) — the default

Uses [OpenAI Whisper](https://github.com/openai/whisper) for automatic speech recognition, but keeps only its word-level timestamps as anchors, not its transcript. A sequence-alignment step then reconciles the *known* lyric words against Whisper's recognized words: matched words borrow the timestamp, and unmatched runs are interpolated between neighbours. Pairing ASR anchors with that reconciliation is what makes this a *hybrid* approach (hence "the hybrid aligner" elsewhere in the docs): it trusts Whisper's timing where recognition is reliable and falls back to interpolation where it isn't. Because anchors are spread across the whole song, a mishandled patch (a screamed or heavily repeated chorus) **stays local** instead of throwing off the rest: the property a cold, whole-song first pass needs most.

### MMS_FA (forced alignment)

**[TorchAudio's MMS_FA](https://pytorch.org/audio/stable/generated/torchaudio.pipelines.MMS_FA.html)**
bundle does **CTC forced alignment**: given known text and audio, it finds, frame
by frame, where each word of the *provided* text occurs. It doesn't transcribe:
it places known words, so it's frame-accurate and drift-free over whatever window
it's given. Used both as a selectable whole-song aligner and for the localized reflow inside [`nudge`](Features.md#nudge-toolkit), because it excels
on a *bounded* run of words

## Whisper parameters

Defaults live in the config and were carefully chosen from experimentation during the development of this project. The parameters are all in
[Configuration](Configuration.md#configuration).

**If you want to change them:** 
 - raising the model size is reasonable if your
material is clean/sung rather than screamed/dense
 - raise `best_of_n` toward `5`
(and nudge the sample temperature up) if hard passages still under-anchor, or drop it to `1` for a faster deterministic run
 - experiment with [onset snapping](Configuration.md#align) when assessing karaoke review renders and tailor to your tastes

### Model size: `medium`

Counter to "bigger is better," experimentation found that `medium` was the sweet
  spot: larger sizes did *worse* (they lean harder on language priors and tend to
  "tidy" or hallucinate words on sung/screamed audio, corrupting the timestamp
  anchors), and smaller sizes dropped or mis-timed words on fast passages. For this use case, faithful timing, and not better transcripts are desired.


### Best-of-N draws: `3` 

Decoding starts from the greedy pass (temperature 0, fully reproducible), then takes N−1 additional sampled draws at a low temperature and keeps whichever anchors the most known words. Quality never drops below the deterministic baseline; the extra draws only help: on messy or overlapping vocals they claw back words a single greedy pass under-anchors. 

In practice **`3` was the best all-round value** across the songs this was tuned on: a clear lift over greedy (`1`) on hard passages, with diminishing returns and ~N× transcription cost above it (`5` squeezes out a little more on the densest, screamed material). Set it to `1` for the fastest, purely deterministic run.

### Onset snapping + a small lead

Each word's start is nudged back to the true 
vocal onset, then given a small uniform head-start so the fill slightly 
anticipates the voice (the karaoke "sing-ahead" feel).

## A/B: Whisper vs MMS_FA

The two aligners fail and succeed differently; therefore the tool keeps **both** and lets you compare per song via the [`ab`](Usage.md#ab--compare-the-two-aligners) command. General findings from testing across  many songs (genres from sung pop to dense rap):

- **MMS_FA tends to be tighter and more literally accurate**
  - it tracks the sung rhythm close to syllable resolution and generally needs fewer fixes
  - it particularly suits **quick / rap / staccato** delivery.
  - fills for the last word of a line tend to end early
- **Whisper is looser and smoother**
  - its blended timings can read as less choppy (sometimes preferable)
  - fills for the first word of a line tend to start late
  - it sometimes handles **repeated sections and held-note line-ends** better than MMS 
  - but it makes more outright placement mistakes on a given song, and on dense fast delivery it can fall behind and never recover.
- **Both are weakest on heavily repeated sections**
  - for example, chant-like choruses. neither reliably tracks which repeat is which.
- **Shared weakness — held notes:** 
  - both tend to end a line's fill a touch early on a sustained final note; expect to extend those ends by hand. Which model holds a given note better is song-dependent.
- **Opposite catch-up failure modes on hard passages:** 
  - Whisper can *lag then cram* (start following lines early, eat instrumental breaks) to claw back lag
  - MMS can *leap then stall* (jump ahead to an un-sung line, then fill it slowly).
  - Both distort timing around difficult sections, in opposite directions.

**Practical takeaway:** because a song usually gets hand-cleanup anyway, MMS_FA's
accurate line *starts* make it the **lower-effort base** more often than not, with
select Whisper timings (smoother fills, better-held repeats/ends) copied in where
they win. When each aligner is better on a different region, the pragmatic result
is a **per-section hand-combine**, not a wholesale choice. Whisper remains the
safer *cold whole-song first pass* (its errors stay local); MMS_FA shines in
*bounded, human-seeded* nudges.

## Alternative models

The design isolates separation and alignment behind thin interfaces, so swapping
in another model is mostly a matter of a new adapter that produces the same
outputs (a vocal stem; word-level timings for known text).

Whisper throughput isn't a bottleneck here, so speed alone isn't a reason to
switch. The likelier draw is memory: a drop-in reimplementation such as
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) (a CTranslate2 port of
Whisper) runs the same models with a smaller VRAM footprint and would slot in
behind the Whisper-aligner interface, which could help on memory-limited GPUs.

- **Separation:** newer or heavier Demucs variants (e.g. a 6-stem model), or other
  separators such as
  [Spleeter](https://github.com/deezer/spleeter) or
  [Open-Unmix](https://github.com/sigsep/open-unmix-pytorch). None solves the
  vocal-like-hook limitation above, but some trade quality against speed
  differently.
- **Alignment:** other forced aligners — e.g.
  [WhisperX](https://github.com/m-bain/whisperX) (Whisper + phoneme-level
  alignment) or the
  [Montreal Forced Aligner](https://montreal-forced-aligner.readthedocs.io/) —
  could slot in as a third aligner behind the same interface. The bar for a good
  fit is the same one that shaped the current choices: attach faithful *timing* to
  the known words, and keep any mistakes *local*.

These integration notes are general: the point is that the thin interfaces make
such swaps tractable: none of these alternatives is wired up today.
