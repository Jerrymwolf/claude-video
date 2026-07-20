# Moral Identity Study — Cart Narcs Corpus + Gravitas Episode Support

**Date:** 2026-07-19
**Status:** Draft for review
**Owner:** Jeremiah Wolf

## Overview

A dual-purpose project: (1) a real pilot study of **moral identity under public confrontation**, run on 5–8 Cart Narcs videos, whose intended downstream output is an Atlantic/NYT-style narrative feature; (2) a forcing function that proves Gravitas runs **consistently at scale** — multi-video batch, uniform codebook, no hand-patching outside defined judgment steps.

The bridge between the two is the codebook: the research question is operationalized as a versioned codebook; the Gravitas coding pass detects instances of its markers; every flag carries machine-validated verbatim evidence; aggregation across episodes answers the question. The tool changes are additive — the verified pipeline (dual transcription, adjudication, diarization panel, concordance, flag validation) does not change.

## Research questions

**Main RQ:** When a stranger with a camera confronts someone over a trivial norm violation, what happens to their moral identity — how is it threatened, defended, performed, and (sometimes) repaired?

- **RQ1 — Defense repertoire** *(scaffolding)*: Which of Bandura's eight moral-disengagement mechanisms appear in each target's speech — and, as the counter-pole, does **responsibility acceptance** (admission, apology, repair) appear instead or alongside? Nine codes; rare mechanisms stay in the codebook and report as zeros — absence is a finding.
- **RQ2 — Identity talk** *(the heart)*: Explicit self-claims by target *and* confronter, coded as identity **threat**, **defense**, **repair**, or **bestowal** (identity granted by the other — e.g., "that's actually being a real man").
- **RQ3 — Arc**: The ordered trajectory per confrontation episode — does defense harden, soften, or flip, and what immediately precedes the turn? Endpoint outcome ∈ {complies, refuses, escalates, partial} — kept as the arc's endpoint, not its substitute.
- **RQ4 — Performance layer**: Camera- and audience-awareness moments, and the confronter's own moral self-presentation — including the rotating **personas** (Agent Greg Gorey, Agent Sebastian, RoboNarc, …) as identity work in their own right.

**Claim discipline:** With n = 5–8 videos (~20–40 confrontation episodes expected), all RQ1×RQ3 patterns are reported descriptively. No causal or correlational claims. The corpus is edited, creator-selected footage; findings describe confrontations *as broadcast*, not as they occurred. This is stated as a limitation and treated as study material (the editing is itself part of the performance).

## Units and roles

**Hierarchy: Video → Episode → Turn/Flag.** The unit of analysis for RQ1–RQ3 is the **episode**, not the video.

**Roles.** Pipeline-canonical labels are unchanged (`INTERVIEWER` / `INTERVIEWEE` / `OTHER` / `UNCLEAR`). The study maps them at the analysis/display layer: `INTERVIEWER` → **CONFRONTER**, `INTERVIEWEE` → **TARGET**, using the existing `render --interviewer/--interviewee` names feature. Sidecar `turns[].label` stays canonical; every study artifact records the mapping. The confronter's per-video **persona** is metadata (see schema), never a role.

**Episode.** A contiguous time span of the transcript covering one interaction. Fields: `id` (`e01`, `e02`, …), `type`, `t_start`/`t_end`, `target_descriptor` (short, e.g. "woman in garage SUV", "Scott"), `target_speech` (bool).

- `type` ∈ {`confrontation`, `commendation`, `bystander`, `to-camera`}.
- Episodes are **contiguous and non-overlapping**, ordered, and jointly cover every turn (each turn belongs to exactly one episode, assigned by `t_start` containment).
- **Within-episode asides:** the confronter's to-camera narration *inside* an ongoing confrontation belongs to that confrontation episode (RQ4 coding picks it up via `speaker_role`). `to-camera` episodes are only stretches with no active target (e.g., the wrap-up monologue).
- **Target-speech gate:** confrontation episodes with `target_speech: false` (e.g., a driver who only revs his engine) are coded for outcome and confronter behavior (RQ3 endpoint, RQ4) and explicitly report "no defense repertoire codeable" — nothing is invented for silent targets.

## Codebook: `codebook_moral_identity.json` v1.0.0

A new versioned codebook file, sibling to the shipped `codebook.json` (which is untouched). Structure mirrors the existing codebook (construct, markers with indicators, flag schema, salience scale) with these code families:

**1. Defense repertoire (9 codes; TARGET speech).** Bandura's mechanisms + counter-pole, each with observable linguistic indicators:

| Code | Example indicators (from pilot) |
|---|---|
| `moral_justification` | reframing the act as serving a worthy end |
| `euphemistic_labeling` | minimizing language for the act ("just left it right there") |
| `advantageous_comparison` | "what about those fifty carts over there" |
| `displacement_of_responsibility` | "that's the store's job", "they get paid for this" |
| `diffusion_of_responsibility` | "everyone does it" |
| `distortion_of_consequences` | "what damage does that do", "it doesn't matter" |
| `dehumanization` | derogating the confronter as not worth moral regard |
| `attribution_of_blame` | "you're harassing me", condemning the condemner |
| `responsibility_acceptance` | "I screwed up", apology, repair action |

**2. Identity talk (4 codes; TARGET and CONFRONTER speech).** `identity_threat` (the accusation as delivered), `identity_defense` (self-claims deployed under threat — "I'm disabled", "I'm not lying"), `identity_repair` (re-narrating the self after admission), `identity_bestowal` (identity granted by the other — "a real man", "litterbug").

**3. Performance markers (2 codes; any speaker).** `audience_address` (playing to camera/Narcoteers, persona voice), `camera_awareness` (target registers being filmed — "get that camera away", the van joke).

**4. Affect vocabulary** (flag field, required on defense/identity codes where affect is evident; `neutral` allowed): anger, contempt, frustration, anxiety, fear, shame, embarrassment, sadness, amusement, pride, relief, neutral. Affect is coded **from language**; frames corroborate only where the POV camera permits (pilot finding: often it doesn't — `visual_evidence` records this honestly, as now).

**5. Arc (per-episode summary, not a flag).** Each confrontation episode gets an `arc` object in the sidecar: ordered phase list (subset of {threat, defense, escalation, softening, flip, repair, exit}), `turning_point` (turn id + what immediately preceded it, or null), `outcome` ∈ {complies, refuses, escalates, partial, n/a}.

**Coding scope is declared by the codebook** (`coding_scope: ["INTERVIEWEE", "INTERVIEWER"]`), not hardcoded in the skill contract. *(As shipped: the narrative-gravity codebook declares NO `coding_scope`, which leaves the scope check switched off entirely and preserves current behavior exactly. The `["INTERVIEWEE"]` default in `validate_flags` is reached only by a codebook that requires `speaker_role` without declaring a scope; under the shipped codebook the interviewee-only rule is enforced by the SKILL.md contract, not by the validator.)*

## Tool deltas (all additive)

1. **`--codebook PATH`** on the coding-related subcommands (`validate-episodes`, `validate-flags`, `render`): selects the codebook file; default remains the shipped `codebook.json`. *(As shipped: `corpus-summary` deliberately takes NO `--codebook` — aggregation is codebook-agnostic and counts what the sidecars themselves record; an accepted-and-ignored argument would read as a filter. `validate-episodes` takes it instead, for `episode_schema`/`arc_schema`.)* The codebook's `coding_scope` drives which roles the gravity/coding pass covers.
2. **Episode stage** (new, between concordance and coding). Judgment lives in the skill contract: Claude reads `diarized.json` and writes `WORK_DIR/episodes.json`. A new deterministic subcommand `validate-episodes --work WORK` checks: non-overlapping ordered spans, full turn coverage, enum types, `target_descriptor` present on confrontations, and writes `episode_id` onto each turn. Flags gain `episode_id` (assigned by `t_start` containment) at `validate-flags` time.
3. **Flag schema additions:** `episode_id`, `speaker_role` (canonical label of the quoted speaker), `affect` (replacing `emotion` in the new codebook's schema; the old codebook keeps `emotion`).
4. **Sidecar additions:** `episodes` array (with per-episode `arc` for confrontations), `persona` (string, per video), `codebook_file`/`codebook_version` at top level. `speaker_names` already exists (v0.2.0).
5. **`corpus-summary`** aggregates per episode: counts by defense code, identity-talk code, outcome; mechanism×outcome cross-tab; per-video persona list.
6. **SKILL.md**: document the episode stage, `--codebook`, and the coding-scope rule.

**Unchanged:** dual transcription, adjudication contract, diarization panel + concordance, quote validation discipline, retention rules, the shipped narrative-gravity codebook, `/watch`.

## Corpus and workflow

- **Corpus:** 5–8 Cart Narcs videos from the channel's public uploads, chosen for confrontation density and variety (garage/lot, hostile/cooperative, persona variety). Multi-episode videos are expected and wanted. Download via existing `yt-dlp` path into one corpus folder; batch mode runs per the existing SKILL.md loop.
- **Per-video run:** transcribe → adjudicate → panel → concordance → **episodes** → coding pass (moral-identity codebook) → validate-flags → frames → render (`--interviewer "<persona>" --interviewee "Target"`).
- **Corpus outputs:** per-video sidecar + docx (as now, with episodes), `corpus_summary.json` (aggregates above), and a short **analysis memo** (markdown): counts, arcs, exemplar quotes per code — the raw material for the feature piece. The feature article itself is out of scope here.

## Error handling and edge cases

- **Silent targets** → target-speech gate; outcome/performance coding only.
- **Ambiguous episode boundaries** (hard cuts mid-interaction) → boundary set at the first turn addressing the new target; a `note` field on the episode records low-confidence boundaries.
- **UNCLEAR/OTHER turns** → belong to their containing episode; never coded for RQ1/RQ2 (speaker unattributable); excluded turns are countable per episode for transparency.
- **Multi-target crosstalk within one span** → if two targets genuinely interleave, split at the finest boundary the transcript supports; if inseparable, one episode with a note — never silently merged into a third pseudo-target.
- **Batch failures** → existing behavior: continue, record, name every failed file in the report.

## Testing

Follows the repo's pattern (pure-logic tests, no network, no LLM-judgment tests):

- **validate-episodes:** synthetic episode sets — overlap rejection, coverage gaps, bad enum, turn assignment correctness, aside-containment (to-camera turn inside a confrontation span stays in that episode).
- **Codebook selection:** `--codebook` loads the alternate file; `coding_scope` respected in validation (a CONFRONTER-quoted flag passes under the new codebook); old codebook's behavior byte-identical to today. *(As shipped: the same flag also passes under the shipped codebook, and that is the byte-identical-behavior requirement winning over this line. The shipped codebook declares no `coding_scope` and does not require `speaker_role`, so the scope check never runs for it and an out-of-scope `speaker_role` is simply an unread extra key. Enforcement arrives with the declaration, not with the flag.)*
- **Flag schema:** `episode_id`/`speaker_role`/`affect` validation; quote-speaker consistency (quote must lie in a turn whose label matches `speaker_role`).
- **Sidecar/corpus-summary:** episodes + arc serialization; aggregation counts on fixture sidecars.
- Full suite stays green (153 now; new tests added on top).

## Success criteria

- **Tool:** the 5–8-video batch runs end-to-end through the episode-aware pipeline with zero manual intervention outside the defined judgment steps (adjudication, panel, episode segmentation, coding); all tests green; artifacts uniform across videos.
- **Study:** every confrontation episode has a per-target profile (defense codes, identity talk, affect, arc, outcome) in which **every coded claim is auditable** to a verbatim quote + timestamp (+ frames where possible); corpus summary supports the descriptive claims in the analysis memo.

## Out of scope

- The feature article draft itself (downstream use of the memo).
- Automated scene narration (remains a manual hero-clip artifact).
- General N-speaker diarization; per-target voice identification.
- Corpus beyond 8 videos; any inferential statistics.
- Changes to `/watch` or the shipped narrative-gravity codebook's behavior.
