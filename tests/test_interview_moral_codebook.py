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

    def test_flag_entirely_before_the_turn_is_rejected_outside_the_slop(self):
        # Sibling of the "flag after turn" case above: the other edge of the
        # +/-2s window. m0002 holds the quote at [5, 9]; a flag ending at 2.0 is
        # 3s early, past the slop.
        f = moral_flag(t_start=0.0, t_end=2.0)
        errs = validate_flags([f], MINI_MORAL, 100.0, turns=TURNS)
        assert any("no INTERVIEWEE turn near" in e for e in errs), errs

    def test_flag_just_past_the_turn_is_rejected_at_the_slop_edge(self):
        # Symmetric sibling of the "before" case: 3s AFTER m0002 ends, just past
        # the +2s slop. The pre-existing sibling sits 21s away, which a widened
        # window would still reject — this one pins the +2.0 itself.
        f = moral_flag(t_start=12.0, t_end=14.0)
        errs = validate_flags([f], MINI_MORAL, 100.0, turns=TURNS)
        assert any("no INTERVIEWEE turn near" in e for e in errs), errs

    def test_ties_go_to_the_first_candidate_not_the_last(self):
        # Two turns with identical spans both contain the quote, so overlap ties.
        # The docstring promises the FIRST match wins; a `>=` comparison would
        # silently switch to the last and read a different turn's concordance.
        turns = [
            {"id": "m0001", "start": 5.0, "end": 9.0, "text": "Yeah.",
             "label": "INTERVIEWEE", "concordance": 0.5},
            {"id": "m0002", "start": 5.0, "end": 9.0, "text": "Yeah.",
             "label": "INTERVIEWEE", "concordance": 1.0},
        ]
        cb = dict(MINI_MORAL, enforce_attribution_gate=True)
        errs = validate_flags([moral_flag(quote="Yeah.")], cb, 100.0, turns=turns)
        assert any("m0001" in e and "attribution_uncertain" in e for e in errs), errs
        assert not any("m0002" in e for e in errs), errs

    def test_flag_just_before_the_turn_but_inside_the_slop_still_resolves(self):
        # Pins the `- 2.0` itself, not merely the existence of a lower bound:
        # ending 1s before the turn starts is inside the slop and must resolve.
        f = moral_flag(t_start=1.0, t_end=4.0)
        assert validate_flags([f], MINI_MORAL, 100.0, turns=TURNS) == []

    def test_lone_candidate_inside_the_slop_but_not_overlapping_is_selected(self):
        # The only candidate turn ends before the flag begins, so its overlap is
        # NEGATIVE (-1.0) while still inside the slop. It must still be selected:
        # an overlap floor of 0.0 would drop it, report the quote as unlocatable,
        # and un-gate a low-concordance citation.
        turns = [{"id": "m0001", "start": 0.0, "end": 4.0,
                  "text": "Don't touch my property.", "label": "INTERVIEWEE",
                  "concordance": 0.5, "segment_indices": [0]}]
        cb = dict(MINI_MORAL, enforce_attribution_gate=True)
        errs = validate_flags([moral_flag(t_start=5.0, t_end=6.0)], cb, 100.0,
                              turns=turns)
        assert any("m0001" in e and "attribution_uncertain" in e for e in errs), errs
        assert not any("could not be located" in e for e in errs), errs

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

    def test_missing_speaker_role_under_coding_scope_is_reported(self):
        # coding_scope declared but speaker_role merely optional: without an
        # explicit check, a flag omitting speaker_role is caught by NEITHER the
        # scope check (which needs a role) nor the required-field check, so an
        # out-of-scope quote validates clean.
        cb = dict(MINI_MORAL, coding_scope=["INTERVIEWEE"],
                  flag_schema={"required": ["id", "marker_types", "quote", "t_start",
                                            "t_end", "salience"]})
        f = moral_flag(quote="Why is this cart here?", t_start=0.0, t_end=4.0)
        f.pop("speaker_role")
        errs = validate_flags([f], cb, 100.0, turns=TURNS)
        assert any("no speaker_role" in e for e in errs), errs

    def test_missing_speaker_role_is_not_double_reported_when_required(self):
        # The schema already emits "missing required field" on this path; the
        # coding_scope check must not pile a second message on top of it.
        f = moral_flag()
        f.pop("speaker_role")
        errs = validate_flags([f], MINI_MORAL, 100.0, turns=TURNS)
        role_errs = [e for e in errs if "speaker_role" in e]
        assert role_errs == ["g0001: missing required field 'speaker_role'"], errs

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


class TestAttributionGate:
    LOW_TURNS = [
        {"id": "m0001", "start": 0.0, "end": 4.0, "text": "Or that 50 people over there?",
         "label": "INTERVIEWEE", "concordance": 0.6667, "segment_indices": [0]},
        {"id": "m0002", "start": 5.0, "end": 9.0, "text": "Don't touch my property.",
         "label": "INTERVIEWEE", "concordance": 1.0, "segment_indices": [1]},
    ]
    GATED = dict(MINI_MORAL, enforce_attribution_gate=True)

    # A gate-only codebook: no coding_scope, no speaker_role in required, so the
    # gate is exercised without the speaker_role check firing for its own reasons.
    GATED_NO_ROLE = {
        "codebook_version": "1.0.0",
        "affect_field": "affect",
        "affect_vocabulary": ["anger", "shame", "neutral"],
        "enforce_attribution_gate": True,
        "markers": MINI_MORAL["markers"],
        "flag_schema": {"required": ["id", "marker_types", "quote", "t_start",
                                     "t_end", "salience"],
                        "optional": ["affect", "attribution_uncertain"]},
    }

    @staticmethod
    def _no_role(**over):
        f = moral_flag(**over)
        f.pop("speaker_role", None)
        return f

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

    def test_unclear_label_triggers_gate_even_at_full_concordance(self):
        turns = [{"id": "m0001", "start": 5.0, "end": 9.0,
                  "text": "Don't touch my property.", "label": "UNCLEAR",
                  "concordance": 1.0, "segment_indices": [0]}]
        errs = validate_flags([self._no_role()], self.GATED_NO_ROLE, 100.0, turns=turns)
        # one message must carry both: the demand AND the real trigger, so the
        # gate cannot report "concordance 1.0" as the reason it fired
        assert any("UNCLEAR" in e and "attribution_uncertain" in e for e in errs), errs

    def test_gate_without_turns_raises_rather_than_silently_passing(self):
        f = moral_flag(quote="Or that 50 people over there?", t_start=0.0, t_end=4.0)
        with pytest.raises(ValueError, match="turn-level validation"):
            validate_flags([f], self.GATED, 100.0, turns=None)

    def test_unlabeled_turns_raise(self):
        bare = [{"id": "m0001", "start": 0.0, "end": 4.0,
                 "text": "Or that 50 people over there?"}]
        with pytest.raises(ValueError, match="label/concordance"):
            validate_flags([moral_flag()], self.GATED, 100.0, turns=bare)

    def test_unlocatable_quote_is_a_finding_not_a_pass(self):
        f = self._no_role(quote="words in no turn")
        errs = validate_flags([f], self.GATED_NO_ROLE, 100.0, turns=self.LOW_TURNS)
        assert any("could not be located" in e for e in errs)

    @pytest.mark.parametrize("truthy", ["true", "TRUE", 1, "yes", [0]])
    def test_truthy_non_true_does_not_satisfy_the_gate(self, truthy):
        # Flags are LLM-authored JSON. A model emitting "true" or 1 instead of a
        # JSON boolean is a realistic failure mode, and a truthiness test would
        # let it silently clear the gate on a 0.6667-concordance turn — corrupt
        # attribution entering the research record marked as validated.
        f = moral_flag(quote="Or that 50 people over there?", t_start=0.0, t_end=4.0,
                       attribution_uncertain=truthy)
        errs = validate_flags([f], self.GATED, 100.0, turns=self.LOW_TURNS)
        assert any("attribution_uncertain" in e for e in errs), (truthy, errs)

    def test_gate_applies_to_every_flag_not_just_the_first(self):
        # Nothing else in the suite runs the gate over more than one flag, so a
        # refactor that hoisted it out of the per-flag loop, or broke after the
        # first finding, would ship undetected.
        clean = moral_flag(id="g0001")                      # cites m0002 @ 1.0
        dirty = moral_flag(id="g0002", quote="Or that 50 people over there?",
                           t_start=0.0, t_end=4.0)          # cites m0001 @ 0.6667
        errs = validate_flags([clean, dirty], self.GATED, 100.0, turns=self.LOW_TURNS)
        assert any("g0002" in e and "attribution_uncertain" in e for e in errs), errs
        assert not any(e.startswith("g0001") for e in errs), errs

    def test_concordance_boundary_exactly_one_does_not_trip_the_gate(self):
        # pins the `< 1.0` boundary explicitly rather than incidentally
        turns = [{"id": "m0001", "start": 5.0, "end": 9.0,
                  "text": "Don't touch my property.", "label": "INTERVIEWEE",
                  "concordance": 1.0, "segment_indices": [0]}]
        assert validate_flags([self._no_role()], self.GATED_NO_ROLE, 100.0, turns=turns) == []
