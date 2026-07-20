---
name: interview
version: "0.3.0"
description: Ingest a social-science interview recording (or a folder of them). Produces a dual-engine verified, speaker-diarized transcript coded against a selectable versioned codebook — narrative gravity by default, or moral identity under public confrontation — with an optional episode layer for multi-target recordings. Output is a .docx with anchored comments plus a JSON sidecar. Local media first; URLs allowed for non-sensitive material.
argument-hint: "<media-file-or-folder> [notes]"
allowed-tools: Bash, Read, Write, Agent, AskUserQuestion
homepage: https://github.com/Jerrymwolf/gravitas
license: MIT
user-invocable: true
---

# /interview

You are the judgment layer of a research transcription pipeline. Python scripts do everything deterministic; YOU do exactly four judgment jobs: (1) adjudicate disagreements between two Whisper engines, (2) sit as a 3-analyst diarization panel, (3) segment the recording into episodes, (4) code the transcript against a versioned codebook. Every judgment you make is written to a JSON file and retained — you are producing research data, not a chat answer.

The pipeline is: `preflight → transcribe → adjudicate → finalize → panel → concordance → episodes → coding → validate-flags → frames → visual evidence → render`. Run the stages in order; each stage prints exactly what you need for the next.

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

## Codebook selection (decide once, at Step 1)

Two codebooks ship next to the scripts. A codebook is a versioned data file that **drives behavior** — not documentation:

- `scripts/codebook.json` — **narrative gravity** (emotional display, repetition, quoted speech, temporal shift, disfluency cluster, pause-then-rush). The default. Codes interviewee speech; affect field `emotion`; no episode schema.
- `scripts/codebook_moral_identity.json` — **moral identity under public confrontation** (Bandura's moral-disengagement mechanisms + responsibility acceptance, identity talk, performance markers). Codes BOTH speaker roles; affect field `affect`; enforces the attribution gate; declares `episode_schema` and `arc_schema`.

The declared fields that change what the tool accepts: `coding_scope`, `affect_field`, `affect_vocabulary`, `enforce_attribution_gate`, `episode_schema`, `arc_schema`, and per-marker `requires_affect`. Read the chosen file fresh each run — never from memory.

`--codebook PATH` selects an alternate codebook, and it exists on exactly three stages: `validate-episodes`, `validate-flags`, and `render`. **Pass the SAME `--codebook` to all three.** Each loads it independently and nothing cross-checks them: omitting it at `render` succeeds quietly and stamps `codebook_file: codebook.json` onto a record coded against a different codebook. Fix the literal path once, at Step 1, and reuse it verbatim. `corpus-summary` deliberately takes no `--codebook` — it counts what the sidecars themselves record.

## Exit codes

At the judgment stages, `1` and `2` mean different things and must be handled differently:

- **Exit 1 — a validation finding.** `validate-episodes` prints `INVALID EPISODES:`, `validate-flags` prints `INVALID FLAGS:`, one line per problem. Your judgment file is wrong; fix it per each printed line and re-run.
- **Exit 2 — broken input.** A missing or malformed `episodes.json`, or a `--codebook` path that does not exist or is not a codebook. The message names the file and the exact spot — `ERROR: episodes.json: line 23 column 1 — Illegal trailing comma before end of array`. Nothing was validated. Fix the file or the path; do NOT report this as a finding. (`render --persona ""` is the same class and also exits 2.)

**A crash is not a finding.** `preflight` predates this convention and keeps its own codes (see Step 0). The other hand-authored files — `adjudications.json`, `panel_*.json`, `flags.json` — are not yet routed through the exit-2 path: malformed JSON there surfaces as a raw Python traceback and **exits 1, the same code as a validation finding**, so the exit code alone cannot tell them apart — read the output. A traceback's last line still gives the line and column; re-read the file you just wrote. (One traceback is not about a malformed file at all: a `ValueError` from validate-flags means the stages were run out of order — see Step 6.) Never report a traceback as a research result.

## Step 0 — Preflight

```bash
python3 "${SKILL_DIR}/scripts/interview.py" preflight
```

Prints a JSON status (`binaries_ok`, `missing_binaries`, `groq_key`, `openai_key`, `dual_ok`) and exits:

- **Exit 0 with `dual_ok: true`** → both engines available. Proceed silently.
- **Exit 0 with `dual_ok: false`** (exactly one key present) → the pipeline runs, but EVERY artifact and report will carry **"single-engine UNVERIFIED"**. Warn the user BEFORE transcribing and offer (via `AskUserQuestion`) to add the missing key. If they accept, run `setup` (below) and point them at the missing engine's signup page. If they decline, proceed single-engine — never silently.
- **Exit 2** → `ffmpeg`/`ffprobe` missing. Give the user the install command printed on stderr (`brew install ffmpeg` on macOS) and stop until it's installed.
- **Exit 3** → no API keys at all. Run the guided setup, which scaffolds the key file and prints where to get each key:

  ```bash
  python3 "${SKILL_DIR}/scripts/interview.py" setup
  ```

  **The user must supply their own keys — Gravitas does not bundle or share them.** Groq (`whisper-large-v3`) has a free tier at console.groq.com/keys; OpenAI (`whisper-1`) is paid at platform.openai.com/api-keys (~$0.04 per interview-hour). Offer via `AskUserQuestion` to open both signup pages in the browser — if they accept, run `setup --open`. Then have them paste each key into `~/.config/watch/.env`, re-run `preflight`, and only proceed once at least one key is present (both, for the dual-engine claim). Without any key the pipeline cannot run — stop.

Keys are read from the environment first, then `~/.config/watch/.env`, then `./.env`. On the very first `/interview` of a session, if `preflight` exits 3 (or `dual_ok` is false), run `setup` before anything else.

## Step 1 — Resolve input

Separate the media source from any notes the user attached (`/interview ~/beis/p017.mp4 second session, same participant` → source = the file, notes = context to keep in mind while coding).

**Always pass the media file's ABSOLUTE path to every subcommand** — resolve it once here and reuse it verbatim through Steps 2–8. Relative paths make the printed frame paths relative and Step 7's `Read` calls cwd-dependent. Fix the `--codebook` path here too (see Codebook selection) and reuse it verbatim at Steps 5, 6, and 8 — a study runs one codebook across its whole corpus.

- **Single file** → proceed to Step 2.
- **Folder** → run discovery first:

  ```bash
  python3 "${SKILL_DIR}/scripts/interview.py" discover "<folder>"
  ```

  It prints the media list and a `duplicate_stems` map. Same-stem files (e.g. `p017.mp4` and `p017.wav`) share an output directory and would overwrite each other — when `duplicate_stems` is non-empty, ask the user which file to process per stem (or process only one per stem) before starting. Then run every chosen file **sequentially, in discover's printed order,** through Steps 2–9. If a file hard-fails (both engines fail, unreadable media), continue the batch and record the failure; `corpus-summary` only counts completed sidecars, so your final report MUST name every failed file explicitly — a failed interview must never silently vanish from the corpus count. Batch mode REQUIRES the default output locations (no `--out-dir`): the corpus summary only finds sidecars at `<folder>/*_interview/sidecar.json`. After the last interview:

  ```bash
  python3 "${SKILL_DIR}/scripts/interview.py" corpus-summary "<folder>"
  ```

  It writes `<folder>/corpus_summary.json` and prints the same object. What it reports:

  - `interviews` and `per_interview[]` — one row per completed sidecar: `media`, `flags`, `episodes`, `codebook`, `persona`, `claim`.
  - `codebooks` (name → interview count), `mixed_constructs` (bool), and `warnings` — a persisted array carrying the same text printed to stderr, so a consumer opening the file months later is told what the terminal said.
  - `by_codebook` — `flags_by_marker`, `flags_by_affect`, and `episode_outcomes` **disaggregated per codebook**.
  - Flat rollups: `flags_by_marker`, `flags_by_affect` (plus the back-compat alias `flags_by_emotion`), `episode_outcomes`, `confrontations_with_outcome`, `marker_by_outcome` (keys `"marker|outcome"`), and `personas`.

  **The mixed-vocabulary caveat, and state it plainly in any report you write:** marker vocabularies are codebook-specific. A folder whose sidecars span more than one codebook sets `mixed_constructs: true` and the flat `flags_by_marker` / `marker_by_outcome` tables then **sum incompatible constructs** — they are a retained rollup, not one distribution. Read `by_codebook` (or `per_interview[].codebook`) instead, and never quote a flat marker table for a mixed corpus. The same warning fires when some sidecars record no codebook provenance at all (they resolve to `"unknown"`): their markers cannot be confirmed to share the known codebook's vocabulary. Note also that `episode_outcomes` and `marker_by_outcome` count **confrontation episodes carrying an arc outcome only** — `confrontations_with_outcome` is their shared denominator; flags in non-confrontation episodes still reach `flags_by_marker`.
- **URL** → allowed only for non-sensitive material (public talks, published oral histories — not confidential participant recordings; those must stay local). Download INTO the directory where the artifacts should live (ask the user if unclear — the interview dir is created next to the media file): `yt-dlp -o "<dir>/%(title)s.%(ext)s" "<url>"`, then treat it as a file. If `yt-dlp` is not installed: `brew install yt-dlp` (macOS) / `pipx install yt-dlp` (Linux).
- **Audio-only file** (`.m4a`, `.wav`, `.mp3`, `.aac`, `.flac`) → same pipeline; the frame stage skips itself automatically and the sidecar records that no visual evidence was available.

All artifacts land next to the media: `<media_dir>/<stem>_interview/{transcript.docx, sidecar.json, frames/, work/}`.

If `<stem>_interview/` already exists, do NOT re-run transcription by default — answer from the existing artifacts, or confirm with the user first: re-running transcribe replaces the prior groq/openai/diff record (the audit trail's engine readings) and re-spends API money. Downstream stages (finalize onward) can be re-run freely from the existing work files.

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

`--out-dir DIR` overrides the default output location for a single interview (never use it in batch mode). If you use it, pass the SAME `--out-dir` to transcribe, frames, AND render — each recomputes the base directory from the media path.

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

By default each unit is one transcript segment (sentence-scale) — rapid dyadic exchange defeats silence-gap splitting, so labeling happens on small units and consecutive same-label units are merged into readable turns in the .docx after concordance (the sidecar keeps the unit-level labels). Pass `--unit gap` only for recordings with clear silence between speakers. Expect one unit per sentence: a 60-minute interview yields several hundred units; the panel must label every one.

## Step 4 — Diarization panel (judgment job 2)

Dispatch THREE independent subagents via the Agent tool, **all in one message** so they run in parallel with isolated contexts — that isolation is what makes their agreement a real reliability measure. Each gets this prompt with the full numbered turn list from finalize appended:

> You are analyst {N} of an independent diarization panel. Below is a numbered, timestamped transcript of a two-party research interview. Label EVERY turn: INTERVIEWER (asks, probes, manages the protocol), INTERVIEWEE (narrates, answers), or OTHER (third voice, interruption, unattributable crosstalk). Judge from discourse role, not word count. Return ONLY a JSON object: {"t0001": "INTERVIEWER", ...} — every turn id, no commentary.

The only valid labels are `INTERVIEWER`, `INTERVIEWEE`, and `OTHER` — any other string is discarded from the valid-vote count and recorded in the turn's `invalid` field; sloppy labels erode the audit record and can force `UNCLEAR` when fewer than 2 valid votes remain. Write each agent's output **verbatim** to `WORK_DIR/panel_1.json`, `panel_2.json`, `panel_3.json` (do not fix, normalize, or fill in their answers — a malformed vote is data too). Each `panel_N.json` must itself be a parseable JSON object: if an analyst wraps the object in prose or code fences, save the JSON OBJECT it returned (its labels verbatim — never your corrections to them); if an analyst returns nothing usable, re-dispatch that one analyst once. If only 2 of 3 panels are usable, proceed — concordance accepts ≥2 — and note the lost analyst in your report. Then:

```bash
python3 "${SKILL_DIR}/scripts/interview.py" concordance --work WORK_DIR
```

It needs at least 2 panel files, prints `PANELS` and `LABELS` counts, and one `LOW:` line for every turn that is `UNCLEAR` or has concordance below 1.0. **Do NOT relabel low-concordance turns** — low concordance is a finding, not a defect; the researcher needs to see where the panel split. The resulting `WORK_DIR/diarized.json` carries `label`, `concordance`, `votes`, and `invalid` on every turn.

## Step 5 — Episode segmentation (judgment job 3)

**Optional for a plain single-interview recording under the default codebook** — one dyad, one continuous interaction, nothing to segment; skip straight to Step 6. Run this step whenever the recording holds **more than one interaction**. A pilot video held eight separate confrontations with eight different people; under plain INTERVIEWER/INTERVIEWEE diarization all eight targets fused into a single pseudo-person, and every per-target claim was silently wrong. Episodes are what keep them apart.

**A single-confrontation video under the moral-identity codebook may also skip it — but don't.** Nothing forces the episode layer: validate-flags and render both succeed without `episodes.json`. What you lose is the record. That sidecar carries no `episodes` key, its flags carry no `episode_id`, and the interview contributes `{}` to the corpus summary's `episode_outcomes` and `marker_by_outcome` — the arc and the outcome, which are the study's per-episode unit of analysis, simply are not written down anywhere. Author one episode covering the whole video and give it an `arc`.

Read `WORK_DIR/diarized.json` and write `WORK_DIR/episodes.json` as a **top-level array** (not `{"episodes": [...]}`), in time order:

```json
[
  {"id": "e01", "type": "confrontation", "t_start": 0.0, "t_end": 58.4,
   "target_descriptor": "woman in garage SUV", "target_speech": true,
   "arc": {"phases": ["threat", "defense", "escalation", "exit"],
           "outcome": "refuses", "turning_point": null}},
  {"id": "e02", "type": "confrontation", "t_start": 58.4, "t_end": 101.2,
   "target_descriptor": "man in red truck", "target_speech": true,
   "arc": {"phases": ["threat", "defense", "repair", "exit"],
           "outcome": "complies", "turning_point": "t0012"}},
  {"id": "e03", "type": "to-camera", "t_start": 107.2, "t_end": 128.6}
]
```

Those timestamps are not round numbers on purpose — see the snapping rule below. In the transcript behind this example, `58.4` is the start of `t0011`, `101.2` is the end of `t0015`, and `107.2` is the start of `t0016`. `e02` therefore closes on its own last turn and `e03` opens on its first, leaving `101.2`–`107.2` uncovered — the legal gap discussed below, silent B-roll between the second confrontation and the wrap-up.

- **Required on every episode:** `id` (`e01`, `e02`, … — unique), `type`, `t_start`, `t_end` (seconds, as numbers — a `"0:00"` video-clock string is rejected).
- `type` is one of `confrontation`, `commendation`, `bystander`, `to-camera`.
- **Confrontations additionally require `target_descriptor`** — short and concrete ("woman in garage SUV", "Scott") — **and `target_speech`**, which must be the JSON boolean `true`/`false`.
- `arc` is optional and belongs on confrontations: `phases` a list drawn from `threat`, `defense`, `escalation`, `softening`, `flip`, `repair`, `exit`; `outcome` one of `complies`, `refuses`, `escalates`, `partial`, `n/a`; `turning_point` a **unit-level turn id as printed by finalize and stored in the sidecar's `turns[]`** — `t0012`, never a merged display id (`m0012`), those exist only inside validate and render and are not in the research record — or the literal `"off-camera"` when the arc turned before the camera ran, or `null`. A codebook declaring `arc_schema` supplies these vocabularies; the ones above are the fallback.
- `note` is optional and free-form — use it to record a low-confidence boundary.

Segmentation rules:

- **Non-overlapping and in time order.** Episodes may not overlap and may not run backwards. They need not be contiguous — see the gap rule.
- **Snap every boundary to a turn boundary**, and take the numbers from `diarized.json`, not from finalize's printed list — that list is rounded to whole seconds (`t0015 [01:30-01:41]`) while the real boundary is `101.2`. Never estimate from the video clock and never round: a boundary landing mid-turn is the single most common way to fail this stage. An episode's **`t_start` snaps to the start of its first turn**; its **`t_end` closes on the end of its last turn** (or anywhere in the silence before the next episode opens).
- **Containment is half-open `[t_start, t_end)`** — a turn starting exactly on a shared boundary belongs to the **later** episode. The final episode is end-inclusive so the recording's last turn is never orphaned. That is the rule that makes snapping work: at a shared boundary, set it to the first turn of the NEW episode, as `e02`'s `58.4` does above.
- **Gaps between episodes are legal** — silent B-roll holds no turns and needs no episode, which is why `e02` ends at `101.2` and `e03` only opens at `107.2`. What is enforced is coverage of the turns: **every turn's start must fall inside exactly one episode.** A turn that does start inside that gap is reported as an orphan:

  ```
  INVALID EPISODES:
    1 turn(s) fall in no episode: t9999 (start 105.0)
  ```

- **A turn may not straddle another episode's start.** Guess a round `55.0` for the `e01`/`e02` boundary instead of snapping to `58.4`, and `t0010` — which runs from `50.1` to `56.26` — is cut in half:

  ```
  INVALID EPISODES:
    1 turn(s) straddle an episode boundary: t0010 (e01 → e02)
  ```

  That is a mis-drawn boundary — almost always an un-snapped one — and authoring time is the only point at which it can still be fixed. Move it to the turn boundary the transcript actually supports.
- **The confronter's to-camera asides INSIDE an ongoing confrontation belong to that confrontation.** A `to-camera` episode is only a stretch with **no active target** (the wrap-up monologue). Narration delivered over a live target stays in that target's episode — the coding pass picks it up through `speaker_role`, not through a separate episode.
- **`target_speech: false`** (a target who only revs the engine) means code outcome and confronter performance only, and report "no defense repertoire codeable" for that episode. **Never invent target speech.**
- Ambiguous boundary (a hard cut mid-interaction) → set it at the first turn addressing the new target, and record the uncertainty in the episode's `note`.
- Two targets genuinely interleaving → split at the finest boundary the transcript supports; if inseparable, one episode with a `note` — never silently merged into a third pseudo-target.

Then validate:

```bash
python3 "${SKILL_DIR}/scripts/interview.py" validate-episodes --work WORK_DIR \
  --codebook "${SKILL_DIR}/scripts/codebook_moral_identity.json"
```

`--codebook` is optional; omit it to validate against the shipped codebook's fallback schema. Clean, it prints one line per episode **with the turn count each captured** — check those counts against your own reading before moving on:

```
EPISODES: 3
  e01 confrontation [00:00-00:58] turns=10 target="woman in garage SUV"
  e02 confrontation [00:58-01:41] turns=5 target="man in red truck"
  e03 to-camera [01:47-02:08] turns=2
```

(The printed time range is `format_hms`-rounded to whole seconds; `episodes.json` keeps your exact values.)

On errors it prints `INVALID EPISODES:` and exits 1 — fix `episodes.json` per each printed line and re-run **until the table prints**. Repeated identical problems are summarized as one capped line (`+N more`), so fix the cause, not the symptom count.

A clean run also **stamps `episode_id` onto every turn** in `diarized.json`. That stamp is what Step 6 reconciles against, so **any re-drawing of `episodes.json` means re-running this stage** before validate-flags.

## Step 6 — Coding pass (judgment job 4)

Read the codebook you fixed in Step 1 **fresh each run** (never from memory — codebooks are versioned and may have changed) and `WORK_DIR/diarized.json`. For each moment matching one or more of that codebook's markers, build a flag exactly per its `flag_schema`:

- `id`: `g0001`, `g0002`, … — sequential and **unique** (duplicates are rejected by validation).
- `marker_types`: non-empty list of marker ids **from this codebook**. When an utterance satisfies more than one definition, code all that apply rather than forcing a single choice.
- `quote`: **verbatim substring of the speaker's speech** — no paraphrase. May span consecutive sentences by the same speaker; must never cross a speaker change.
- `t_start`/`t_end`: seconds, within the media duration.
- `salience`: integer 1–5 per the codebook's scale. Reserve 5 for genuinely defining moments.
- **Affect — the codebook names both the field and the vocabulary.** Under the shipped codebook the field is `emotion`, required iff `marker_types` includes `emotional_display`, drawn from its `emotions` list. Under a codebook declaring `affect_field` (the moral-identity codebook declares `affect`), that field is the only one checked and `affect_vocabulary` is the only vocabulary — a stale `emotions` key is ignored. It is required by **every marker carrying `requires_affect: true`**, which in the moral-identity codebook is 14 of its 16 markers — the only exceptions are `audience_address` and `camera_awareness`. `neutral` is the explicit no-signal value, not an omission.
- `speaker_role`: see coding scope below.
- `attribution_uncertain`: see the attribution gate below.
- `note`: optional, brief.
- Do **not** write `episode_id` yourself — validate-flags stamps it from `episodes.json`.

**Coding scope.** A codebook's `coding_scope` declares which speaker roles get coded. The shipped codebook declares none, and the rule is this contract's: code **ONLY turns labeled INTERVIEWEE** (nothing machine-checks that under the default codebook — the discipline is yours). The moral-identity codebook declares `["INTERVIEWEE", "INTERVIEWER"]`, so the confronter's speech is in scope too and **every flag must carry `speaker_role`** — the canonical label (`INTERVIEWER` / `INTERVIEWEE`) of the turn the quote came from. Validation then requires the quote to be found in a turn actually bearing that role; a flag omitting `speaker_role` is itself a finding. `OTHER` and `UNCLEAR` turns are never coded under any codebook — the speaker is unattributable.

**The attribution gate.** When a codebook sets `enforce_attribution_gate` (the moral-identity codebook does), any flag whose quoted turn has `concordance < 1.0` or label `UNCLEAR` must carry `"attribution_uncertain": true` — the **JSON boolean `true`, not the string `"true"`**, which is rejected exactly like a missing key:

```
g0007: quoted turn m0008 has concordance 0.6667 — flag must set attribution_uncertain: true
```

Do not answer that by relabeling the turn or dropping the flag. The panel split is a finding, and this field is how the record carries it forward honestly. Step 4's `LOW:` lines are your list of the turns this applies to.

Expect roughly 5–20 flags for a 60-minute interview. **Zero flags is a valid outcome** for a flat interview — do not invent gravity to have something to show. Write the flags to `WORK_DIR/flags.json` as a **top-level array** (not `{"flags": [...]}`):

```json
[
  {"id": "g0001", "marker_types": ["quoted_speech"], "quote": "and he said to me, you're done", "t_start": 754.2, "t_end": 761.0, "salience": 3}
]
```

Under the moral-identity codebook a flag carries the two extra fields:

```json
[
  {"id": "g0002", "marker_types": ["displacement_of_responsibility"], "quote": "That is the store's job, they get paid to do that.", "t_start": 15.1, "t_end": 19.8, "salience": 4, "speaker_role": "INTERVIEWEE", "affect": "frustration"},
  {"id": "g0007", "marker_types": ["diffusion_of_responsibility"], "quote": "Everyone does it, people leave carts all the time.", "t_start": 40.2, "t_end": 49.6, "salience": 4, "speaker_role": "INTERVIEWEE", "affect": "frustration", "attribution_uncertain": true}
]
```

Then validate:

```bash
python3 "${SKILL_DIR}/scripts/interview.py" validate-flags --work WORK_DIR [--duration <seconds>] \
  --codebook "${SKILL_DIR}/scripts/codebook_moral_identity.json"
```

`--codebook` must be the same one you coded against — pointing it at the other codebook turns every marker id into `unknown marker '...'`. `--duration` is optional; when omitted it is auto-derived from the final transcript's last segment. Pass it explicitly for exactness: get `<seconds>` from `ffprobe -v error -show_entries format=duration -of csv=p=0 "<media>"`. Quotes are checked verbatim against the diarized transcript (merged same-speaker view) — a paraphrase fails validation. A quote may span consecutive sentences by the SAME speaker, but must never cross a speaker change. On errors, fix `flags.json` per each printed line and re-run until it prints the OK line, which names the codebook it actually used — read that filename and confirm it is the one you meant:

```
OK: 9 flags valid against codebook 1.0.0 (codebook_moral_identity.json)
```

Validation gates the frame stage — never proceed past a failing validate.

**When `WORK_DIR/episodes.json` exists**, this stage also reconciles the two layers and stamps `episode_id` onto every flag. Three refusals to know, all exit 1:

- `N display turn(s) out of sync with episodes.json — re-run validate-episodes` — `episodes.json` was re-drawn after Step 5 stamped the turns (or Step 5 never ran). Re-run `validate-episodes`, then this stage. Do not hand-edit the stamps.
- `episodes.json is present but there is no labeled turn layer to reconcile it against` — run concordance, then validate-episodes, first. **You only see that sentence under the default codebook.** Under a codebook declaring `coding_scope`/`enforce_attribution_gate` — including the moral-identity one in the command above — the same stage order raises first, as a traceback ending `ValueError: turns missing label/concordance (run concordance first): t0001, …`. That traceback is the one case where the input file is fine and the **stage order** is wrong; the remedy is the same concordance → validate-episodes → validate-flags.
- The flag's own placement — `g0010: t_start 103.0 outside every episode` (its `t_start` fell in a legal gap, where turns may not start but flags evidently did) or `g0010: straddles episodes e01 → e02 (t_start 50.1, t_end 64.48); filed under e01` (a boundary runs through the flag; it is filed under its `t_start`'s episode anyway, and the disagreement is reported rather than resolved silently). Fix the timestamps, or the boundary, and re-run both stages.

Those three are checked in order, and the first two are checked **before** flag placement: a run whose turn layer is out of sync reports drift and stops, so fix drift first and the placement errors — if any — surface on the next run.

## Step 7 — Frame evidence (video only)

```bash
python3 "${SKILL_DIR}/scripts/interview.py" frames "<media>"
```

For audio-only media this prints a skip note and exits 0 — go straight to Step 8. For video, it extracts a ~5-frame burst around each flag's midpoint into `frames/<flag_id>/`, prints the path of every frame (absolute, given the absolute-media rule in Step 1), and writes the relative paths (plus a `frames_missing` count for any frames that could not be extracted) back into `flags.json`.

`Read` every printed frame (batch per flag when there are many — see Token efficiency), using parallel tool calls so you see each flag's burst together. Then, for each flag, set `"visual_evidence"` in `WORK_DIR/flags.json` to one of:

- `"corroborates — <note>"` — visible affect/behavior matches the flag (e.g. tearing up during a grief-marked passage).
- `"contradicts — <note>"` — the visuals cut against the flag (e.g. flat affect during claimed emotional display).
- `"neutral — <note>"` — frames show nothing diagnostic either way.

**NEVER delete a flag because frames contradict it.** Record the contradiction — the sidecar keeps both signals, and the disagreement between text and video is itself research data.

## Step 8 — Render

```bash
python3 "${SKILL_DIR}/scripts/interview.py" render "<media>" \
  --codebook "${SKILL_DIR}/scripts/codebook_moral_identity.json" \
  --persona "Agent Greg Gorey" \
  --interviewer "Agent Greg Gorey" --interviewee "Target"
```

(`--codebook`, `--persona`, and the four name flags are all optional; the bare `render "<media>"` is the default-codebook form.)

Prints `DOCX:` and `SIDECAR:` paths and `CLAIM:` — the accuracy claim, exactly one of:

- `dual-engine verified with logged adjudication`
- `dual-engine verified with logged adjudication; INCOMPLETE — transcription gaps recorded`
- `single-engine UNVERIFIED`

The .docx is the speaker-labeled transcript with coded flags anchored as comments. The sidecar is the full machine-readable record, **schema 1.1**: `interview` (media, duration, processed_at, and `persona` when given), `engines`, `accuracy_claim`, top-level `codebook_version` and `codebook_file`, `degradation`, `partial_failures`, `segments`, `turns` (with concordance, votes, and `episode_id` when the episode layer ran), `adjudications`, `flags` (with visual evidence and `episode_id`), plus `episodes` (the validated list, arcs included) when `episodes.json` exists and `speaker_names` when names were passed. `codebook_file` is always recorded, because which codebook produced the record is a fact about the record; both shipped codebooks are independently at version `1.0.0`, so the **filename**, not the version, is what carries identity.

**The .docx is not the complete record — the sidecar is.** A Word comment carries the marker list, salience, time range, note, visual evidence and frame count only, under a hardcoded `GRAVITY [...]` heading:

```
GRAVITY [displacement_of_responsibility] | salience 4/5 | t=00:15-00:19 | frames: 5
```

A codebook-declared affect field (`affect`), `speaker_role`, `episode_id`, and `attribution_uncertain` **do not appear there** — they are in the sidecar and nowhere else. Say so if you hand the .docx to a human coder for a moral-identity study, and never let a claim about affect, speaker, episode, or attribution be sourced from the .docx alone.

**Codebook (`--codebook PATH`).** Pass the SAME codebook you validated against. render loads it independently, and nothing cross-checks the two stages: omitting it here exits 0 and writes `codebook_file: codebook.json` onto a record coded against a different codebook — a corrupt research record with no error message. If you catch it after the fact, re-run render with the right `--codebook`; render is pure assembly and safe to repeat.

**Persona (`--persona NAME`).** The confronter's per-video character — "Agent Greg Gorey", "RoboNarc". It is recorded as `interview.persona` in the sidecar and rolls up into the corpus summary's `personas` list and each `per_interview[].persona`. **A persona is metadata — never a role and never a label.** `turns[].label` stays canonical, `coding_scope` still speaks in `INTERVIEWER`/`INTERVIEWEE`, and persona *work* in the speech is coded through the `audience_address` marker, not through this flag. Omit the flag entirely when a video has no persona: passing an empty string is rejected (exit 2) rather than recorded as a persona that is the empty string. If you also want the persona shown in the .docx headers, that is the separate `--interviewer` display name below.

**Optional speaker names.** By default the .docx headers read `INTERVIEWER:` / `INTERVIEWEE:` (and `OTHER:` / `UNCLEAR:`). Pass display names to relabel them — useful when the dyad has known participants or the recording isn't a literal interview:

```bash
python3 "${SKILL_DIR}/scripts/interview.py" render "<media>" \
  --interviewer "Interviewer" --interviewee "Participant"
```

`--other` and `--unclear` rename those labels too; any flag you omit keeps its canonical role label. This is a **display layer only** — the sidecar's `turns[].label` stays role-based (the research record), and the chosen names are recorded under a `speaker_names` key so the artifact is self-describing. Names are purely a render concern; re-run `render` with different names any time without re-transcribing. Note that a single INTERVIEWEE label covers whoever is in the interviewee role — in a multi-party recording (e.g. one host confronting several people) every non-host turn shares one name, so names fit true dyads best.

## Step 9 — Report to the user

Per interview, report:

- **The accuracy claim, verbatim from render output.** Never soften it, never upgrade it.
- The codebook you coded against, by filename and version (the OK line from validate-flags).
- Engine disagreement count and how many adjudications were nontrivial (synthesized corrections, deletions).
- Diarization label counts, plus any `UNCLEAR` or low-concordance turns with timestamps — and, when the attribution gate is on, how many flags carry `attribution_uncertain`.
- When the episode layer ran: the episode count by type, each confrontation's target descriptor and arc outcome, and any episode whose `target_speech` is false (report "no defense repertoire codeable" for it rather than a thin profile).
- Flag count by marker type; the top-salience moments with timestamps and a one-line description each.
- Artifact paths (`transcript.docx`, `sidecar.json`).

Batch mode: one line per interview (media, claim, codebook, flag count, episode count), then the corpus summary from `corpus-summary`. If it reported `mixed_constructs: true`, **say so and report from `by_codebook`** — quoting the flat marker table for a mixed corpus sums incompatible constructs. Reproduce any `warnings` entry verbatim.

## Retention

**NEVER delete the work directory or the frames directory.** They are the audit trail: every engine reading, every adjudication decision with rationale, every panel vote, and every evidence frame must remain inspectable after the fact. One caveat: re-running the frames stage regenerates each flag's frame images in place — the previous `cue_*.jpg` for that flag are replaced, so a frames re-run overwrites that flag's prior visual-evidence images. A transcribe re-run likewise replaces the prior groq/openai/diff record — which is why Step 1's re-run policy requires user confirmation first. Evidence retention is this skill's compensating control for being fully automatic — a human reviewer can re-derive or challenge any judgment from what's on disk. This is the opposite of `/watch`'s cleanup step: these artifacts persist next to the media by design.

## Failure modes

- **One engine keyless or failed** → the pipeline continues single-engine (the diff self-compares, so there is nothing to adjudicate). The degradation is recorded in the sidecar and the claim becomes `single-engine UNVERIFIED`. Your report MUST carry that phrase.
- **Some transcription chunks failed** → recorded in the sidecar's `partial_failures`. On a dual-engine run the claim gains `INCOMPLETE — transcription gaps recorded`; on a single-engine run it does NOT — the claim stays the plain `single-engine UNVERIFIED`, which swallows the gap. Report the gaps from `partial_failures` either way; do not infer them from the claim.
- **finalize raises on adjudications** → your `adjudications.json` has missing or unknown ids. Fix the file to cover exactly the printed disagreement ids; do not edit `diff.json`.
- **A panel file won't parse** → concordance dies on malformed JSON. Save the JSON object from that analyst's reply (labels verbatim); if nothing usable, re-dispatch that one analyst once, or proceed with the 2 usable panels and note the lost analyst in your report.
- **A batch file hard-fails** (both engines fail, unreadable media) → continue the batch and record the failure; name every failed file explicitly in your final report — `corpus-summary` only counts completed sidecars.
- **validate-flags rejects** → fix `flags.json` per the printed errors and re-run. Never bypass validation.
- **validate-episodes rejects** → fix `episodes.json` per the printed errors and re-run until the episode table prints. Repeated problems are capped into one summary line — fix the cause (usually one mistyped timestamp), not each symptom.
- **A stage exits 2** → broken input, not a finding: a missing/malformed `episodes.json` or a bad `--codebook` path. Nothing was validated. See Exit codes.
- **`validate-flags` reports episode drift** → `episodes.json` changed after the turns were stamped, or `validate-episodes` never ran. Re-run `validate-episodes`, then `validate-flags`. Never hand-edit `episode_id` in `diarized.json` or `flags.json`.
- **A run used mismatched codebooks across stages** → the sidecar's `codebook_file` will disagree with the codebook you coded against, and nothing raises. Re-run `render` with the correct `--codebook`; the docx and sidecar are rebuilt from the work files.
- **Frames missing for a flag** → `frames_missing` is recorded on the flag; assess visual evidence from the frames that did extract, or mark it `neutral` if none did.
- **Never claim the transcript is "error-free"** — no ASR pipeline is. The honest claim is whatever render prints, and that is what you report.

## Token efficiency

This skill burns tokens primarily on frame reading. Order of magnitude: a 20-flag video interview yields up to ~100 frames, roughly 200 image tokens each at 512px; the transcript stages are cheap by comparison.

- **More than ~10 flags** → do not read every frame in one message. Read frames in per-flag batches, ordered by salience (highest first), and record each flag's `visual_evidence` before moving to the next batch.
- **Batch mode accumulates context** across interviews, but every stage's inputs persist on disk, so a FRESH session can resume any interview from its work dir: finalize needs `work/diff.json` + `work/adjudications.json`; concordance needs `work/turns.json` + `work/panel_*.json`; validate-episodes needs `work/diarized.json` + `work/episodes.json`; **validate-flags needs `work/flags.json` AND `work/diarized.json`** (plus `work/final_transcript.json` if you want the duration auto-derived, and `work/episodes.json` when the episode layer ran); frames needs `work/flags.json`; render needs `work/diarized.json`, `work/flags.json`, `work/final_transcript.json`, `work/audit_log.json`, and `work/diff.json` (plus `work/episodes.json` when the episode layer ran). Any resumed stage that takes `--codebook` needs the same one the run started with — the sidecar of a completed interview records it as `codebook_file`.

  **`diarized.json` is not optional at validate-flags, and its absence fails OPEN.** The verbatim-quote check exists only when that file is there: resume with `flags.json` alone under the default codebook and a **fabricated quote earns the `OK:` line and exit 0** — the same OK line Step 9 tells you to report as provenance. Under a codebook declaring `coding_scope`/`enforce_attribution_gate` the same resume raises a `ValueError` traceback instead of validating. Never run validate-flags against a work dir missing `diarized.json`; if you are unsure what a resumed work dir holds, `ls` it before trusting an OK.
- **If context runs low mid-batch** → finish the interview in progress through render, report which files remain unprocessed, and tell the user to re-invoke `/interview` on the remainder.

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
- Does not delete the work directory, `transcript.docx`, or `sidecar.json` — retention is a hard rule (see Retention). Two replace-in-place exceptions, both covered in Retention: a frames re-run regenerates a flag's `cue_*.jpg` images, and a user-confirmed transcribe re-run replaces the prior engine/diff record

**Bundled scripts:** `scripts/interview.py` (CLI entry point; all subcommands), `scripts/dual_transcribe.py` (dual-engine orchestration, transcript diff, adjudication application), `scripts/analyze.py` (turn building, panel concordance, flag validation, frame-burst timing), `scripts/render.py` (.docx with anchored comments + JSON sidecar), `scripts/stt.py` (Groq/OpenAI Whisper clients), `scripts/framegrab.py` (ffmpeg frame extraction), `scripts/codebook.json` (narrative-gravity codebook v1.0.0, the default), `scripts/codebook_moral_identity.json` (moral-identity-under-confrontation codebook v1.0.0, selected with `--codebook`). All pure stdlib — no third-party Python packages.

Review scripts before first use to verify behavior.
