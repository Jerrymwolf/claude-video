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
