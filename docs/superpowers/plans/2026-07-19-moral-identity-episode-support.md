# Moral-Identity Codebook + Episode-Aware Gravitas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the moral-identity codebook and the additive pipeline support (codebook selection, episode segmentation/validation, flag/sidecar schema fields, episode-aware corpus aggregation) specified in `docs/superpowers/specs/2026-07-19-moral-identity-study-design.md`.

**Architecture:** All LLM judgment stays in SKILL.md; scripts stay deterministic and pure-stdlib. Every behavior change is driven by fields *declared in the codebook file* (`coding_scope`, `affect_field`, `enforce_attribution_gate`), so the shipped narrative-gravity codebook's behavior is byte-identical to today. New pure functions live in `analyze.py`; CLI wiring in `interview.py`; sidecar assembly in `render.py`.

**Tech Stack:** Python 3 stdlib only. pytest (no network; existing conventions in `tests/`). Run tests with the scratch venv pytest: `/private/tmp/claude-501/-Users-jeremiahwolf/d1bd7d9e-7c2b-45f0-bc5b-b48b5b010635/scratchpad/venv/bin/python -m pytest` from the repo root `/Users/jeremiahwolf/Desktop/Projects/APPs/Gravitas/gravitas` (or any pytest on PATH; suite currently 153 green).

**Repo:** `/Users/jeremiahwolf/Desktop/Projects/APPs/Gravitas/gravitas`, branch `main`.

---

## File structure

| File | Responsibility |
|---|---|
| `skills/interview/scripts/codebook_moral_identity.json` (create) | The study's versioned construct: 10 defense codes (Bandura 8 + responsibility_acceptance + aggression_threat), 4 identity-talk codes, 2 performance codes; affect vocabulary; coding scope; attribution gate; episode/arc enums documented in-file |
| `skills/interview/scripts/analyze.py` (modify) | New pure functions: `validate_episodes`, `assign_episode_ids`, `assign_flag_episodes`, `summarize_corpus`; generalized `validate_flags` (codebook-driven scope/affect/attribution) |
| `skills/interview/scripts/interview.py` (modify) | `--codebook` on validate-flags/render/corpus-summary; new `validate-episodes` subcommand; `--persona` on render; flag episode assignment |
| `skills/interview/scripts/render.py` (modify) | `build_sidecar` gains `episodes`, `persona`, `codebook_file`; sidecar `schema_version` → "1.1" |
| `skills/interview/SKILL.md` (modify) | Document the episode step, `--codebook`, coding-scope rule, `--persona`; version → 0.3.0 |
| `tests/test_interview_moral_codebook.py` (create) | Codebook invariants + generalized validate_flags behavior |
| `tests/test_interview_episodes.py` (create) | Episode validation/assignment + corpus aggregation + cmd wiring |
| `tests/test_interview_render.py` (modify) | Sidecar additions |
| `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json` (modify) | Version → 0.3.0 |

---

### Task 1: Commit the pending v0.2.0 speaker-names work

The working tree holds the finished, tested v0.2.0 feature (6 files). It must land as its own commit before this plan's work starts.

**Files:** none created — commits existing modifications.

- [ ] **Step 1: Verify the tree state and suite**

Run: `git -C /Users/jeremiahwolf/Desktop/Projects/APPs/Gravitas/gravitas status --short`
Expected: exactly these modified: `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`, `skills/interview/SKILL.md`, `skills/interview/scripts/interview.py`, `skills/interview/scripts/render.py`, `tests/test_interview_render.py` (untracked files are fine — do not add them).

Run: `python -m pytest -q` (from repo root, using the venv pytest above)
Expected: `153 passed`

- [ ] **Step 2: Commit**

```bash
git add .claude-plugin/plugin.json .codex-plugin/plugin.json skills/interview/SKILL.md \
  skills/interview/scripts/interview.py skills/interview/scripts/render.py tests/test_interview_render.py
git commit -m "feat: configurable speaker display names in render (v0.2.0)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: The moral-identity codebook file

**Files:**
- Create: `skills/interview/scripts/codebook_moral_identity.json`
- Test: `tests/test_interview_moral_codebook.py`

- [ ] **Step 1: Write the failing invariant tests**

Create `tests/test_interview_moral_codebook.py`:

```python
"""Moral-identity codebook: structural invariants + codebook-driven validation."""
from __future__ import annotations

import json
from pathlib import Path

from analyze import validate_flags

MORAL_PATH = (Path(__file__).resolve().parent.parent / "skills" / "interview"
              / "scripts" / "codebook_moral_identity.json")

BANDURA = {
    "moral_justification", "euphemistic_labeling", "advantageous_comparison",
    "displacement_of_responsibility", "diffusion_of_responsibility",
    "distortion_of_consequences", "dehumanization", "attribution_of_blame",
}


class TestMoralCodebookInvariants:
    def _cb(self):
        return json.loads(MORAL_PATH.read_text(encoding="utf-8"))

    def test_version_and_declared_fields(self):
        cb = self._cb()
        assert cb["codebook_version"] == "1.0.0"
        assert cb["coding_scope"] == ["INTERVIEWEE", "INTERVIEWER"]
        assert cb["affect_field"] == "affect"
        assert cb["enforce_attribution_gate"] is True

    def test_marker_families_complete(self):
        cb = self._cb()
        ids = {m["id"] for m in cb["markers"]}
        assert BANDURA <= ids
        assert {"responsibility_acceptance", "aggression_threat"} <= ids
        assert {"identity_threat", "identity_defense", "identity_repair",
                "identity_bestowal"} <= ids
        assert {"audience_address", "camera_awareness"} <= ids
        assert len(ids) == 16

    def test_defense_and_identity_markers_require_affect(self):
        cb = self._cb()
        req = {m["id"] for m in cb["markers"] if m.get("requires_affect")}
        assert BANDURA <= req
        assert {"responsibility_acceptance", "aggression_threat",
                "identity_threat", "identity_defense", "identity_repair",
                "identity_bestowal"} <= req
        assert "audience_address" not in req and "camera_awareness" not in req

    def test_affect_vocabulary_includes_neutral(self):
        cb = self._cb()
        vocab = set(cb["affect_vocabulary"])
        assert "neutral" in vocab
        assert {"anger", "contempt", "shame", "pride", "amusement"} <= vocab

    def test_flag_schema_requires_speaker_role(self):
        cb = self._cb()
        assert "speaker_role" in cb["flag_schema"]["required"]
        assert "affect" in cb["flag_schema"]["optional"]
        assert "attribution_uncertain" in cb["flag_schema"]["optional"]
        assert "episode_id" in cb["flag_schema"]["optional"]

    def test_arc_enums_allow_off_camera_turning_point(self):
        cb = self._cb()
        arc = cb["arc_schema"]
        assert set(arc["outcomes"]) == {"complies", "refuses", "escalates", "partial", "n/a"}
        assert "off-camera" in arc["turning_point_values"]
        assert {"threat", "defense", "escalation", "softening", "flip",
                "repair", "exit"} == set(arc["phases"])

    def test_every_marker_has_definition_and_indicators(self):
        cb = self._cb()
        for m in cb["markers"]:
            assert m["definition"].strip(), m["id"]
            assert m["indicators"], m["id"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_interview_moral_codebook.py -q`
Expected: FAIL (FileNotFoundError — codebook file doesn't exist).

- [ ] **Step 3: Create the codebook file**

Create `skills/interview/scripts/codebook_moral_identity.json`:

```json
{
  "codebook_version": "1.0.0",
  "construct": "Moral identity under public confrontation: how a person confronted on camera over a minor norm violation positions their behavior (moral disengagement vs. responsibility acceptance), negotiates identity (threat/defense/repair/bestowal), and performs for the recording.",
  "coding_scope": ["INTERVIEWEE", "INTERVIEWER"],
  "affect_field": "affect",
  "enforce_attribution_gate": true,
  "salience_scale": {
    "1": "Marker present but incidental; does not shape the surrounding exchange.",
    "2": "Marker colors the passage but the exchange would read the same without it.",
    "3": "Marker meaningfully shapes how the exchange should be interpreted.",
    "4": "Marker dominates the passage; a clear analytic anchor.",
    "5": "Marker defines the confrontation; the analysis cannot ignore it."
  },
  "affect_vocabulary": [
    "anger", "contempt", "frustration", "anxiety", "fear", "shame",
    "embarrassment", "sadness", "amusement", "pride", "relief", "neutral"
  ],
  "markers": [
    {
      "id": "moral_justification",
      "name": "Moral justification",
      "definition": "The act is reframed as serving a worthy or moral purpose.",
      "indicators": ["appeals to a greater good", "recasting the violation as helpful or considerate"],
      "requires_affect": true
    },
    {
      "id": "euphemistic_labeling",
      "name": "Euphemistic labeling / minimization",
      "definition": "Minimizing or sanitizing language reduces the act's moral weight.",
      "indicators": ["'all I did was ...'", "'just left it right there'", "diminutive re-description of the act"],
      "requires_affect": true
    },
    {
      "id": "advantageous_comparison",
      "name": "Advantageous comparison",
      "definition": "The act is excused by contrast with worse conduct by others.",
      "indicators": ["'what about those fifty carts over there'", "pointing to other violators or worse offenses"],
      "requires_affect": true
    },
    {
      "id": "displacement_of_responsibility",
      "name": "Displacement of responsibility",
      "definition": "Responsibility is shifted to an authority, role, or circumstance beyond the speaker's agency.",
      "indicators": ["'that's the store's job'", "'they get paid to do that'", "'not my job'", "incapacity claims offered as excusing conditions"],
      "requires_affect": true
    },
    {
      "id": "diffusion_of_responsibility",
      "name": "Diffusion of responsibility",
      "definition": "Responsibility is dissolved into a group norm.",
      "indicators": ["'everyone does it'", "'people leave carts all the time'"],
      "requires_affect": true
    },
    {
      "id": "distortion_of_consequences",
      "name": "Distortion of consequences",
      "definition": "The act's harm is denied, minimized, or questioned.",
      "indicators": ["'what damage does that do'", "'it doesn't matter'", "'it's not hurting anyone'"],
      "requires_affect": true
    },
    {
      "id": "dehumanization",
      "name": "Dehumanization",
      "definition": "The confronter or victim class is stripped of moral regard.",
      "indicators": ["derogation denying the other's standing as a person worth moral consideration"],
      "requires_affect": true
    },
    {
      "id": "attribution_of_blame",
      "name": "Attribution of blame",
      "definition": "The confronter (or circumstances) is recast as the true wrongdoer; condemning the condemner.",
      "indicators": ["'you're harassing me'", "'don't touch my property'", "litigation threats", "reframing the confrontation itself as the offense"],
      "requires_affect": true
    },
    {
      "id": "responsibility_acceptance",
      "name": "Responsibility acceptance",
      "definition": "Acknowledgment of wrongdoing: admission of the act TOGETHER WITH acceptance of its wrongness — apology, self-blame, or repair. A defiant admission of the act that rejects the norm's force ('Yes, I did. It doesn't matter.') is NOT acceptance.",
      "indicators": ["'I screwed up'", "'I shouldn't have done it'", "apology", "voluntary repair (returning the cart)"],
      "requires_affect": true
    },
    {
      "id": "aggression_threat",
      "name": "Aggression / threat",
      "definition": "Verbal aggression or threat of harm toward the confronter; the flag-level evidence for arc escalation phases.",
      "indicators": ["explicit threats ('I will hit you')", "profanity-laden aggression directed at the confronter", "physical intimidation narrated in speech"],
      "requires_affect": true
    },
    {
      "id": "identity_threat",
      "name": "Identity threat",
      "definition": "A speaker impugns the other's moral identity (or a negative identity is imposed).",
      "indicators": ["'I think you were lying'", "'you were being catatonic'", "'litterbug' labeling", "'your ego won't let you'"],
      "requires_affect": true
    },
    {
      "id": "identity_defense",
      "name": "Identity defense",
      "definition": "A speaker asserts a positive self-claim under threat.",
      "indicators": ["'I'm not lying'", "'I'm being polite'", "'I'm trying to be as nice as I can be'", "disability/exemption self-claims deployed to protect the self"],
      "requires_affect": true
    },
    {
      "id": "identity_repair",
      "name": "Identity repair",
      "definition": "A speaker re-narrates the self after admission — restoring moral identity through ownership.",
      "indicators": ["'I screwed up and you got me'", "declining mitigation to affirm the norm", "public self-identification after repair"],
      "requires_affect": true
    },
    {
      "id": "identity_bestowal",
      "name": "Identity bestowal",
      "definition": "One speaker grants the other an identity, positive or negative.",
      "indicators": ["'that's actually being a real man'", "'you're better than most'", "handing over a 'litterbug' magnet as labeling act"],
      "requires_affect": true
    },
    {
      "id": "audience_address",
      "name": "Audience address / persona work",
      "definition": "Speech aimed at the recording's future audience or delivered in persona.",
      "indicators": ["'Narcoteers'", "agent persona self-introductions", "narrating the encounter to camera"],
      "requires_affect": false
    },
    {
      "id": "camera_awareness",
      "name": "Camera awareness",
      "definition": "A target registers being filmed or being future content.",
      "indicators": ["remarks about the camera or being recorded", "jokes about the recording's consequences"],
      "requires_affect": false
    }
  ],
  "episode_schema": {
    "types": ["confrontation", "commendation", "bystander", "to-camera"],
    "required": ["id", "type", "t_start", "t_end"],
    "confrontation_required": ["target_descriptor", "target_speech"]
  },
  "arc_schema": {
    "phases": ["threat", "defense", "escalation", "softening", "flip", "repair", "exit"],
    "outcomes": ["complies", "refuses", "escalates", "partial", "n/a"],
    "turning_point_values": ["<turn-id>", "off-camera", null]
  },
  "flag_schema": {
    "required": ["id", "marker_types", "quote", "t_start", "t_end", "salience", "speaker_role"],
    "optional": ["affect", "episode_id", "attribution_uncertain", "note", "frame_paths", "frames_missing", "visual_evidence"],
    "rules": [
      "id: 'g' + 4-digit sequence, e.g. g0001",
      "marker_types: non-empty list of marker ids from this codebook",
      "speaker_role: canonical label of the quoted speaker; must be in coding_scope",
      "affect: required iff any marker has requires_affect; must be from affect_vocabulary ('neutral' is the no-signal value)",
      "quote: verbatim substring of the final transcript, single speaker only",
      "attribution_uncertain: required true when the quoted turn's concordance < 1.0 or label is UNCLEAR",
      "episode_id: assigned by the tool from episodes.json at validate time",
      "t_start/t_end: seconds, within media duration, t_start <= t_end",
      "salience: integer 1-5 per salience_scale",
      "visual_evidence: one of corroborates|contradicts|neutral, plus a short note — set only after frames are read"
    ]
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_interview_moral_codebook.py -q`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add skills/interview/scripts/codebook_moral_identity.json tests/test_interview_moral_codebook.py
git commit -m "feat: moral-identity codebook v1.0.0 (Bandura + identity talk + performance)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Generalize `validate_flags` — codebook-driven affect field, vocabulary, and speaker scope

**Files:**
- Modify: `skills/interview/scripts/analyze.py:135-190` (`validate_flags`)
- Test: `tests/test_interview_moral_codebook.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_interview_moral_codebook.py`:

```python
MINI_MORAL = {
    "codebook_version": "1.0.0",
    "coding_scope": ["INTERVIEWEE", "INTERVIEWER"],
    "affect_field": "affect",
    "affect_vocabulary": ["anger", "shame", "neutral"],
    "enforce_attribution_gate": False,
    "markers": [
        {"id": "attribution_of_blame", "definition": "x", "indicators": ["y"], "requires_affect": True},
        {"id": "audience_address", "definition": "x", "indicators": ["y"], "requires_affect": False},
    ],
    "flag_schema": {"required": ["id", "marker_types", "quote", "t_start", "t_end",
                                 "salience", "speaker_role"],
                    "optional": ["affect", "attribution_uncertain", "episode_id"]},
}

TURNS = [
    {"id": "m0001", "start": 0.0, "end": 4.0, "text": "Why is this cart here?",
     "label": "INTERVIEWER", "concordance": 1.0, "segment_indices": [0]},
    {"id": "m0002", "start": 5.0, "end": 9.0, "text": "Don't touch my property.",
     "label": "INTERVIEWEE", "concordance": 1.0, "segment_indices": [1]},
]


def moral_flag(**over):
    base = {"id": "g0001", "marker_types": ["attribution_of_blame"],
            "quote": "Don't touch my property.", "t_start": 5.0, "t_end": 9.0,
            "salience": 3, "speaker_role": "INTERVIEWEE", "affect": "anger"}
    base.update(over)
    return base


class TestCodebookDrivenValidation:
    def test_valid_moral_flag_passes(self):
        assert validate_flags([moral_flag()], MINI_MORAL, 100.0, turns=TURNS) == []

    def test_affect_field_and_vocabulary_enforced(self):
        errs = validate_flags([moral_flag(affect="smug")], MINI_MORAL, 100.0, turns=TURNS)
        assert any("'smug' not in codebook vocabulary" in e for e in errs)
        errs = validate_flags([moral_flag(affect=None)], MINI_MORAL, 100.0, turns=TURNS)
        assert any("requires an affect" in e for e in errs)

    def test_marker_without_requires_affect_allows_missing_affect(self):
        f = moral_flag(marker_types=["audience_address"], affect=None,
                       quote="Why is this cart here?", t_start=0.0, t_end=4.0,
                       speaker_role="INTERVIEWER")
        assert validate_flags([f], MINI_MORAL, 100.0, turns=TURNS) == []

    def test_speaker_role_outside_scope_rejected(self):
        cb = dict(MINI_MORAL, coding_scope=["INTERVIEWEE"])
        f = moral_flag(speaker_role="INTERVIEWER", quote="Why is this cart here?",
                       t_start=0.0, t_end=4.0)
        errs = validate_flags([f], cb, 100.0, turns=TURNS)
        assert any("speaker_role 'INTERVIEWER' not in coding scope" in e for e in errs)

    def test_quote_must_lie_in_turn_with_matching_label(self):
        f = moral_flag(speaker_role="INTERVIEWER")  # quote is an INTERVIEWEE line
        errs = validate_flags([f], MINI_MORAL, 100.0, turns=TURNS)
        assert any("no INTERVIEWER turn near" in e for e in errs)

    def test_old_codebook_behavior_unchanged(self):
        old = {"codebook_version": "1.0.0",
               "emotions": ["anger"],
               "markers": [{"id": "emotional_display", "definition": "x",
                            "indicators": ["y"], "requires_emotion": True}],
               "flag_schema": {"required": ["id", "marker_types", "quote",
                                            "t_start", "t_end", "salience"]}}
        f = {"id": "g0001", "marker_types": ["emotional_display"],
             "quote": "Don't touch my property.", "t_start": 5.0, "t_end": 9.0,
             "salience": 3, "emotion": "anger"}
        assert validate_flags([f], old, 100.0, turns=TURNS) == []
        f2 = dict(f, emotion=None)
        errs = validate_flags([f2], old, 100.0, turns=TURNS)
        assert any("requires an emotion" in e for e in errs)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_interview_moral_codebook.py -q`
Expected: FAIL — `validate_flags() got an unexpected keyword argument 'turns'`.

- [ ] **Step 3: Implement**

In `skills/interview/scripts/analyze.py`, replace the `validate_flags` function (lines 135–190) with:

```python
def _find_quote_turn(flag: dict, turns: list[dict], label: str | None = None) -> dict | None:
    """First turn containing the flag's quote, optionally restricted to a label,
    whose span overlaps the flag's [t_start-2, t_end+2] window (mirrors the
    docx anchor slop). Falls back to text-only match when timestamps are absent."""
    quote = flag.get("quote") or ""
    if not quote:
        return None
    t0, t1 = flag.get("t_start"), flag.get("t_end")
    timed = isinstance(t0, (int, float)) and isinstance(t1, (int, float))
    for turn in turns:
        if label is not None and turn.get("label") != label:
            continue
        if quote not in turn["text"]:
            continue
        if not timed or (t0 <= turn["end"] + 2.0 and t1 >= turn["start"] - 2.0):
            return turn
    return None


def validate_flags(
    flags: list[dict],
    codebook: dict,
    duration: float,
    transcript_text: str | None = None,
    turns: list[dict] | None = None,
) -> list[str]:
    """Return a list of human-readable schema violations (empty = valid).

    When `transcript_text` is provided, every quote must be a verbatim
    substring of it — paraphrased quotes are research-record corruption.

    Codebook-declared behavior (defaults preserve the shipped narrative-gravity
    codebook exactly): `affect_field` names the affect key ("emotion" default);
    `affect_vocabulary` (fallback: `emotions`) is its vocabulary; markers with
    `requires_affect`/`requires_emotion` demand it; `coding_scope` (default
    ["INTERVIEWEE"]) gates `speaker_role` when the schema requires that field;
    `enforce_attribution_gate` demands `attribution_uncertain: true` on flags
    whose quoted turn has concordance < 1.0 or label UNCLEAR (needs `turns`).
    """
    errors: list[str] = []
    marker_ids = {m["id"] for m in codebook["markers"]}
    affect_field = codebook.get("affect_field", "emotion")
    vocab = set(codebook.get("affect_vocabulary") or codebook.get("emotions") or [])
    requiring = {m["id"] for m in codebook["markers"]
                 if m.get("requires_affect") or m.get("requires_emotion")}
    required = codebook["flag_schema"]["required"]
    scope = set(codebook.get("coding_scope", ["INTERVIEWEE"]))
    check_role = "speaker_role" in required
    gate = bool(codebook.get("enforce_attribution_gate"))

    for i, flag in enumerate(flags):
        ref = flag.get("id", f"flags[{i}]")
        for field in required:
            if flag.get(field) in (None, "", []):
                errors.append(f"{ref}: missing required field '{field}'")
        quote = flag.get("quote")
        if transcript_text is not None and quote and quote not in transcript_text:
            errors.append(f"{ref}: quote is not a verbatim substring of the transcript")
        markers = flag.get("marker_types")
        if markers in (None, "", []):
            markers = []  # already reported missing by the required-field check
        elif not isinstance(markers, list):
            errors.append(f"{ref}: marker_types must be a list (got {type(markers).__name__})")
            markers = []
        for m in markers:
            if m not in marker_ids:
                errors.append(f"{ref}: unknown marker '{m}'")
        if any(m in requiring for m in markers):
            value = flag.get(affect_field)
            if not value:
                errors.append(f"{ref}: marker requires an {affect_field}")
            elif value not in vocab:
                errors.append(f"{ref}: {affect_field} '{value}' not in codebook vocabulary")
        role = flag.get("speaker_role")
        if check_role and role:
            if role not in scope:
                errors.append(f"{ref}: speaker_role '{role}' not in coding scope {sorted(scope)}")
            elif turns is not None and quote and _find_quote_turn(flag, turns, label=role) is None:
                errors.append(f"{ref}: no {role} turn near [{flag.get('t_start')}, "
                              f"{flag.get('t_end')}] contains the quote")
        if gate and turns is not None and quote:
            home = _find_quote_turn(flag, turns)
            if home is not None and (home.get("label") == "UNCLEAR"
                                     or float(home.get("concordance", 1.0)) < 1.0):
                if flag.get("attribution_uncertain") is not True:
                    errors.append(f"{ref}: quoted turn {home['id']} has concordance "
                                  f"{home.get('concordance')} — flag must set "
                                  f"attribution_uncertain: true")
        salience = flag.get("salience")
        if not isinstance(salience, int) or isinstance(salience, bool) or not 1 <= salience <= 5:
            errors.append(f"{ref}: salience must be an integer 1-5 (got {salience!r})")
        t_start, t_end = flag.get("t_start"), flag.get("t_end")
        if isinstance(t_start, (int, float)) and isinstance(t_end, (int, float)):
            if t_start > t_end:
                errors.append(f"{ref}: t_start > t_end")
            if t_end > duration + 1.0 or t_start < 0:
                dur_txt = "unknown" if duration == float("inf") else f"{duration:.0f}s"
                errors.append(f"{ref}: timestamps outside media duration ({dur_txt})")

    # Frame extraction keys output dirs by flag id — duplicate ids would
    # silently cross-contaminate each other's visual evidence.
    ids = [f.get("id") for f in flags if f.get("id")]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(f"{dup}: duplicate flag id")
    return errors
```

Note: the emotion error message changes from `emotional_display requires an emotion` to `marker requires an emotion`. Update the existing test in `tests/test_interview_concordance.py` (`test_emotional_display_requires_valid_emotion`) if it asserts the old wording — check with `grep -n "requires an emotion" tests/test_interview_concordance.py` and adjust the assertion string to `"requires an emotion"` (substring both wordings share) if needed.

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest tests/test_interview_moral_codebook.py tests/test_interview_concordance.py -q`
Expected: all pass (13 in the new file, 30 in concordance).

- [ ] **Step 5: Commit**

```bash
git add skills/interview/scripts/analyze.py tests/test_interview_moral_codebook.py tests/test_interview_concordance.py
git commit -m "feat: codebook-driven flag validation (affect field, vocabulary, speaker scope)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Attribution-uncertainty gate test coverage

The gate was implemented in Task 3; this task locks it with dedicated tests (it's the dry run's amendment 4 and deserves explicit coverage).

**Files:**
- Test: `tests/test_interview_moral_codebook.py` (append)

- [ ] **Step 1: Write the tests**

Append to `tests/test_interview_moral_codebook.py`:

```python
class TestAttributionGate:
    LOW_TURNS = [
        {"id": "m0001", "start": 0.0, "end": 4.0, "text": "Or that 50 people over there?",
         "label": "INTERVIEWEE", "concordance": 0.6667, "segment_indices": [0]},
        {"id": "m0002", "start": 5.0, "end": 9.0, "text": "Don't touch my property.",
         "label": "INTERVIEWEE", "concordance": 1.0, "segment_indices": [1]},
    ]
    GATED = dict(MINI_MORAL, enforce_attribution_gate=True)

    def test_low_concordance_quote_requires_uncertainty_flag(self):
        f = moral_flag(quote="Or that 50 people over there?", t_start=0.0, t_end=4.0)
        errs = validate_flags([f], self.GATED, 100.0, turns=self.LOW_TURNS)
        assert any("attribution_uncertain" in e for e in errs)

    def test_uncertainty_flag_satisfies_gate(self):
        f = moral_flag(quote="Or that 50 people over there?", t_start=0.0, t_end=4.0,
                       attribution_uncertain=True)
        assert validate_flags([f], self.GATED, 100.0, turns=self.LOW_TURNS) == []

    def test_full_concordance_quote_needs_no_flag(self):
        assert validate_flags([moral_flag()], self.GATED, 100.0, turns=self.LOW_TURNS) == []

    def test_gate_off_means_no_requirement(self):
        f = moral_flag(quote="Or that 50 people over there?", t_start=0.0, t_end=4.0)
        assert validate_flags([f], MINI_MORAL, 100.0, turns=self.LOW_TURNS) == []
```

- [ ] **Step 2: Run tests to verify they pass** (implementation landed in Task 3)

Run: `python -m pytest tests/test_interview_moral_codebook.py -q`
Expected: 17 passed. If any fail, fix `validate_flags` (not the tests) until green.

- [ ] **Step 3: Commit**

```bash
git add tests/test_interview_moral_codebook.py
git commit -m "test: lock attribution-uncertainty gate behavior

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Episode validation and assignment (pure functions)

**Files:**
- Modify: `skills/interview/scripts/analyze.py` (append after `burst_timestamps`)
- Test: `tests/test_interview_episodes.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_interview_episodes.py`:

```python
"""Episode segmentation: validation, turn/flag assignment, corpus aggregation."""
from __future__ import annotations

from analyze import assign_episode_ids, assign_flag_episodes, validate_episodes


def ep(eid, etype, t0, t1, **over):
    base = {"id": eid, "type": etype, "t_start": t0, "t_end": t1}
    if etype == "confrontation":
        base["target_descriptor"] = "someone"
        base["target_speech"] = True
    base.update(over)
    return base


def turn(tid, t0, t1):
    return {"id": tid, "start": t0, "end": t1, "text": "x",
            "label": "INTERVIEWEE", "concordance": 1.0, "segment_indices": [0]}


EPISODES = [
    ep("e01", "confrontation", 0.0, 100.0, target_descriptor="woman in garage"),
    ep("e02", "commendation", 100.0, 120.0),
    ep("e03", "confrontation", 130.0, 200.0, target_descriptor="Scott"),
]
TURNS = [turn("t0001", 0.0, 4.0), turn("t0002", 50.0, 55.0),
         turn("t0003", 110.0, 112.0), turn("t0004", 130.0, 133.0)]


class TestValidateEpisodes:
    def test_valid_set_passes(self):
        assert validate_episodes(EPISODES, TURNS) == []

    def test_gap_between_episodes_is_allowed(self):
        # 120-130 has no turns — silent B-roll; coverage is over turns, not time
        assert validate_episodes(EPISODES, TURNS) == []

    def test_overlap_rejected(self):
        bad = [ep("e01", "confrontation", 0.0, 100.0),
               ep("e02", "commendation", 90.0, 120.0)]
        errs = validate_episodes(bad, TURNS[:3])
        assert any("overlaps" in e for e in errs)

    def test_unknown_type_rejected(self):
        errs = validate_episodes([ep("e01", "interview", 0.0, 200.0)], TURNS)
        assert any("unknown type" in e for e in errs)

    def test_uncovered_turn_rejected(self):
        errs = validate_episodes(EPISODES[:2], TURNS)  # t0004 at 130 uncovered
        assert any("t0004" in e and "no episode" in e for e in errs)

    def test_confrontation_requires_descriptor_and_speech_bool(self):
        e = ep("e01", "confrontation", 0.0, 200.0)
        del e["target_descriptor"]
        errs = validate_episodes([e], TURNS)
        assert any("target_descriptor" in x for x in errs)
        e2 = ep("e01", "confrontation", 0.0, 200.0, target_speech="yes")
        errs = validate_episodes([e2], TURNS)
        assert any("target_speech must be true/false" in x for x in errs)

    def test_duplicate_ids_rejected(self):
        bad = [ep("e01", "to-camera", 0.0, 60.0), ep("e01", "to-camera", 60.0, 200.0)]
        errs = validate_episodes(bad, TURNS[:2])
        assert any("duplicate episode id" in e for e in errs)

    def test_arc_enums_validated(self):
        e = ep("e01", "confrontation", 0.0, 200.0,
               arc={"phases": ["threat", "victory"], "outcome": "wins",
                    "turning_point": "off-camera"})
        errs = validate_episodes([e], TURNS)
        assert any("unknown arc phase 'victory'" in x for x in errs)
        assert any("unknown arc outcome 'wins'" in x for x in errs)

    def test_arc_off_camera_turning_point_allowed(self):
        e = ep("e01", "confrontation", 0.0, 200.0,
               arc={"phases": ["repair", "exit"], "outcome": "complies",
                    "turning_point": "off-camera"})
        assert validate_episodes([e], TURNS) == []


class TestAssignment:
    def test_turns_get_episode_ids(self):
        turns = assign_episode_ids([dict(t) for t in TURNS], EPISODES)
        assert [t["episode_id"] for t in turns] == ["e01", "e01", "e02", "e03"]

    def test_boundary_turn_goes_to_containing_episode(self):
        # t_start exactly at e02's start belongs to e02 (containment is start-inclusive)
        turns = assign_episode_ids([turn("t0001", 100.0, 104.0)], EPISODES)
        assert turns[0]["episode_id"] == "e02"

    def test_flags_get_episode_ids_and_orphans_error(self):
        flags = [{"id": "g0001", "t_start": 50.0, "t_end": 52.0},
                 {"id": "g0002", "t_start": 125.0, "t_end": 126.0}]
        errs = assign_flag_episodes(flags, EPISODES)
        assert flags[0]["episode_id"] == "e01"
        assert any("g0002" in e and "outside every episode" in e for e in errs)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_interview_episodes.py -q`
Expected: FAIL — `ImportError: cannot import name 'validate_episodes'`.

- [ ] **Step 3: Implement**

Append to `skills/interview/scripts/analyze.py` (after `burst_timestamps`):

```python
EPISODE_TYPES = {"confrontation", "commendation", "bystander", "to-camera"}
ARC_PHASES = {"threat", "defense", "escalation", "softening", "flip", "repair", "exit"}
ARC_OUTCOMES = {"complies", "refuses", "escalates", "partial", "n/a"}


def validate_episodes(episodes: list[dict], turns: list[dict]) -> list[str]:
    """Return human-readable violations (empty = valid).

    Episodes are ordered, non-overlapping time spans. Gaps BETWEEN episodes are
    legal (silent B-roll holds no turns); coverage is enforced over turns —
    every turn's start must fall inside exactly one episode. Arc objects are
    optional; when present their enums are checked (turning_point may be a
    turn id or the literal "off-camera" — arcs can turn before the camera ran).
    """
    errors: list[str] = []
    if not isinstance(episodes, list) or not episodes:
        return ["episodes.json must be a non-empty array"]
    ids = [e.get("id") for e in episodes]
    for dup in sorted({i for i in ids if i and ids.count(i) > 1}):
        errors.append(f"{dup}: duplicate episode id")
    prev_end, prev_id = None, None
    for i, e in enumerate(episodes):
        ref = e.get("id", f"episodes[{i}]")
        for field in ("id", "type", "t_start", "t_end"):
            if e.get(field) in (None, ""):
                errors.append(f"{ref}: missing required field '{field}'")
        etype = e.get("type")
        if etype and etype not in EPISODE_TYPES:
            errors.append(f"{ref}: unknown type '{etype}' (valid: {sorted(EPISODE_TYPES)})")
        t0, t1 = e.get("t_start"), e.get("t_end")
        if isinstance(t0, (int, float)) and isinstance(t1, (int, float)):
            if t0 > t1:
                errors.append(f"{ref}: t_start > t_end")
            if prev_end is not None and t0 < prev_end:
                errors.append(f"{ref}: overlaps {prev_id} (starts at {t0} before its end {prev_end})")
            prev_end, prev_id = t1, ref
        if etype == "confrontation":
            if not str(e.get("target_descriptor") or "").strip():
                errors.append(f"{ref}: confrontation requires a target_descriptor")
            if not isinstance(e.get("target_speech"), bool):
                errors.append(f"{ref}: target_speech must be true/false")
        arc = e.get("arc")
        if arc is not None:
            for ph in arc.get("phases", []):
                if ph not in ARC_PHASES:
                    errors.append(f"{ref}: unknown arc phase '{ph}'")
            outcome = arc.get("outcome")
            if outcome is not None and outcome not in ARC_OUTCOMES:
                errors.append(f"{ref}: unknown arc outcome '{outcome}'")
            tp = arc.get("turning_point")
            if tp is not None and not isinstance(tp, str):
                errors.append(f"{ref}: turning_point must be a turn id, 'off-camera', or null")
    for t in turns:
        if _containing_episode(float(t["start"]), episodes) is None:
            errors.append(f"{t.get('id', '?')}: start {t['start']} falls in no episode")
    return errors


def _containing_episode(t: float, episodes: list[dict]) -> dict | None:
    """Half-open containment [t_start, t_end) so a time exactly on a shared
    boundary belongs to the LATER episode; the final episode is end-inclusive
    so the recording's last turn is never orphaned."""
    for i, e in enumerate(episodes):
        t0, t1 = e.get("t_start"), e.get("t_end")
        if not (isinstance(t0, (int, float)) and isinstance(t1, (int, float))):
            continue
        last = i == len(episodes) - 1
        if t0 <= t < t1 or (last and t == t1):
            return e
    return None


def assign_episode_ids(turns: list[dict], episodes: list[dict]) -> list[dict]:
    """Stamp episode_id onto each turn by start-time containment (in place).
    Call only after validate_episodes returns clean — assumes full coverage."""
    for t in turns:
        home = _containing_episode(float(t["start"]), episodes)
        if home is None:
            raise ValueError(f"{t.get('id', '?')}: start {t['start']} falls in no episode")
        t["episode_id"] = home["id"]
    return turns


def assign_flag_episodes(flags: list[dict], episodes: list[dict]) -> list[str]:
    """Stamp episode_id onto each flag by t_start containment (in place).
    Returns errors for flags outside every episode instead of raising — flag
    placement is a judgment product and its errors go back to the coder."""
    errors: list[str] = []
    for f in flags:
        home = _containing_episode(float(f.get("t_start", -1)), episodes)
        if home is None:
            errors.append(f"{f.get('id', '?')}: t_start {f.get('t_start')} outside every episode")
        else:
            f["episode_id"] = home["id"]
    return errors
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_interview_episodes.py -q`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add skills/interview/scripts/analyze.py tests/test_interview_episodes.py
git commit -m "feat: episode validation and turn/flag episode assignment

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: CLI wiring — `validate-episodes` subcommand, `--codebook` on validate-flags, flag episode stamping

**Files:**
- Modify: `skills/interview/scripts/interview.py` (imports; `cmd_validate_flags`; new `cmd_validate_episodes`; `main()` parser)
- Test: `tests/test_interview_episodes.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_interview_episodes.py`:

```python
import json
from pathlib import Path
from types import SimpleNamespace

import interview


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


MORAL_CB = (Path(__file__).resolve().parent.parent / "skills" / "interview"
            / "scripts" / "codebook_moral_identity.json")


class TestCmdValidateEpisodes:
    def _work(self, tmp_path, episodes, turns):
        work = tmp_path / "work"
        _write(work / "episodes.json", episodes)
        _write(work / "diarized.json", turns)
        return work

    def test_valid_episodes_stamp_turns(self, tmp_path, capsys):
        work = self._work(tmp_path, EPISODES, TURNS)
        rc = interview.cmd_validate_episodes(SimpleNamespace(work=str(work)))
        assert rc == 0
        stamped = json.loads((work / "diarized.json").read_text())
        assert [t["episode_id"] for t in stamped] == ["e01", "e01", "e02", "e03"]
        assert "e01" in capsys.readouterr().out

    def test_invalid_episodes_error_and_leave_turns_unstamped(self, tmp_path, capsys):
        bad = [ep("e01", "confrontation", 0.0, 100.0),
               ep("e02", "commendation", 90.0, 120.0)]
        work = self._work(tmp_path, bad, TURNS[:3])
        rc = interview.cmd_validate_episodes(SimpleNamespace(work=str(work)))
        assert rc == 1
        assert "episode_id" not in json.loads((work / "diarized.json").read_text())[0]


class TestCmdValidateFlagsMoral:
    def test_moral_codebook_flags_pass_and_get_episode_ids(self, tmp_path):
        work = tmp_path / "work"
        turns = [dict(turn("t0001", 50.0, 55.0), text="Don't touch my property.")]
        _write(work / "diarized.json", turns)
        _write(work / "episodes.json", EPISODES)
        _write(work / "flags.json", [{
            "id": "g0001", "marker_types": ["attribution_of_blame"],
            "quote": "Don't touch my property.", "t_start": 50.0, "t_end": 55.0,
            "salience": 3, "speaker_role": "INTERVIEWEE", "affect": "anger"}])
        rc = interview.cmd_validate_flags(SimpleNamespace(
            work=str(work), duration="200", codebook=str(MORAL_CB)))
        assert rc == 0
        flags = json.loads((work / "flags.json").read_text())
        assert flags[0]["episode_id"] == "e01"

    def test_default_codebook_unchanged(self, tmp_path):
        work = tmp_path / "work"
        _write(work / "flags.json", [{
            "id": "g0001", "marker_types": ["quoted_speech"],
            "quote": "he said no", "t_start": 1.0, "t_end": 2.0, "salience": 2}])
        rc = interview.cmd_validate_flags(SimpleNamespace(
            work=str(work), duration="10", codebook=None))
        assert rc == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_interview_episodes.py -q`
Expected: FAIL — `AttributeError: module 'interview' has no attribute 'cmd_validate_episodes'` and Namespace errors on `codebook`.

- [ ] **Step 3: Implement**

In `skills/interview/scripts/interview.py`:

(a) Extend the `analyze` import block (lines 16–23) to:

```python
from analyze import (
    assign_episode_ids,
    assign_flag_episodes,
    build_turns,
    burst_timestamps,
    compute_concordance,
    merge_labeled_turns,
    segment_turns,
    validate_episodes,
    validate_flags,
)
```

(b) Add after `cmd_concordance`:

```python
def cmd_validate_episodes(args) -> int:
    work = Path(args.work)
    episodes = _load(work / "episodes.json")
    turns = _load(work / "diarized.json")
    errors = validate_episodes(episodes, turns)
    if errors:
        print("INVALID EPISODES:")
        for e in errors:
            print(f"  {e}")
        return 1
    assign_episode_ids(turns, episodes)
    _save(work / "diarized.json", turns)
    from collections import Counter
    per_ep = Counter(t["episode_id"] for t in turns)
    print(f"EPISODES: {len(episodes)}")
    for e in episodes:
        desc = f' target="{e.get("target_descriptor", "")}"' if e["type"] == "confrontation" else ""
        print(f"  {e['id']} {e['type']} [{format_hms(e['t_start'])}-{format_hms(e['t_end'])}] "
              f"turns={per_ep.get(e['id'], 0)}{desc}")
    return 0
```

(c) In `cmd_validate_flags`, replace `codebook = _load(CODEBOOK_PATH)` with:

```python
    codebook_path = Path(args.codebook) if getattr(args, "codebook", None) else CODEBOOK_PATH
    codebook = _load(codebook_path)
```

and replace the tail of the function — from the `transcript_text = None` line through `return 0` — with:

```python
    transcript_text = None
    merged = None
    if (work / "diarized.json").exists():
        turns = _load(work / "diarized.json")
        if turns and all("label" in t for t in turns):
            # Validate against the same merged view the docx anchors against,
            # so a verbatim quote spanning two same-speaker sentences passes.
            merged = merge_labeled_turns(turns)
            transcript_text = "\n".join(t["text"] for t in merged)
        else:
            transcript_text = "\n".join(t["text"] for t in turns)
    errors = validate_flags(flags, codebook, duration,
                            transcript_text=transcript_text, turns=merged)
    ep_path = work / "episodes.json"
    if not errors and ep_path.exists():
        errors = assign_flag_episodes(flags, _load(ep_path))
        if not errors:
            _save(work / "flags.json", flags)
    if errors:
        print("INVALID FLAGS:")
        for e in errors:
            print(f"  {e}")
        return 1
    print(f"OK: {len(flags)} flags valid against codebook {codebook['codebook_version']} "
          f"({codebook_path.name})")
    return 0
```

(d) In `main()`: extend the two parser lines:

```python
    p = sub.add_parser("validate-episodes"); p.add_argument("--work", required=True)
    p = sub.add_parser("validate-flags"); p.add_argument("--work", required=True); p.add_argument("--duration"); p.add_argument("--codebook", metavar="PATH", help="alternate codebook file (default: shipped codebook.json)")
```

and register the handler in the dispatch dict: `"validate-episodes": cmd_validate_episodes,`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_interview_episodes.py -q`
Expected: 16 passed.

- [ ] **Step 5: Commit**

```bash
git add skills/interview/scripts/interview.py tests/test_interview_episodes.py
git commit -m "feat: validate-episodes subcommand + --codebook and episode stamping on validate-flags

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Sidecar additions — episodes, persona, codebook identity; render flags

**Files:**
- Modify: `skills/interview/scripts/render.py` (`build_sidecar`)
- Modify: `skills/interview/scripts/interview.py` (`cmd_render`; `main()` render parser)
- Test: `tests/test_interview_render.py` (append)

- [ ] **Step 1: Write the failing tests**

Append inside `class TestSidecar` in `tests/test_interview_render.py`:

```python
    def test_episodes_persona_and_codebook_identity_recorded(self):
        eps = [{"id": "e01", "type": "confrontation", "t_start": 0.0, "t_end": 30.0,
                "target_descriptor": "woman", "target_speech": True,
                "arc": {"phases": ["threat", "defense"], "outcome": "refuses",
                        "turning_point": None}}]
        sc = build_sidecar(
            media="x.mp4", duration=10.0,
            engines={"groq": "whisper-large-v3", "openai": "whisper-1"},
            degradation=[], segments=[], turns=TURNS, adjudications=[], flags=[],
            partial_failures=[], codebook_version="1.0.0", now="2026-07-10T12:00:00",
            episodes=eps, persona="Agent Greg Gorey",
            codebook_file="codebook_moral_identity.json",
        )
        assert sc["schema_version"] == "1.1"
        assert sc["codebook_version"] == "1.0.0"
        assert sc["episodes"][0]["arc"]["outcome"] == "refuses"
        assert sc["interview"]["persona"] == "Agent Greg Gorey"
        assert sc["codebook_file"] == "codebook_moral_identity.json"
        # deep-copied — mutating the sidecar must not touch the caller's episodes
        sc["episodes"][0]["arc"]["phases"].append("exit")
        assert eps[0]["arc"]["phases"] == ["threat", "defense"]

    def test_episode_fields_absent_by_default(self):
        sc = self._sidecar()
        assert "episodes" not in sc
        assert "persona" not in sc["interview"]
        assert "codebook_file" not in sc
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_interview_render.py -q`
Expected: FAIL — `build_sidecar() got an unexpected keyword argument 'episodes'`.

- [ ] **Step 3: Implement**

In `skills/interview/scripts/render.py`, change `build_sidecar`'s signature and tail:

```python
def build_sidecar(
    media: str,
    duration: float,
    engines: dict,
    degradation: list[str],
    segments: list[dict],
    turns: list[dict],
    adjudications: list[dict],
    flags: list[dict],
    partial_failures: list[str],
    codebook_version: str,
    now: str | None = None,
    speaker_names: dict | None = None,
    episodes: list[dict] | None = None,
    persona: str | None = None,
    codebook_file: str | None = None,
) -> dict:
```

Docstring addition (append to the existing docstring):

```
    `episodes` (validated episode list, arcs included), `persona` (the
    confronter's per-video character), and `codebook_file` are recorded when
    provided so the artifact is self-describing; schema_version 1.1 adds them.
```

Change `"schema_version": "1.0",` to `"schema_version": "1.1",`, add `"codebook_version": codebook_version,` to the sidecar dict literal directly after the `"accuracy_claim": claim,` line (the spec wants codebook identity at top level, not only embedded per flag), and, before the `if speaker_names:` block, add:

```python
    if persona:
        sidecar["interview"]["persona"] = persona
    if episodes is not None:
        sidecar["episodes"] = copy.deepcopy(episodes)
    if codebook_file:
        sidecar["codebook_file"] = codebook_file
```

In `skills/interview/scripts/interview.py` `cmd_render`:

(a) Replace `codebook = _load(CODEBOOK_PATH)` with:

```python
    codebook_path = Path(args.codebook) if getattr(args, "codebook", None) else CODEBOOK_PATH
    codebook = _load(codebook_path)
```

(b) Before the `sidecar = build_sidecar(` call, add:

```python
    episodes = _load(work / "episodes.json") if (work / "episodes.json").exists() else None
```

(c) Extend the `build_sidecar(...)` call with:

```python
        speaker_names=names,
        episodes=episodes,
        persona=getattr(args, "persona", None),
        codebook_file=codebook_path.name if codebook_path != CODEBOOK_PATH else None,
```

(keep the existing `speaker_names=names` — do not duplicate it).

(d) In `main()`, extend the render parser:

```python
    p.add_argument("--codebook", metavar="PATH", help="alternate codebook file (default: shipped codebook.json)")
    p.add_argument("--persona", metavar="NAME", help="the confronter's per-video persona, recorded in the sidecar")
```

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q`
Expected: all pass (~190).

- [ ] **Step 5: Commit**

```bash
git add skills/interview/scripts/render.py skills/interview/scripts/interview.py tests/test_interview_render.py
git commit -m "feat: sidecar records episodes, persona, and codebook identity (schema 1.1)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: Episode-aware corpus aggregation

**Files:**
- Modify: `skills/interview/scripts/analyze.py` (append `summarize_corpus`)
- Modify: `skills/interview/scripts/interview.py` (`cmd_corpus_summary` refactor)
- Test: `tests/test_interview_episodes.py` (append)

> **Deliberate spec deviation:** the spec listed `--codebook` on corpus-summary, but aggregation turned out fully codebook-agnostic — it counts whatever the sidecars contain. An argument that is accepted and ignored would mislead, so corpus-summary takes no `--codebook`. Recorded here as the spec deviation.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_interview_episodes.py`:

```python
from analyze import summarize_corpus


def _sidecar(media, flags, episodes=None, persona=None):
    sc = {"interview": {"media": media}, "accuracy_claim": "dual-engine verified with logged adjudication",
          "flags": flags}
    if episodes is not None:
        sc["episodes"] = episodes
    if persona:
        sc["interview"]["persona"] = persona
    return sc


class TestSummarizeCorpus:
    def test_aggregates_markers_outcomes_and_crosstab(self):
        eps = [dict(ep("e01", "confrontation", 0, 100),
                    arc={"phases": ["threat", "defense"], "outcome": "refuses",
                         "turning_point": None})]
        flags = [{"id": "g0001", "marker_types": ["attribution_of_blame"],
                  "affect": "anger", "episode_id": "e01"}]
        out = summarize_corpus([
            _sidecar("a.webm", flags, eps, persona="Agent Greg Gorey"),
            _sidecar("b.webm", [{"id": "g0001", "marker_types": ["responsibility_acceptance"],
                                 "affect": "shame", "episode_id": "e01"}],
                     [dict(ep("e01", "confrontation", 0, 50),
                           arc={"phases": ["repair"], "outcome": "complies",
                                "turning_point": "off-camera"})],
                     persona="RoboNarc"),
        ])
        assert out["interviews"] == 2
        assert out["flags_by_marker"] == {"attribution_of_blame": 1,
                                          "responsibility_acceptance": 1}
        assert out["flags_by_affect"] == {"anger": 1, "shame": 1}
        assert out["episode_outcomes"] == {"refuses": 1, "complies": 1}
        assert out["marker_by_outcome"] == {"attribution_of_blame|refuses": 1,
                                            "responsibility_acceptance|complies": 1}
        assert out["personas"] == ["Agent Greg Gorey", "RoboNarc"]
        assert out["per_interview"][0]["episodes"] == 1

    def test_old_sidecars_without_episodes_still_aggregate(self):
        out = summarize_corpus([_sidecar("a.webm", [
            {"id": "g0001", "marker_types": ["emotional_display"], "emotion": "anger"}])])
        assert out["flags_by_marker"] == {"emotional_display": 1}
        assert out["flags_by_affect"] == {"anger": 1}   # falls back to `emotion`
        assert out["episode_outcomes"] == {}
        assert out["personas"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_interview_episodes.py -q`
Expected: FAIL — `ImportError: cannot import name 'summarize_corpus'`.

- [ ] **Step 3: Implement**

Append to `skills/interview/scripts/analyze.py`:

```python
def summarize_corpus(sidecars: list[dict]) -> dict:
    """Aggregate per-interview sidecars into corpus counts.

    Works on both sidecar generations: pre-episode sidecars contribute marker
    and affect counts only (`emotion` is read as the affect fallback); episode
    sidecars additionally feed outcome counts and the marker×outcome cross-tab
    (keys "marker|outcome"), which only counts flags inside episodes that carry
    an arc outcome.
    """
    from collections import Counter
    by_marker: Counter = Counter()
    by_affect: Counter = Counter()
    outcomes: Counter = Counter()
    cross: Counter = Counter()
    personas: list[str] = []
    rows: list[dict] = []
    for sc in sidecars:
        flags = sc.get("flags", [])
        episodes = sc.get("episodes", [])
        ep_outcome = {e["id"]: (e.get("arc") or {}).get("outcome")
                      for e in episodes if e.get("id")}
        for f in flags:
            for m in f.get("marker_types", []):
                by_marker[m] += 1
            affect = f.get("affect") or f.get("emotion")
            if affect:
                by_affect[affect] += 1
            outcome = ep_outcome.get(f.get("episode_id"))
            if outcome:
                for m in f.get("marker_types", []):
                    cross[f"{m}|{outcome}"] += 1
        for e in episodes:
            if e.get("type") == "confrontation":
                oc = (e.get("arc") or {}).get("outcome")
                if oc:
                    outcomes[oc] += 1
        persona = sc.get("interview", {}).get("persona")
        if persona:
            personas.append(persona)
        rows.append({"media": sc["interview"]["media"], "flags": len(flags),
                     "episodes": len(episodes), "claim": sc["accuracy_claim"]})
    return {"interviews": len(rows), "per_interview": rows,
            "flags_by_marker": dict(by_marker), "flags_by_affect": dict(by_affect),
            "episode_outcomes": dict(outcomes), "marker_by_outcome": dict(cross),
            "personas": personas}
```

Refactor `cmd_corpus_summary` in `interview.py` to delegate (keeping the skip-warning and the `flags_by_emotion` key for old consumers):

```python
def cmd_corpus_summary(args) -> int:
    folder = Path(args.folder)
    sidecar_paths = sorted(folder.glob("*_interview/sidecar.json"))
    sidecars = []
    for path in sidecar_paths:
        sc = _load(path)
        if not isinstance(sc, dict) or "interview" not in sc or "accuracy_claim" not in sc:
            print(f"WARNING: skipping non-interview sidecar: {path}", file=sys.stderr)
            continue
        sidecars.append(sc)
    summary = summarize_corpus(sidecars)
    # Back-compat alias: pre-episode consumers read flags_by_emotion.
    summary["flags_by_emotion"] = summary["flags_by_affect"]
    _save(folder / "corpus_summary.json", summary)
    print(json.dumps(summary, indent=2))
    return 0
```

Add `summarize_corpus` to the `analyze` import block in `interview.py`.

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add skills/interview/scripts/analyze.py skills/interview/scripts/interview.py tests/test_interview_episodes.py
git commit -m "feat: episode-aware corpus aggregation (outcomes, marker-by-outcome, personas)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: SKILL.md documentation + version 0.3.0

**Files:**
- Modify: `skills/interview/SKILL.md`
- Modify: `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`

- [ ] **Step 1: Document the episode step**

In `skills/interview/SKILL.md`: change the pipeline line in the intro to
`preflight → transcribe → adjudicate → finalize → panel → concordance → episodes → gravity → validate-flags → frames → visual evidence → render`, then insert after the Step 4 (diarization panel) section:

```markdown
## Step 4.5 — Episodes (only when the codebook declares them, or the recording has multiple interactions)

Read `WORK_DIR/diarized.json` and segment the recording into contiguous, non-overlapping **episodes** — one per interaction. Write `WORK_DIR/episodes.json` as a top-level array:

```json
[
  {"id": "e01", "type": "confrontation", "t_start": 0.0, "t_end": 324.0,
   "target_descriptor": "woman in garage SUV", "target_speech": true,
   "arc": {"phases": ["threat", "defense", "escalation", "exit"],
           "outcome": "refuses", "turning_point": null}},
  {"id": "e02", "type": "commendation", "t_start": 325.0, "t_end": 333.0}
]
```

- `type` ∈ `confrontation | commendation | bystander | to-camera`. The confronter's to-camera asides *inside* an ongoing confrontation belong to that confrontation; `to-camera` episodes are only stretches with no active target.
- Confrontations require `target_descriptor` and `target_speech` (false for silent targets — code outcome/performance only, never invent target speech).
- `arc` (confrontations, after the coding pass): `phases` ⊆ threat/defense/escalation/softening/flip/repair/exit; `outcome` ∈ complies/refuses/escalates/partial/n-a; `turning_point` is a turn id, `"off-camera"` (the turn happened before recording), or null.

Then validate — it stamps `episode_id` onto every turn:

```bash
python3 "${SKILL_DIR}/scripts/interview.py" validate-episodes --work WORK_DIR
```

Fix `episodes.json` per any printed error and re-run until it prints the episode table. For a plain single-interview recording with the default codebook this step is optional.
```

- [ ] **Step 2: Document `--codebook`, coding scope, and `--persona`**

In Step 5 (gravity pass), after the sentence about reading the codebook fresh, add:

```markdown
An alternate codebook may govern the run (e.g. `codebook_moral_identity.json`): pass `--codebook "<path>"` to BOTH `validate-flags` and `render`. The codebook's `coding_scope` declares which speaker roles to code (the default codebook codes only INTERVIEWEE turns; a codebook listing INTERVIEWER too means the confronter's speech is coded as well, each flag carrying `speaker_role`). When the codebook sets `enforce_attribution_gate`, any flag quoting a turn with concordance < 1.0 must carry `"attribution_uncertain": true`.
```

In Step 7 (render), after the speaker-names paragraph, add:

```markdown
`--persona "NAME"` records the confronter's per-video character (e.g. "Agent Greg Gorey", "RoboNarc") in the sidecar — metadata only, never a role label. `--codebook` must match the one used in validate-flags.
```

- [ ] **Step 3: Bump versions**

- `skills/interview/SKILL.md` frontmatter: `version: "0.3.0"`
- `.claude-plugin/plugin.json`: `"version": "0.3.0"`
- `.codex-plugin/plugin.json`: `"version": "0.3.0"`

- [ ] **Step 4: Full suite + JSON sanity**

Run: `python -m pytest -q`
Expected: all pass.

Run: `python -c "import json; [json.load(open(p)) for p in ('.claude-plugin/plugin.json', '.codex-plugin/plugin.json', 'skills/interview/scripts/codebook_moral_identity.json')]; print('json ok')"`
Expected: `json ok`

- [ ] **Step 5: Commit**

```bash
git add skills/interview/SKILL.md .claude-plugin/plugin.json .codex-plugin/plugin.json
git commit -m "docs: episode stage, --codebook/--persona, coding-scope rule; v0.3.0

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Post-plan verification (manual, not a task)

Re-run the pilot end-to-end with the new codebook to prove the pipeline finds the research questions mechanically — episodes.json + moral flags for "I Will Kiss You" exist as hand-coded prototypes from the dry run:

```bash
cd /Users/jeremiahwolf/Desktop/Projects/APPs/Gravitas/gravitas
SKILL=skills/interview/scripts/interview.py
MEDIA="/Users/jeremiahwolf/Desktop/Projects/APPs/Gravitas/test-media/cartnarcs/I Will Kiss You.webm"
CB=skills/interview/scripts/codebook_moral_identity.json
python3 $SKILL validate-episodes --work "${MEDIA%.*}_interview/work"   # after writing episodes.json
python3 $SKILL validate-flags --work "${MEDIA%.*}_interview/work" --codebook $CB
python3 $SKILL render "$MEDIA" --codebook $CB --interviewer "Confronter" --interviewee "Target" --persona "Agent Greg Gorey"
```

Expected: episode table prints; `OK: N flags valid against codebook 1.0.0 (codebook_moral_identity.json)`; sidecar carries `episodes`, `persona`, `codebook_file`, schema 1.1.
