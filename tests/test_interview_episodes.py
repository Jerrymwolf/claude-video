"""Episode segmentation: validation, turn/flag assignment."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import analyze
from analyze import (assign_episode_ids, assign_flag_episodes,
                     merge_labeled_turns, validate_episodes)

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

    def test_gap_between_episodes_is_allowed_but_a_turn_inside_it_is_not(self):
        # 120-130 holds no turns — silent B-roll; coverage is over turns, not
        # time. The gap is only legal while it stays empty.
        assert validate_episodes(EPISODES, TURNS) == []
        errs = validate_episodes(EPISODES, TURNS + [turn("t0005", 125.0, 126.0)])
        assert any("t0005" in e and "no episode" in e for e in errs)

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
        # turns=[] isolates the span check from turn-coverage noise; the error
        # is reported with TURNS too, this is presentation, not necessity
        errs = validate_episodes([ep("e01", "to-camera", 200.0, 100.0)], [])
        assert any("t_start > t_end" in e for e in errs)

    def test_out_of_order_rejected_and_distinguished_from_overlap(self):
        # B is entirely before A — not an overlap, and saying "overlaps" sends
        # the researcher hunting for a collision that does not exist. The
        # sortedness this rejects is what makes the positional "last episode"
        # check in _containing_episode mean "temporally last".
        bad = [ep("e01", "to-camera", 130.0, 200.0), ep("e02", "to-camera", 0.0, 50.0)]
        errs = validate_episodes(bad, [])
        assert any("out of order" in e for e in errs)
        assert not any("overlaps" in e for e in errs)

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

    def test_non_dict_arc_rejected(self):
        e = ep("e01", "confrontation", 0.0, 200.0, arc="threat")
        errs = validate_episodes([e], TURNS)
        assert any("arc must be an object" in x for x in errs)

    def test_arc_phases_as_bare_string_rejected_not_iterated(self):
        # "threat" as a string would iterate to six characters, reporting six
        # bogus "unknown arc phase" errors for one real mistake
        e = ep("e01", "confrontation", 0.0, 200.0, arc={"phases": "threat"})
        errs = validate_episodes([e], TURNS)
        assert any("arc.phases must be a list" in x for x in errs)
        assert not any("unknown arc phase" in x for x in errs)

    def test_string_timestamps_reported_explicitly(self):
        # episodes.json is authored from a video clock — "0:00" is a likely slip
        e = {"id": "e01", "type": "to-camera", "t_start": "0:00", "t_end": "3:20"}
        errs = validate_episodes([e], [])
        assert any("t_start must be a number" in x and "0:00" in x for x in errs)
        assert any("t_end must be a number" in x for x in errs)

    def test_boolean_timestamp_rejected(self):
        # bool subclasses int, so `false` would otherwise be read as 0.0
        e = {"id": "e01", "type": "to-camera", "t_start": False, "t_end": 100.0}
        errs = validate_episodes([e], [])
        assert any("t_start must be a number" in x for x in errs)

    def test_coverage_errors_are_capped_not_one_per_turn(self):
        # one mistyped episode timestamp orphans every turn; hundreds of
        # identical lines bury the cause under its effects
        strays = [turn(f"t{i:04d}", 500.0 + i, 501.0 + i) for i in range(8)]
        errs = [e for e in validate_episodes(EPISODES, strays) if "no episode" in e]
        assert len(errs) == 1
        assert errs[0].startswith("8 turn(s) fall in no episode")
        assert "+3 more" in errs[0]

    def test_turn_straddling_a_boundary_is_reported(self):
        # start 95 / end 140 crosses the e01|e02 boundary at 100: the boundary
        # is drawn through a turn, and only the author can still fix it
        errs = validate_episodes(EPISODES, [turn("t0001", 95.0, 140.0)])
        assert any("t0001" in e and "straddle" in e for e in errs)


class TestCodebookDrivenRequiredFields:
    """`episode_schema.required` must actually drive the required-field check.
    A second copy of the list in Python is the same silent twin that
    _episode_enums exists to prevent."""

    def test_shipped_codebook_required_matches_module_fallbacks(self):
        assert tuple(MORAL["episode_schema"]["required"]) == analyze.EPISODE_REQUIRED
        assert (tuple(MORAL["episode_schema"]["confrontation_required"])
                == analyze.EPISODE_CONFRONTATION_REQUIRED)

    def test_codebook_declared_extra_required_field_is_enforced(self):
        cb = {"episode_schema": {"required": ["id", "type", "t_start", "t_end", "summary"]}}
        errs = validate_episodes([ep("e01", "to-camera", 0.0, 200.0)], TURNS, codebook=cb)
        assert any("missing required field 'summary'" in e for e in errs)

    def test_codebook_declared_extra_confrontation_field_is_enforced(self):
        cb = {"episode_schema": {"confrontation_required": ["target_descriptor",
                                                            "target_speech",
                                                            "target_role"]}}
        errs = validate_episodes([ep("e01", "confrontation", 0.0, 200.0)], TURNS, codebook=cb)
        assert any("confrontation requires a target_role" in e for e in errs)

    def test_target_speech_keeps_its_bool_rule_when_codebook_declares_it(self):
        cb = {"episode_schema": {"confrontation_required": ["target_speech"]}}
        e = ep("e01", "confrontation", 0.0, 200.0, target_speech="yes")
        errs = validate_episodes([e], TURNS, codebook=cb)
        assert any("target_speech must be true/false" in x for x in errs)


class TestMergeBarrier:
    """merge_labeled_turns must not fuse same-label units across an episode
    boundary — that re-creates the fused-target bug episodes exist to fix."""

    def unit(self, uid, t0, t1, text, label="INTERVIEWEE", **over):
        u = {"id": uid, "start": t0, "end": t1, "text": text, "label": label,
             "concordance": 1.0, "segment_indices": [0]}
        u.update(over)
        return u

    def test_same_label_units_in_different_episodes_do_not_merge(self):
        units = [self.unit("u1", 0.0, 5.0, "You cannot park here", episode_id="e01"),
                 self.unit("u2", 105.0, 110.0, "You cannot park here either",
                           episode_id="e02")]
        merged = merge_labeled_turns(units)
        assert len(merged) == 2
        assert [m["episode_id"] for m in merged] == ["e01", "e02"]

    def test_same_label_units_in_the_same_episode_still_merge(self):
        units = [self.unit("u1", 0.0, 5.0, "First", episode_id="e01"),
                 self.unit("u2", 5.0, 9.0, "Second", episode_id="e01")]
        merged = merge_labeled_turns(units)
        assert len(merged) == 1
        assert merged[0]["text"] == "First Second"
        assert merged[0]["episode_id"] == "e01"

    def test_barrier_is_inert_without_episode_id(self):
        # every pre-episode caller (cmd_validate_flags, cmd_render) passes
        # units with no episode_id — behavior must be byte-identical
        units = [self.unit("u1", 0.0, 5.0, "First"), self.unit("u2", 5.0, 9.0, "Second")]
        merged = merge_labeled_turns(units)
        assert len(merged) == 1
        assert merged[0]["text"] == "First Second"
        assert "episode_id" not in merged[0]

    def test_merged_turn_drops_episode_id_when_members_disagree(self):
        # an unannotated member makes the claim unprovable; one member's id
        # must not speak for units that never carried one
        units = [self.unit("u1", 0.0, 5.0, "First", episode_id="e01"),
                 self.unit("u2", 5.0, 9.0, "Second")]
        merged = merge_labeled_turns(units)
        assert len(merged) == 1
        assert "episode_id" not in merged[0]

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
        # the list is mutated before the caller sees the errors: a caller that
        # persists on the error path must not write a record where a missing
        # key is indistinguishable from an unassigned one
        assert flags[1]["episode_id"] is None

    def test_flag_straddling_a_boundary_is_reported(self):
        flags = [{"id": "g0003", "t_start": 99.0, "t_end": 105.0}]
        errs = assign_flag_episodes(flags, EPISODES)
        assert flags[0]["episode_id"] == "e01"
        assert any("g0003" in e and "straddles" in e for e in errs)

    def test_non_numeric_flag_timestamp_errors_instead_of_raising(self):
        # the docstring promises errors, not exceptions
        flags = [{"id": "g0004", "t_start": "1:39", "t_end": "1:45"}]
        errs = assign_flag_episodes(flags, EPISODES)
        assert any("g0004" in e and "t_start must be a number" in e for e in errs)
        assert flags[0]["episode_id"] is None


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
