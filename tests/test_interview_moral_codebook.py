"""Moral-identity codebook: structural invariants + codebook-driven validation."""
from __future__ import annotations

import json
from pathlib import Path

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
