# Gravitas

**Interview transcription that measures narrative gravity.**

Gravitas turns a recorded research interview into usable qualitative data: a speaker-labeled transcript that two independent speech engines agree on, with the analytically heavy moments — the emotional displays, the stories told twice, the dialogue re-enacted, the timelines that collapse — flagged where they happen and backed by the interviewee's face on camera. You point it at a recording (or a folder of them) and get back a Word document you can code in and a JSON record a pipeline can read.

It's the `/interview` skill, a fork of Brad Bonanno's [claude-video](https://github.com/bradautomates/claude-video). The upstream `/watch` skill ships here unchanged; [see below](#also-included-watch).

---

## Why this exists

A researcher with a corpus of recorded interviews has no good option between two bad ones. Hand-transcription is slow and expensive. Single-engine machine transcription makes silent errors — concentrated exactly where they hurt: proper nouns, jargon, emotional overlapping speech — with no way to know where. Neither tells you who is speaking. And the richest layer, the moments where the telling carries unusual weight, only surfaces if a human listens to every minute.

Gravitas attacks all three:

- **Errors become visible instead of silent.** Every interview is transcribed twice — Groq's `whisper-large-v3` and OpenAI's `whisper-1` — and the two outputs are diffed word by word. Where they disagree is exactly where transcription is uncertain. Each disagreement is adjudicated with a logged rationale, so the final transcript is a decision, not a guess, and every decision is inspectable.
- **Speakers get labeled, with a reliability number.** A panel of three independent analysts labels every turn `INTERVIEWER`, `INTERVIEWEE`, or `OTHER`. Their agreement is recorded per turn as a concordance score. Turns that fit neither party — a third voice, crosstalk, a to-camera aside — are labeled `OTHER`, never forced into the dyad.
- **Gravity is coded against a fixed construct.** Interviewee turns are scored against a versioned codebook of observable discourse markers. Each flagged moment carries its marker type, a salience rating, a verbatim quote, a timestamp, and — for video — a burst of frames pulled at that exact moment, read as corroborating or disconfirming evidence.

The whole pipeline is automatic and produces persistent, citable artifacts. The compensating control for "no human in the loop" is total evidence retention: every flag and every adjudication keeps its evidence, so any claim can be audited after the fact without re-running.

## What one interview produces

Everything lands next to the media in `<stem>_interview/`:

- **`transcript.docx`** — a speaker-labeled, timestamped transcript. Each gravity moment is a Word comment anchored on the exact quoted span (marker, emotion, salience, the frame evidence). The accuracy claim is printed in the document itself, because the .docx travels alone in document-based coding workflows. Opens and codes like any transcript.
- **`sidecar.json`** — the machine-readable research record: every segment with its speaker label and concordance score, the full adjudication audit log (both engine readings, the chosen text, the rationale), every flag with its evidence bundle, and run metadata (engines, codebook version, any degradation).
- **`work/` and `frames/`** — every intermediate, retained as the audit trail. Not cleaned up.

Batch runs add a corpus-level summary of flags across the whole set.

## How it works

The skill drives a deterministic Python pipeline stage by stage; the judgment (adjudicating diffs, labeling speakers, coding gravity) is Claude's, the mechanics are the scripts'.

1. **Dual transcription.** Audio is extracted once (mono 16 kHz) and sent to both Whisper engines; anything over the API cap is chunked automatically.
2. **Diff.** The two transcripts are aligned word-by-word. Agreements become the base transcript; each disagreement becomes a numbered span with both readings and surrounding context.
3. **Adjudication.** Claude resolves every disagreement — choosing a reading, or deleting a hallucinated filler — and logs a short rationale. The result is the final transcript plus an audit log.
4. **Diarization panel.** Three independent analysts label every unit `INTERVIEWER` / `INTERVIEWEE` / `OTHER`; a concordance function merges their votes into a per-unit label and score, with `UNCLEAR` for turns that don't reach agreement.
5. **Gravity pass.** Interviewee turns are coded against the codebook. Each flag is validated against the schema (verbatim quote, valid marker, salience in range) before it can proceed.
6. **Frame evidence.** For video, a short burst of frames is extracted at each flagged moment only — never a full-video scan — and read as visual corroboration. A contradiction is recorded, not suppressed.
7. **Render.** The `.docx` and `sidecar.json` are written; the honest accuracy claim is stamped into both.

## The narrative-gravity codebook

The construct is a shipped, versioned data file (`skills/interview/scripts/codebook.json`, currently **v1.0.0**), so any analysis run can cite the exact definition it used. A moment carries narrative gravity when it shows one or more observable markers:

| Marker | What it captures |
|--------|------------------|
| `emotional_display` | A felt emotion tied to the content (carries an emotion label) |
| `repetition` | The interviewee returns to the same event or claim unprompted |
| `quoted_speech` | Dialogue re-enacted rather than reported ("and he said to me…") |
| `temporal_shift` | The telling breaks timeline — historic present, sudden jumps |
| `disfluency_cluster` | A localized spike in false starts or fillers against baseline |
| `pause_then_rush` | A marked silence followed by dense, rapid speech |

Emotional displays draw from a fixed vocabulary of 14 emotions (anger, sadness, excitement, fear, joy, surprise, disgust, shame, pride, grief, anxiety, frustration, relief, contempt). Every flag carries a **salience** rating from 1 (incidental) to 5 (interview-defining). Zero flags is a valid outcome for a flat interview — the tool does not invent gravity.

## Honest claims

Gravitas never claims a transcript is "error-free" — the architecture can't guarantee that, and the tool's language says so. The claim it does make, printed in both artifacts, is one of:

- **`dual-engine verified with logged adjudication`** — both engines ran, every disagreement was adjudicated.
- **`… ; INCOMPLETE — transcription gaps recorded`** — a chunk failed; the gap is named in the record.
- **`single-engine UNVERIFIED`** — only one key was configured; there was nothing to cross-check.

Accepted, on-the-record limits: the diff can't catch an error both engines make identically; the text-only diarization panel can share blind spots on acoustically ambiguous turns; adjudication happens without hearing the audio; and automatic emotion flags are machine claims — mitigated only by the retained evidence, which lets you overturn any one of them.

## Install

Gravitas is the `skills/interview/` skill. It's self-contained (pure-stdlib Python over `ffmpeg`; `yt-dlp` only for URL sources), so it installs as a folder.

**Claude Code (symlink the working tree):**
```bash
git clone https://github.com/Jerrymwolf/gravitas.git
ln -s "$(pwd)/gravitas/skills/interview" ~/.claude/skills/interview
```

**Any Agent Skills host (Codex, Cursor, Gemini CLI, …):** point your host's skill loader at `skills/interview/` — `SKILL.md` and its `scripts/` copy as one unit and resolve their own paths on any host.

## Setup

The first run's `preflight` checks for `ffmpeg`/`ffprobe` and both Whisper keys. Put them in `~/.config/watch/.env` (mode `0600`):

```
GROQ_API_KEY=...      # console.groq.com/keys — whisper-large-v3
OPENAI_API_KEY=...    # platform.openai.com/api-keys — whisper-1
```

Both keys unlock the dual-engine verification. A single key still runs the whole pipeline, but every artifact is honestly marked `single-engine UNVERIFIED`. Cost is small — a 7-minute interview transcribes on both engines for well under a dime.

**Data governance:** audio (never the video) is uploaded to Groq and OpenAI for transcription. Confirm that fits your IRB / data-management plan before running human-subjects recordings.

## Usage

```
/interview ~/Interviews/bei_017.mp4          # one recording
/interview ~/Interviews/wave2/               # folder — every file, then a corpus summary
```

- **Local files first** (`.mp4/.mov/.mkv/.webm`, plus audio-only `.m4a/.wav/.mp3/…` — the frame pass is skipped and noted). URLs work through `yt-dlp` for non-sensitive material.
- **Batch mode** processes each file into its own artifact pair and names any file that fails, so nothing silently vanishes from the corpus count.
- **Two-speaker with anomaly handling** by default; a third voice or crosstalk lands as `OTHER`, not a misattribution.

Under the hood the skill runs `scripts/interview.py` stages — `preflight`, `transcribe`, `finalize`, `concordance`, `validate-flags`, `frames`, `render`, `discover`, `corpus-summary` — exchanging JSON judgment files through the work dir. You invoke `/interview`; the skill orchestrates them.

## Also included: /watch

The upstream `/watch` skill ships here unchanged — it gives an agent a general video input (paste a URL or path, ask a question; it pulls captions or Whisper-transcribes, extracts scene-aware frames, and answers grounded in what's on screen). Gravitas doesn't modify it, so it keeps working for everyday video Q&A and upstream fixes merge cleanly. Full `/watch` documentation lives at the [upstream repo](https://github.com/bradautomates/claude-video).

## Structure

```
.
├── skills/
│   ├── interview/                # Gravitas — the product
│   │   ├── SKILL.md              # the contract Claude reads on /interview
│   │   └── scripts/
│   │       ├── interview.py      # CLI orchestrator — one subcommand per pipeline stage
│   │       ├── dual_transcribe.py# dual-engine transcription + word-level diff + adjudication apply
│   │       ├── analyze.py        # diarization units, panel concordance, flag validation, frame bursts
│   │       ├── render.py         # OOXML .docx (anchored comments) + JSON sidecar
│   │       ├── stt.py            # Whisper client (verbatim copy of watch's whisper.py)
│   │       ├── framegrab.py      # timestamp-pinned frame extraction (subset copy of watch's frames.py)
│   │       └── codebook.json     # the versioned narrative-gravity construct
│   └── watch/                    # upstream skill — unchanged (see "Also included")
├── tests/                        # pytest suite (ffmpeg-synthesized clips, no network)
├── CLAUDE.md → AGENTS.md         # generic-agent entry point
└── docs/                         # implementation plan (spec: issue #1)
```

## Develop

```bash
python3 -m pytest -q              # full suite (interview + upstream watch), no network
```

The interview scripts stay self-contained — `stt.py` / `framegrab.py` are deliberate copies of watch's `whisper.py` / `frames.py` (kept byte-close so upstream diffs stay legible), never cross-imported. The pure cores (diff, concordance, renderer) are unit-tested in isolation; the LLM judgment lives in `SKILL.md` and is accountable through the retained artifacts, not assertions.

## Credits & license

MIT. Fork of [bradautomates/claude-video](https://github.com/bradautomates/claude-video) by Brad Bonanno — the `/watch` skill, the Whisper client, and the ffmpeg plumbing Gravitas builds on are his. Whisper transcription via [Groq](https://groq.com) and [OpenAI](https://openai.com).
