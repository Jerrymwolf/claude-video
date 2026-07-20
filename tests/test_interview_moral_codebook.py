"""Moral-identity codebook: structural invariants + codebook-driven validation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from analyze import validate_flags

MORAL_PATH = (Path(__file__).resolve().parent.parent / "skills" / "interview"
              / "scripts" / "codebook_moral_identity.json")

CODEBOOK = json.loads(MORAL_PATH.read_text(encoding="utf-8"))

BANDURA = {
    "moral_justification", "euphemistic_labeling", "advantageous_comparison",
    "displacement_of_responsibility", "diffusion_of_responsibility",
    "distortion_of_consequences", "dehumanization", "attribution_of_blame",
}

AFFECT_VOCABULARY = {
    "anger", "contempt", "frustration", "anxiety", "fear", "shame",
    "embarrassment", "sadness", "amusement", "pride", "relief", "neutral",
}


class TestMoralCodebookInvariants:
    def test_version_and_declared_fields(self):
        cb = CODEBOOK
        assert cb["codebook_version"] == "1.0.0"
        assert cb["coding_scope"] == ["INTERVIEWEE", "INTERVIEWER"]
        assert cb["affect_field"] == "affect"
        assert cb["enforce_attribution_gate"] is True

    def test_marker_families_complete(self):
        cb = CODEBOOK
        ids = {m["id"] for m in cb["markers"]}
        assert BANDURA <= ids
        assert {"responsibility_acceptance", "aggression_threat"} <= ids
        assert {"identity_threat", "identity_defense", "identity_repair",
                "identity_bestowal"} <= ids
        assert {"audience_address", "camera_awareness"} <= ids
        # Both counts, so a duplicated marker id fails instead of collapsing
        # invisibly into the set.
        assert len(cb["markers"]) == 16
        assert len(ids) == 16

    def test_defense_and_identity_markers_require_affect(self):
        cb = CODEBOOK
        req = {m["id"] for m in cb["markers"] if m.get("requires_affect")}
        assert BANDURA <= req
        assert {"responsibility_acceptance", "aggression_threat",
                "identity_threat", "identity_defense", "identity_repair",
                "identity_bestowal"} <= req
        assert "audience_address" not in req and "camera_awareness" not in req

    def test_affect_vocabulary_includes_neutral(self):
        cb = CODEBOOK
        vocab = set(cb["affect_vocabulary"])
        assert "neutral" in vocab
        assert {"anger", "contempt", "shame", "pride", "amusement"} <= vocab
        # Task 3 consumes this as a closed enum: pin the exact set so a silent
        # deletion cannot invalidate previously-valid flags.
        assert vocab == AFFECT_VOCABULARY
        assert len(cb["affect_vocabulary"]) == len(AFFECT_VOCABULARY)

    def test_affect_definitions_match_vocabulary(self):
        cb = CODEBOOK
        assert set(cb["affect_definitions"]) == set(cb["affect_vocabulary"])
        for term, gloss in cb["affect_definitions"].items():
            assert gloss.strip(), term

    def test_flag_schema_requires_speaker_role(self):
        cb = CODEBOOK
        assert "speaker_role" in cb["flag_schema"]["required"]
        assert "affect" in cb["flag_schema"]["optional"]
        assert "attribution_uncertain" in cb["flag_schema"]["optional"]
        assert "episode_id" in cb["flag_schema"]["optional"]

    def test_arc_enums_allow_off_camera_turning_point(self):
        cb = CODEBOOK
        arc = cb["arc_schema"]
        assert set(arc["outcomes"]) == {"complies", "refuses", "escalates", "partial", "n/a"}
        # Special values only — a real turning_point is a transcript turn id, so
        # this list must not carry a prose placeholder among legal values.
        assert arc["turning_point_special_values"] == ["off-camera", None]
        assert {"threat", "defense", "escalation", "softening", "flip",
                "repair", "exit"} == set(arc["phases"])
        assert any("turning_point:" in note for note in arc["notes"])

    def test_every_marker_has_definition_and_indicators(self):
        for m in CODEBOOK["markers"]:
            assert m["name"].strip(), m["id"]
            assert m["definition"].strip(), m["id"]
            assert m["indicators"], m["id"]
            # Must be an explicit bool: an omitted key reads as falsey through
            # .get() in both this suite and validate_flags, silently dropping
            # the affect requirement.
            assert "requires_affect" in m, m["id"]
            assert isinstance(m["requires_affect"], bool), m["id"]


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

    def test_quote_outside_the_timestamp_window_is_rejected(self):
        f = moral_flag(t_start=30.0, t_end=34.0)   # text matches m0002; timestamps 21s away
        errs = validate_flags([f], MINI_MORAL, 100.0, turns=TURNS)
        assert any("no INTERVIEWEE turn near" in e for e in errs)

    def test_untimed_flag_falls_back_to_text_only_turn_match(self):
        # No timestamps to anchor with: the text-only fallback must still resolve
        # the turn rather than treating every turn as out-of-window.
        f = moral_flag()
        del f["t_start"], f["t_end"]
        errs = validate_flags([f], MINI_MORAL, 100.0, turns=TURNS)
        assert not any("turn near" in e for e in errs)
        assert all("missing required field" in e for e in errs), errs

    def test_turn_with_maximum_overlap_wins_not_the_first_text_match(self):
        # Short quotes recur. m0001 is inside the +/-2s slop but barely; m0002 is
        # the real home. Picking the first match would read m0001's concordance
        # and let a low-concordance citation through ungated.
        turns = [
            {"id": "m0001", "start": 0.0, "end": 4.0, "text": "Yeah.",
             "label": "INTERVIEWEE", "concordance": 1.0},
            {"id": "m0002", "start": 5.0, "end": 9.0, "text": "Yeah.",
             "label": "INTERVIEWEE", "concordance": 0.5},
        ]
        cb = dict(MINI_MORAL, enforce_attribution_gate=True)
        errs = validate_flags([moral_flag(quote="Yeah.")], cb, 100.0, turns=turns)
        assert any("m0002" in e and "attribution_uncertain" in e for e in errs), errs
        assert not any("m0001" in e for e in errs), errs

    def test_gate_reuses_the_turn_the_speaker_role_check_resolved(self):
        # An UNCLEAR turn overlaps the flag more than the INTERVIEWEE turn the
        # flag actually cites. A second, unscoped lookup would resolve UNCLEAR
        # and demand attribution_uncertain on a correctly-attributed flag.
        turns = [
            {"id": "m0001", "start": 6.0, "end": 10.0, "text": "Yeah.",
             "label": "UNCLEAR", "concordance": 1.0},
            {"id": "m0002", "start": 6.0, "end": 9.0, "text": "Yeah.",
             "label": "INTERVIEWEE", "concordance": 1.0},
        ]
        cb = dict(MINI_MORAL, enforce_attribution_gate=True)
        f = moral_flag(quote="Yeah.", t_start=6.0, t_end=10.0)
        assert validate_flags([f], cb, 100.0, turns=turns) == []

    def test_gate_fires_on_unclear_label_at_full_concordance(self):
        turns = [dict(TURNS[0]), dict(TURNS[1], label="UNCLEAR", concordance=1.0)]
        cb = dict(MINI_MORAL, enforce_attribution_gate=True)
        errs = validate_flags([moral_flag()], cb, 100.0, turns=turns)
        assert any("UNCLEAR" in e and "attribution_uncertain" in e for e in errs), errs
        cleared = validate_flags([moral_flag(attribution_uncertain=True)], cb, 100.0,
                                 turns=turns)
        assert not any("attribution_uncertain" in e for e in cleared), cleared

    def test_gate_names_concordance_when_that_is_the_trigger(self):
        turns = [dict(TURNS[0]), dict(TURNS[1], concordance=0.66)]
        cb = dict(MINI_MORAL, enforce_attribution_gate=True)
        errs = validate_flags([moral_flag()], cb, 100.0, turns=turns)
        assert any("concordance 0.66" in e for e in errs), errs
        assert not any("UNCLEAR" in e for e in errs), errs

    def test_gate_rejects_a_quote_that_matches_no_turn(self):
        cb = dict(MINI_MORAL, enforce_attribution_gate=True)
        errs = validate_flags([moral_flag(quote="Words spoken nowhere.")], cb, 100.0,
                              turns=TURNS)
        assert any("could not be located in any turn" in e for e in errs), errs

    def test_turn_level_codebook_without_turns_raises(self):
        with pytest.raises(ValueError, match="turn-level validation"):
            validate_flags([moral_flag()], MINI_MORAL, 100.0)

    def test_unlabeled_turns_raise(self):
        bare = [{"id": "m0001", "start": 0.0, "end": 4.0, "text": "Why is this cart here?"}]
        with pytest.raises(ValueError, match="missing label/concordance"):
            validate_flags([moral_flag()], MINI_MORAL, 100.0, turns=bare)

    def test_coding_scope_applies_without_speaker_role_in_required(self):
        cb = dict(MINI_MORAL, coding_scope=["INTERVIEWEE"],
                  flag_schema={"required": ["id", "marker_types", "quote", "t_start",
                                            "t_end", "salience"]})
        f = moral_flag(speaker_role="INTERVIEWER", quote="Why is this cart here?",
                       t_start=0.0, t_end=4.0)
        errs = validate_flags([f], cb, 100.0, turns=TURNS)
        assert any("not in coding scope" in e for e in errs), errs

    def test_coding_scope_defaults_to_interviewee_only(self):
        cb = {k: v for k, v in MINI_MORAL.items() if k != "coding_scope"}
        assert validate_flags([moral_flag()], cb, 100.0, turns=TURNS) == []
        f = moral_flag(speaker_role="INTERVIEWER", quote="Why is this cart here?",
                       t_start=0.0, t_end=4.0)
        errs = validate_flags([f], cb, 100.0, turns=TURNS)
        assert any("not in coding scope ['INTERVIEWEE']" in e for e in errs), errs

    def test_affect_vocabulary_takes_precedence_over_emotions(self):
        cb = {"codebook_version": "1.0.0",
              "affect_vocabulary": ["calm"], "emotions": ["anger"],
              "markers": [{"id": "m1", "requires_emotion": True}],
              "flag_schema": {"required": ["id", "marker_types", "quote", "t_start",
                                           "t_end", "salience"]}}
        base = {"id": "g0001", "marker_types": ["m1"], "quote": "Don't touch my property.",
                "t_start": 5.0, "t_end": 9.0, "salience": 3}
        assert validate_flags([dict(base, emotion="calm")], cb, 100.0) == []
        errs = validate_flags([dict(base, emotion="anger")], cb, 100.0)
        assert any("'anger' not in codebook vocabulary" in e for e in errs), errs

    def test_declared_affect_field_does_not_fall_back_to_stale_emotions(self):
        # A moral codebook copy-edited from the narrative one keeps an `emotions`
        # key by accident; it must not become the vocabulary for `affect`.
        cb = {k: v for k, v in MINI_MORAL.items() if k != "affect_vocabulary"}
        cb["emotions"] = ["anger"]
        errs = validate_flags([moral_flag(affect="anger")], cb, 100.0, turns=TURNS)
        assert any("'anger' not in codebook vocabulary" in e for e in errs), errs

    def test_affect_error_names_the_offending_marker(self):
        f = moral_flag(affect=None,
                       marker_types=["audience_address", "attribution_of_blame"])
        errs = validate_flags([f], MINI_MORAL, 100.0, turns=TURNS)
        assert any("marker 'attribution_of_blame' requires an affect" in e for e in errs), errs

    def test_non_string_quote_is_reported_not_crashed(self):
        errs = validate_flags([moral_flag(quote=123)], MINI_MORAL, 100.0, turns=TURNS)
        assert any("quote must be a string" in e for e in errs), errs
