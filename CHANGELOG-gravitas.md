# Changelog — Gravitas (`/interview`)

All notable changes to the **Gravitas** product — the `skills/interview/` skill —
are documented here. The upstream `/watch` skill keeps its own independent
version line in [`CHANGELOG.md`](CHANGELOG.md). The two lines advance
separately, so a number in one says nothing about the other: both are at
`0.2.0` for entirely unrelated reasons, and a `0.3.0` here implies nothing about
`/watch`.

## [0.3.0] — unreleased

Moral identity under public confrontation: a second codebook, an episode layer
for recordings that confront more than one person, and the provenance needed to
keep a coded artifact honest about which construct produced it.

### Added
- **Selectable codebook.** `--codebook PATH` on `validate-episodes`,
  `validate-flags`, and `render`. The shipped narrative-gravity `codebook.json`
  stays the default, so every existing invocation is unchanged.
- **`codebook_moral_identity.json` v1.0.0** — 16 markers spanning Bandura's
  moral-disengagement mechanisms, identity talk (threat / defense / repair /
  bestowal), and performance-for-the-recording, each with boundary rules against
  its nearest neighbour, plus a 12-term affect vocabulary with definitions.
- **Codebook-driven flag validation.** A codebook may now declare
  `affect_field` and `affect_vocabulary` (replacing the narrative `emotion` /
  `emotions` pair), `markers[].requires_affect`, `coding_scope` (which speaker
  roles may be coded, checked against the turn the quote actually lands in), and
  `enforce_attribution_gate` (a flag quoting a turn the panel could not
  attribute cleanly must carry `attribution_uncertain: true`).
- **Episode layer.** A hand-authored `episodes.json` is validated by the new
  `validate-episodes` stage against the codebook's `episode_schema` /
  `arc_schema`, then stamped onto every diarized unit; `validate-flags` inherits
  each flag's episode from that layer. Episodes are a hard barrier in turn
  merging — two units in different episodes never fuse, because in a
  multi-target recording they are two different people.
- **Turn/flag episode drift detection.** Editing `episodes.json` and re-running
  only `validate-flags` is caught and refused, rather than filing one target's
  exchange under another.
- **`--persona NAME`** on `render` — the confronter's per-video character,
  recorded in the sidecar. An empty value is refused (exit 2) rather than
  recorded as an empty-string persona.
- **Sidecar schema 1.1** — adds `codebook_file` and top-level
  `codebook_version` (both codebooks are independently at 1.0.0, so the file
  name is what carries identity), plus `episodes` and `interview.persona` when
  present.
- **Episode-aware corpus aggregation.** `corpus-summary` counts episodes and
  arc outcomes across a folder of sidecars and warns when the corpus mixes
  constructs — sidecars produced under different codebooks are not one dataset.
  `flags_by_emotion` is kept as a back-compat alias of `flags_by_affect`.

### Fixed
- **`validate-flags` failed open on the verbatim-quote check.** The check ran
  only when `work/diarized.json` happened to exist; without it, a fabricated
  quote earned the same `OK:` line SKILL.md designates as quote provenance. The
  stage now refuses (exit 1) when any flag carries a quote and no turn layer is
  available to check it against, naming the missing file and the consequence —
  matching `render`, which already failed closed on exactly this condition. A
  codebook whose `coding_scope` / `enforce_attribution_gate` demands turns now
  reports that here too, instead of a bare traceback. Both print under a
  distinct **`CANNOT VALIDATE:`** header rather than `INVALID FLAGS:`: the
  remedy is to run an earlier stage, not to re-examine your coding.
- **`render` silently recorded the wrong codebook.** Omitting `--codebook` on a
  moral-identity run exited 0 and wrote `codebook_file: "codebook.json"` into a
  sidecar full of moral-identity markers. A successful `validate-flags` now
  records the codebook it accepted the flags against in
  `work/codebook_ref.json`, and `render` refuses (exit 1) when the codebook it
  resolves differs in name or version, naming both and the record's path. Work
  dirs with no such record still render, so runs predating this stay valid; a
  record that is present but unusable (missing or blank `codebook_file` /
  `codebook_version`) exits 2 naming the record, rather than refusing a
  legitimate render with an instruction that cannot be followed.
- **The `.docx` comment dropped codebook-declared fields.** It read `emotion`
  only, so a codebook declaring `affect_field: "affect"` lost its affect
  entirely, along with `speaker_role`, `episode_id`, and
  `attribution_uncertain`. All four now appear when present. The `.docx` is the
  human coding surface in document-based review, so a complete sidecar was not
  enough. Narrative-gravity comments are byte-unchanged: the affect segment
  keeps the label of the field the flag actually carries.

## [0.2.0] — 2026-07-19

### Added
- **Configurable speaker display names** — `--interviewer`, `--interviewee`,
  `--other`, and `--unclear` on `render` set the names in the `.docx` speaker
  headers, and are recorded in the sidecar as `speaker_names`. Canonical role
  labels stay on `turns[].label`: the research record is role-based and names
  are a display layer, so partial maps and omitting the flags entirely both
  render the canonical labels.

## [0.1.0] — 2026-07-11

Initial Gravitas release, forked from `claude-video`.

### Added
- `/interview <media-file-or-folder> [notes]` — a staged pipeline run by the
  model per `SKILL.md`: `preflight` → `transcribe` → `finalize` →
  `concordance` → `validate-flags` → `frames` → `render`.
- **Dual-engine transcription with logged adjudication.** Every recording is
  transcribed by both Groq `whisper-large-v3` and OpenAI `whisper-1` and the two
  are diffed; each disagreement is adjudicated and the decision is recorded. One
  key still runs the whole pipeline, but every artifact is marked
  "single-engine UNVERIFIED".
- **Panel diarization.** Independent label passes are scored for concordance
  per unit; units below threshold become `UNCLEAR`. Units are segment-scale and
  same-label neighbours merge only after labeling — gap splitting under-segments
  rapid dyadic exchange.
- **Narrative-gravity codebook v1.0.0** — six discourse markers with a 1–5
  salience scale, validated deterministically: every flag's quote must be a
  verbatim substring of the final transcript.
- **Artifacts:** `transcript.docx` (speaker-labeled, coded moments as anchored
  Word comments, accuracy claim on the page) and `sidecar.json` (the
  machine-readable record). Raw OOXML via `zipfile` — pure stdlib.
- **Frame evidence** — a burst of frames per flag, referenced from the sidecar
  by interview-relative path so artifacts stay portable.
- `interview.py setup` — guided Whisper key setup writing an owner-only
  `~/.config/watch/.env`, shared with `/watch`.
- `corpus-summary` — aggregate every sidecar under a folder.
