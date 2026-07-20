"""Episode segmentation: validation, turn/flag assignment."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import analyze
from analyze import (assign_episode_ids, assign_flag_episodes, validate_episodes)

MORAL = json.loads((Path(__file__).resolve().parent.parent / "skills" / "interview"
                    / "scripts" / "codebook_moral_identity.json").read_text(encoding="utf-8"))


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
        # 120-130 holds no turns — silent B-roll; coverage is over turns, not time
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

    def test_inverted_span_rejected(self):
        # turns=[] isolates the span check: an inverted span still "contains"
        # its own t_end, so coverage would otherwise mask the error
        errs = validate_episodes([ep("e01", "to-camera", 200.0, 100.0)], [])
        assert any("t_start > t_end" in e for e in errs)

    def test_missing_required_field_rejected(self):
        e = ep("e01", "to-camera", 0.0, 100.0)
        del e["type"]
        errs = validate_episodes([e], [])
        assert any("missing required field 'type'" in x for x in errs)

    def test_non_string_turning_point_rejected(self):
        e = ep("e01", "confrontation", 0.0, 200.0,
               arc={"phases": ["threat"], "outcome": "complies", "turning_point": 42})
        errs = validate_episodes([e], TURNS)
        assert any("turning_point must be a turn id" in x for x in errs)

    def test_empty_episode_list_rejected(self):
        assert validate_episodes([], TURNS) == ["episodes.json must be a non-empty array"]

    def test_arc_off_camera_turning_point_allowed(self):
        e = ep("e01", "confrontation", 0.0, 200.0,
               arc={"phases": ["repair", "exit"], "outcome": "complies",
                    "turning_point": "off-camera"})
        assert validate_episodes([e], TURNS) == []


class TestAssignment:
    def test_turns_get_episode_ids(self):
        turns = assign_episode_ids([dict(t) for t in TURNS], EPISODES)
        assert [t["episode_id"] for t in turns] == ["e01", "e01", "e02", "e03"]

    def test_boundary_turn_goes_to_the_later_episode(self):
        # t_start exactly on a shared boundary belongs to the LATER episode
        turns = assign_episode_ids([turn("t0001", 100.0, 104.0)], EPISODES)
        assert turns[0]["episode_id"] == "e02"

    def test_final_episode_end_is_inclusive(self):
        # the last turn must never be orphaned by a half-open interval
        turns = assign_episode_ids([turn("t0009", 200.0, 201.0)], EPISODES)
        assert turns[0]["episode_id"] == "e03"

    def test_orphan_turn_raises(self):
        # turns are assigned post-validation, so an orphan here is a bug, not a
        # coder error — it must fail loudly rather than silently drop episode_id
        with pytest.raises(ValueError):
            assign_episode_ids([turn("t0009", 125.0, 126.0)], EPISODES)

    def test_flags_get_episode_ids_and_orphans_error(self):
        flags = [{"id": "g0001", "t_start": 50.0, "t_end": 52.0},
                 {"id": "g0002", "t_start": 125.0, "t_end": 126.0}]
        errs = assign_flag_episodes(flags, EPISODES)
        assert flags[0]["episode_id"] == "e01"
        assert any("g0002" in e and "outside every episode" in e for e in errs)


class TestCodebookDrivenEnums:
    """The codebook is the source of truth for episode/arc enums; the module
    constants are only the no-codebook fallback. These lock both halves so the
    two can never silently diverge."""

    def test_shipped_codebook_enums_match_module_fallbacks(self):
        assert set(MORAL["episode_schema"]["types"]) == analyze.EPISODE_TYPES
        assert set(MORAL["arc_schema"]["phases"]) == analyze.ARC_PHASES
        assert set(MORAL["arc_schema"]["outcomes"]) == analyze.ARC_OUTCOMES

    def test_codebook_enums_override_fallbacks(self):
        cb = {"episode_schema": {"types": ["confrontation"]},
              "arc_schema": {"phases": ["threat"], "outcomes": ["complies"]}}
        # 'commendation' is a module-constant type but NOT in this codebook
        errs = validate_episodes([ep("e01", "commendation", 0.0, 200.0)], TURNS, codebook=cb)
        assert any("unknown type 'commendation'" in e for e in errs)

    def test_no_codebook_falls_back_to_module_constants(self):
        assert validate_episodes(EPISODES, TURNS, codebook=None) == []
