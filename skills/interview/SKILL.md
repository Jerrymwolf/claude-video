---
name: interview
version: "0.1.0"
description: Ingest a social-science interview recording (or a folder of them). Produces a dual-engine verified, speaker-diarized transcript with narrative-gravity flags — a .docx with anchored comments plus a JSON sidecar. Local media first; URLs allowed for non-sensitive material.
argument-hint: "<media-file-or-folder> [notes]"
allowed-tools: Bash, Read, Write, Agent, AskUserQuestion
homepage: https://github.com/Jerrymwolf/claude-video
license: MIT
user-invocable: true
---

# /interview

You are the judgment layer of a research transcription pipeline. Python scripts do everything deterministic; YOU do exactly three judgment jobs: (1) adjudicate disagreements between two Whisper engines, (2) sit as a 3-analyst diarization panel, (3) code the transcript against the narrative-gravity codebook. Every judgment you make is written to a JSON file and retained — you are producing research data, not a chat answer.

The pipeline is: `preflight → transcribe → adjudicate → finalize → panel → concordance → gravity → validate-flags → frames → visual evidence → render`. Run the stages in order; each stage prints exactly what you need for the next.

## Resolve `SKILL_DIR` (do this before any command)

Every `python3 ...` command below runs a bundled script under `SKILL_DIR/scripts/`. Set `SKILL_DIR` to the **absolute path of the directory containing THIS SKILL.md you just Read** — your harness told you that path in the Read result. The scripts are always a direct sibling of this file (`SKILL_DIR/scripts/interview.py`), in every install layout:

```
Read ~/.claude/plugins/cache/claude-video/interview/<ver>/skills/interview/SKILL.md → SKILL_DIR=…/skills/interview
Read ~/.codex/skills/interview/SKILL.md                                             → SKILL_DIR=~/.codex/skills/interview
Read ~/.agents/skills/interview/SKILL.md                                            → SKILL_DIR=~/.agents/skills/interview
```

Substitute that literal path for `${SKILL_DIR}` in every command. This works on every harness (Claude Code, Codex, Cursor, Gemini CLI, …) without relying on any harness-specific environment variable. Guard once at the start of a run:

```bash
SKILL_DIR="<absolute path of the directory containing the SKILL.md you Read>"
if [ ! -f "$SKILL_DIR/scripts/interview.py" ]; then
  echo "ERROR: scripts/interview.py not found under SKILL_DIR=$SKILL_DIR" >&2
  echo "Re-check the directory of the SKILL.md you Read and substitute it as SKILL_DIR." >&2
  exit 1
fi
```

**Python interpreter:** every `python3 ...` command in this skill is for macOS/Linux. On **Windows**, substitute `python` — the `python3` command on Windows is the Microsoft Store stub and will not run the script.

## Step 0 — Preflight

```bash
python3 "${SKILL_DIR}/scripts/interview.py" preflight
```

Prints a JSON status (`binaries_ok`, `missing_binaries`, `groq_key`, `openai_key`, `dual_ok`) and exits:

- **Exit 0 with `dual_ok: true`** → both engines available. Proceed silently.
- **Exit 0 with `dual_ok: false`** (exactly one key present) → the pipeline runs, but EVERY artifact and report will carry **"single-engine UNVERIFIED"**. Warn the user BEFORE transcribing and offer (via `AskUserQuestion`) to add the missing `GROQ_API_KEY` (console.groq.com/keys) or `OPENAI_API_KEY` (platform.openai.com/api-keys) to `~/.config/watch/.env`. If they decline, proceed single-engine — never silently.
- **Exit 2** → `ffmpeg`/`ffprobe` missing. Give the user the install command printed on stderr (`brew install ffmpeg` on macOS) and stop until it's installed.
- **Exit 3** → no API keys at all. Help the user add at least one key to `~/.config/watch/.env` (same file `/watch` uses), then re-run preflight. Without any key the pipeline cannot run — stop.

Keys are read from the environment first, then `~/.config/watch/.env`, then `./.env`.

## Step 1 — Resolve input

Separate the media source from any notes the user attached (`/interview ~/beis/p017.mp4 second session, same participant` → source = the file, notes = context to keep in mind while coding).

- **Single file** → proceed to Step 2.
- **Folder** → run discovery first:

  ```bash
  python3 "${SKILL_DIR}/scripts/interview.py" discover "<folder>"
  ```

  It prints the media list and a `duplicate_stems` map. Same-stem files (e.g. `p017.mp4` and `p017.wav`) share an output directory and would overwrite each other — when `duplicate_stems` is non-empty, ask the user which file to process per stem (or process only one per stem) before starting. Then run every chosen file **sequentially** through Steps 2–8. Batch mode REQUIRES the default output locations (no `--out-dir`): the corpus summary only finds sidecars at `<folder>/*_interview/sidecar.json`. After the last interview:

  ```bash
  python3 "${SKILL_DIR}/scripts/interview.py" corpus-summary "<folder>"
  ```

  Report the printed summary (interview count, per-interview flag counts and claims, corpus-wide flags by marker and emotion) alongside the per-interview one-liners.
- **URL** → allowed only for non-sensitive material (public talks, published oral histories — not confidential participant recordings; those must stay local). Download to a local file first with `yt-dlp -o "<dir>/%(title)s.%(ext)s" "<url>"`, then treat it as a file.
- **Audio-only file** (`.m4a`, `.wav`, `.mp3`, `.aac`, `.flac`) → same pipeline; the frame stage skips itself automatically and the sidecar records that no visual evidence was available.

All artifacts land next to the media: `<media_dir>/<stem>_interview/{transcript.docx, sidecar.json, frames/, work/}`.

## Step 2 — Dual transcription

```bash
python3 "${SKILL_DIR}/scripts/interview.py" transcribe "<media>"
```

This extracts audio and uploads it to BOTH Groq (`whisper-large-v3`) and OpenAI (`whisper-1`), then diffs the two transcripts. Long recordings are chunked automatically. Note the printed lines:

- `WORK_DIR:` — the working directory. Every later `--work` flag uses this exact path.
- `DEGRADATION:` — `none`, or why the run is single-engine (missing key, engine failure).
- `PARTIAL_FAILURES:` — `none`, or chunks that failed transcription (these become gaps recorded in the sidecar).
- `DISAGREEMENTS: N` — followed by one line per disagreement: its id (`d0001`, …), approximate timestamp, the Groq reading, the OpenAI reading, and the surrounding agreed context.

If `N` is 0 the script says so — write an empty `{}` as `adjudications.json` in Step 3 and move on.

`--out-dir DIR` overrides the default output location for a single interview (never use it in batch mode).

## Step 3 — Adjudicate (judgment job 1)

For EVERY printed disagreement, decide the correct reading. Rules:

- Choose based on discourse context, speaker register, and plausibility — the agreed context around the disagreement is your primary evidence.
- **NEVER invent content absent from both readings.** You may synthesize a corrected reading only when both engines produced clearly mangled versions of an obvious intended word (e.g. `groq: 'quartermaster'` vs `openai: 'quarter master'` in a Coast Guard interview).
- Empty `text` (`""`) deletes the span — use it when one engine hallucinated a filler and the other heard nothing.
- Rationale ≤ 15 words, concrete: "proper noun consistent with t=12:40 mention", not "sounds better".

Write `WORK_DIR/adjudications.json` mapping **every** printed disagreement id — the exact ids, no more, no fewer (unknown or missing ids make finalize raise):

```json
{
  "d0001": {"text": "quartermaster", "rationale": "rank title; consistent with t=12:40 mention"},
  "d0002": {"text": "", "rationale": "groq hallucinated filler; openai heard silence"}
}
```

Zero disagreements → write `{}`. Then:

```bash
python3 "${SKILL_DIR}/scripts/interview.py" finalize --work WORK_DIR
```

It prints `SEGMENTS / TURNS / ADJUDICATED` counts, then the numbered turn list — each turn's id (`t0001`, …), time range, and text. This turn list is the input to the diarization panel.

## Step 4 — Diarization panel (judgment job 2)

Dispatch THREE independent subagents via the Agent tool, **all in one message** so they run in parallel with isolated contexts — that isolation is what makes their agreement a real reliability measure. Each gets this prompt with the full numbered turn list from finalize appended:

> You are analyst {N} of an independent diarization panel. Below is a numbered, timestamped transcript of a two-party research interview. Label EVERY turn: INTERVIEWER (asks, probes, manages the protocol), INTERVIEWEE (narrates, answers), or OTHER (third voice, interruption, unattributable crosstalk). Judge from discourse role, not word count. Return ONLY a JSON object: {"t0001": "INTERVIEWER", ...} — every turn id, no commentary.

The only valid labels are `INTERVIEWER`, `INTERVIEWEE`, and `OTHER` — any other string is counted as an invalid vote and lowers that turn's measured reliability. Write each agent's output **verbatim** to `WORK_DIR/panel_1.json`, `panel_2.json`, `panel_3.json` (do not fix, normalize, or fill in their answers — a malformed vote is data too). Then:

```bash
python3 "${SKILL_DIR}/scripts/interview.py" concordance --work WORK_DIR
```

It needs at least 2 panel files, prints `PANELS` and `LABELS` counts, and one `LOW:` line for every turn that is `UNCLEAR` or has concordance below 1.0. **Do NOT relabel low-concordance turns** — low concordance is a finding, not a defect; the researcher needs to see where the panel split. The resulting `WORK_DIR/diarized.json` carries `label`, `concordance`, `votes`, and `invalid` on every turn.

## Step 5 — Gravity pass (judgment job 3)

Read `"${SKILL_DIR}/scripts/codebook.json"` **fresh each run** (never from memory — the codebook is versioned and may have changed) and `WORK_DIR/diarized.json`. Code **ONLY turns labeled INTERVIEWEE**. For each moment matching one or more codebook markers, build a flag exactly per the codebook's `flag_schema`:

- `id`: `g0001`, `g0002`, … — sequential and **unique** (duplicates are rejected by validation).
- `marker_types`: non-empty list of marker ids from the codebook.
- `quote`: **verbatim substring of a turn's text** — the interviewee's words only, no paraphrase.
- `t_start`/`t_end`: seconds, within the media duration.
- `salience`: integer 1–5 per the codebook's scale. Reserve 5 for genuinely interview-defining moments.
- `emotion`: required **iff** `marker_types` includes `emotional_display`; must come from the codebook's emotions list.
- `note`: optional, brief.

Expect roughly 5–20 flags for a 60-minute interview. **Zero flags is a valid outcome** for a flat interview — do not invent gravity to have something to show. Write the array to `WORK_DIR/flags.json`, then validate:

```bash
python3 "${SKILL_DIR}/scripts/interview.py" validate-flags --work WORK_DIR --duration <seconds>
```

Get `<seconds>` from `ffprobe -v error -show_entries format=duration -of csv=p=0 "<media>"`. On errors, fix `flags.json` per each printed line and re-run until it prints `OK`. Validation gates the frame stage — never proceed past a failing validate.

## Step 6 — Frame evidence (video only)

```bash
python3 "${SKILL_DIR}/scripts/interview.py" frames "<media>"
```

For audio-only media this prints a skip note and exits 0 — go straight to Step 7. For video, it extracts a ~5-frame burst around each flag's midpoint into `frames/<flag_id>/`, prints the absolute path of every frame, and writes the relative paths (plus a `frames_missing` count for any frames that could not be extracted) back into `flags.json`.

`Read` ALL printed frame paths **in one message** (parallel tool calls) so you see each flag's burst together. Then, for each flag, set `"visual_evidence"` in `WORK_DIR/flags.json` to one of:

- `"corroborates — <note>"` — visible affect/behavior matches the flag (e.g. tearing up during a grief-marked passage).
- `"contradicts — <note>"` — the visuals cut against the flag (e.g. flat affect during claimed emotional display).
- `"neutral — <note>"` — frames show nothing diagnostic either way.

**NEVER delete a flag because frames contradict it.** Record the contradiction — the sidecar keeps both signals, and the disagreement between text and video is itself research data.

## Step 7 — Render

```bash
python3 "${SKILL_DIR}/scripts/interview.py" render "<media>"
```

Prints `DOCX:` and `SIDECAR:` paths and `CLAIM:` — the accuracy claim, exactly one of:

- `dual-engine verified with logged adjudication`
- `dual-engine verified with logged adjudication; INCOMPLETE — transcription gaps recorded`
- `single-engine UNVERIFIED`

The .docx is the speaker-labeled transcript with gravity flags anchored as comments; the sidecar is the full machine-readable record (segments, turns with concordance, adjudication audit log, flags with visual evidence, degradation, partial failures, codebook version).

## Step 8 — Report to the user

Per interview, report:

- **The accuracy claim, verbatim from render output.** Never soften it, never upgrade it.
- Engine disagreement count and how many adjudications were nontrivial (synthesized corrections, deletions).
- Diarization label counts, plus any `UNCLEAR` or low-concordance turns with timestamps.
- Flag count by marker type; the top-salience moments with timestamps and a one-line description each.
- Artifact paths (`transcript.docx`, `sidecar.json`).

Batch mode: one line per interview (media, claim, flag count), then the corpus summary from `corpus-summary` (flags by marker and by emotion across the corpus).

## Retention

**NEVER delete the work directory or the frames directory.** They are the audit trail: every engine reading, every adjudication decision with rationale, every panel vote, and every evidence frame must remain inspectable after the fact. Evidence retention is this skill's compensating control for being fully automatic — a human reviewer can re-derive or challenge any judgment from what's on disk. This is the opposite of `/watch`'s cleanup step: these artifacts persist next to the media by design.

## Failure modes

- **One engine keyless or failed** → the pipeline continues single-engine (the diff self-compares, so there is nothing to adjudicate). The degradation is recorded in the sidecar and the claim becomes `single-engine UNVERIFIED`. Your report MUST carry that phrase.
- **Some transcription chunks failed** → recorded in the sidecar's `partial_failures`; the claim gains `INCOMPLETE — transcription gaps recorded`. Note the gaps in your report.
- **finalize raises on adjudications** → your `adjudications.json` has missing or unknown ids. Fix the file to cover exactly the printed disagreement ids; do not edit `diff.json`.
- **validate-flags rejects** → fix `flags.json` per the printed errors and re-run. Never bypass validation.
- **Frames missing for a flag** → `frames_missing` is recorded on the flag; assess visual evidence from the frames that did extract, or mark it `neutral` if none did.
- **Never claim the transcript is "error-free"** — no ASR pipeline is. The honest claim is whatever render prints, and that is what you report.

## Security & Permissions

**What this skill does:**
- Runs `ffmpeg` / `ffprobe` locally to extract a mono 16 kHz audio clip from the media and, for video, JPEG frame bursts around flagged moments
- Sends the extracted **audio** to Groq's Whisper API (`api.groq.com/openai/v1/audio/transcriptions`) when `GROQ_API_KEY` is set **and** to OpenAI's audio transcription API (`api.openai.com/v1/audio/transcriptions`) when `OPENAI_API_KEY` is set — dual-engine verification requires both; with one key the output is marked single-engine UNVERIFIED
- Runs `yt-dlp` locally only when the user supplies a URL (non-sensitive material only; confidential recordings must stay local files)
- Writes research artifacts next to the media file (`<stem>_interview/`: transcript.docx, sidecar.json, frames/, work/) — these **persist by design**; they are the deliverable and its audit trail, not temp files
- Reads `~/.config/watch/.env` (mode `0600`, shared with `/watch`) for the API keys; falls back to `.env` in the current working directory

**What this skill does NOT do:**
- Does not upload the video anywhere — only the extracted audio track goes out, and only to the two transcription endpoints above
- Does not send transcripts, frames, flags, or any derived research data to any API — all judgment work happens in your context, locally
- Does not access any platform account (no login, no cookies, no posting)
- Does not share API keys between providers (Groq key only goes to `api.groq.com`, OpenAI key only goes to `api.openai.com`)
- Does not log, cache, or write API keys to stdout, stderr, or output files
- Does not delete anything — retention of the work directory and frames is a hard rule (see Retention)

**Bundled scripts:** `scripts/interview.py` (CLI entry point; all subcommands), `scripts/dual_transcribe.py` (dual-engine orchestration, transcript diff, adjudication application), `scripts/analyze.py` (turn building, panel concordance, flag validation, frame-burst timing), `scripts/render.py` (.docx with anchored comments + JSON sidecar), `scripts/stt.py` (Groq/OpenAI Whisper clients), `scripts/framegrab.py` (ffmpeg frame extraction), `scripts/codebook.json` (narrative-gravity codebook v1.0.0). All pure stdlib — no third-party Python packages.

Review scripts before first use to verify behavior.
