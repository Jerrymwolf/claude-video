"""Turn grouping, panel concordance, gravity-flag validation, frame bursts."""
from __future__ import annotations

import json
from pathlib import Path

from analyze import build_turns, burst_timestamps, compute_concordance, validate_flags

CODEBOOK = json.loads(
    (Path(__file__).resolve().parent.parent
     / "skills" / "interview" / "scripts" / "codebook.json").read_text()
)


def seg(start, end, text):
    return {"start": start, "end": end, "text": text}


class TestBuildTurns:
    def test_groups_contiguous_segments_and_splits_on_gap(self):
        segments = [
            seg(0.0, 2.0, "So tell me about"),
            seg(2.3, 4.0, "a time you led."),      # 0.3s gap → same turn
            seg(6.0, 9.0, "Well, it was 2019."),   # 2.0s gap → new turn
        ]
        turns = build_turns(segments, gap_seconds=1.0)
        assert [t["id"] for t in turns] == ["t0001", "t0002"]
        assert turns[0]["text"] == "So tell me about a time you led."
        assert turns[0]["start"] == 0.0 and turns[0]["end"] == 4.0
        assert turns[1]["text"] == "Well, it was 2019."
        assert turns[0]["segment_indices"] == [0, 1]
        assert turns[1]["segment_indices"] == [2]

    def test_non_monotonic_segments_are_ordered_not_corrupted(self):
        segments = [
            seg(10.0, 12.0, "later words"),
            seg(0.0, 2.0, "earlier words"),
            seg(12.5, 13.0, "tail"),
        ]
        turns = build_turns(segments, gap_seconds=1.0)
        assert [t["id"] for t in turns] == ["t0001", "t0002"]
        assert turns[0]["text"] == "earlier words"
        assert turns[1]["text"] == "later words tail"
        assert all(t["end"] >= t["start"] for t in turns)
        # segment_indices refer to ORIGINAL list positions
        assert turns[0]["segment_indices"] == [1]
        assert turns[1]["segment_indices"] == [0, 2]

    def test_overlapping_segments_never_shrink_turn_end(self):
        segments = [
            seg(0.0, 5.0, "a"),
            seg(4.0, 4.5, "b"),    # overlap must not drag end back to 4.5
            seg(5.2, 6.0, "c"),    # still within gap 1.0 of end=5.0
        ]
        turns = build_turns(segments, gap_seconds=1.0)
        assert len(turns) == 1
        assert turns[0]["end"] == 6.0
        assert turns[0]["text"] == "a b c"


class TestComputeConcordance:
    def _turns(self):
        return [{"id": "t0001", "start": 0.0, "end": 4.0, "text": "x"},
                {"id": "t0002", "start": 6.0, "end": 9.0, "text": "y"}]

    def test_unanimous_panel_yields_full_concordance(self):
        panels = [{"t0001": "INTERVIEWER", "t0002": "INTERVIEWEE"}] * 3
        result = compute_concordance(self._turns(), panels)
        assert result["t0001"] == {"label": "INTERVIEWER", "concordance": 1.0, "votes": 3, "invalid": 0}
        assert result["t0002"]["label"] == "INTERVIEWEE"

    def test_two_of_three_majority_meets_threshold(self):
        panels = [
            {"t0001": "INTERVIEWER", "t0002": "INTERVIEWEE"},
            {"t0001": "INTERVIEWER", "t0002": "INTERVIEWEE"},
            {"t0001": "INTERVIEWEE", "t0002": "INTERVIEWEE"},
        ]
        result = compute_concordance(self._turns(), panels)
        assert result["t0001"]["label"] == "INTERVIEWER"
        assert round(result["t0001"]["concordance"], 2) == 0.67

    def test_three_way_split_falls_through_to_unclear(self):
        panels = [{"t0001": "INTERVIEWER"}, {"t0001": "INTERVIEWEE"}, {"t0001": "OTHER"}]
        result = compute_concordance(self._turns()[:1], panels)
        assert result["t0001"]["label"] == "UNCLEAR"

    def test_fewer_than_two_votes_is_unclear(self):
        panels = [{"t0001": "INTERVIEWER"}, {}, {}]
        result = compute_concordance(self._turns()[:1], panels)
        assert result["t0001"]["label"] == "UNCLEAR"
        assert result["t0001"]["votes"] == 1

    def test_invalid_labels_are_discarded_not_counted(self):
        panels = [{"t0001": "NARRATOR"}, {"t0001": "INTERVIEWER"}, {"t0001": "INTERVIEWER"}]
        result = compute_concordance(self._turns()[:1], panels)
        assert result["t0001"]["label"] == "INTERVIEWER"
        assert result["t0001"]["votes"] == 2
        assert result["t0001"]["invalid"] == 1

    def test_tie_vote_is_unclear(self):
        panels = [
            {"t0001": "INTERVIEWER"},
            {"t0001": "INTERVIEWER"},
            {"t0001": "INTERVIEWEE"},
            {"t0001": "INTERVIEWEE"},
        ]
        result = compute_concordance(self._turns()[:1], panels)
        assert result["t0001"]["label"] == "UNCLEAR"


class TestValidateFlags:
    def _flag(self, **overrides):
        flag = {
            "id": "g0001",
            "marker_types": ["emotional_display"],
            "emotion": "anger",
            "quote": "I was furious",
            "t_start": 62.0,
            "t_end": 65.5,
            "salience": 4,
        }
        flag.update(overrides)
        return flag

    def test_valid_flag_passes(self):
        assert validate_flags([self._flag()], CODEBOOK, duration=600.0) == []

    def test_unknown_marker_rejected(self):
        errors = validate_flags([self._flag(marker_types=["vibes"])], CODEBOOK, 600.0)
        assert any("vibes" in e for e in errors)

    def test_emotional_display_requires_valid_emotion(self):
        errors = validate_flags([self._flag(emotion=None)], CODEBOOK, 600.0)
        assert any("emotion" in e for e in errors)
        errors = validate_flags([self._flag(emotion="hangry")], CODEBOOK, 600.0)
        assert any("hangry" in e for e in errors)

    def test_salience_bounds_and_time_bounds(self):
        assert validate_flags([self._flag(salience=0)], CODEBOOK, 600.0)
        assert validate_flags([self._flag(salience=6)], CODEBOOK, 600.0)
        assert validate_flags([self._flag(t_start=700.0, t_end=701.0)], CODEBOOK, 600.0)
        assert validate_flags([self._flag(t_start=10.0, t_end=5.0)], CODEBOOK, 600.0)

    def test_missing_required_field_rejected(self):
        flag = self._flag()
        del flag["quote"]
        errors = validate_flags([flag], CODEBOOK, 600.0)
        assert any("quote" in e for e in errors)

    def test_boolean_salience_rejected(self):
        assert validate_flags([self._flag(salience=True)], CODEBOOK, 600.0)
        assert validate_flags([self._flag(salience=False)], CODEBOOK, 600.0)

    def test_marker_types_string_rejected_without_per_char_noise(self):
        errors = validate_flags([self._flag(marker_types="emotional_display")], CODEBOOK, 600.0)
        assert len(errors) == 1
        assert "must be a list" in errors[0]
        assert not any("unknown marker" in e for e in errors)

    def test_falsy_non_list_marker_types_rejected(self):
        errors = validate_flags([self._flag(marker_types=False)], CODEBOOK, 600.0)
        assert any("must be a list (got bool)" in e for e in errors)
        errors = validate_flags([self._flag(marker_types=0)], CODEBOOK, 600.0)
        assert any("must be a list (got int)" in e for e in errors)

    def test_none_marker_types_reports_only_missing_field(self):
        errors = validate_flags([self._flag(marker_types=None)], CODEBOOK, 600.0)
        assert errors == ["g0001: missing required field 'marker_types'"]

    def test_duplicate_flag_ids_rejected(self):
        # Frame dirs are keyed by flag id — duplicates would cross-contaminate
        # each other's visual evidence.
        errors = validate_flags([self._flag(), self._flag()], CODEBOOK, 600.0)
        assert any("duplicate flag id" in e and "g0001" in e for e in errors)

    def test_paraphrased_quote_rejected_against_transcript(self):
        transcript = "Tell me about it.\nIt was 2019 and I was furious about the layoff."
        errors = validate_flags([self._flag(quote="I was very angry")], CODEBOOK, 600.0,
                                transcript_text=transcript)
        assert any("verbatim substring" in e for e in errors)
        # the verbatim quote passes untouched
        assert validate_flags([self._flag(quote="I was furious")], CODEBOOK, 600.0,
                              transcript_text=transcript) == []

    def test_no_transcript_text_skips_verbatim_check(self):
        # backward compat: without transcript_text the quote gate is off
        errors = validate_flags([self._flag(quote="words found nowhere")], CODEBOOK, 600.0)
        assert not any("verbatim" in e for e in errors)


class TestBurstTimestamps:
    def test_five_points_centered_on_span_midpoint(self):
        points = burst_timestamps(60.0, 64.0, duration=600.0)
        assert points == [57.0, 59.5, 62.0, 64.5, 67.0]

    def test_clamped_at_media_edges(self):
        points = burst_timestamps(1.0, 2.0, duration=600.0)
        assert points[0] == 0.0
        points = burst_timestamps(598.0, 599.0, duration=600.0)
        assert points[-1] == 600.0

    def test_clamping_dedupes(self):
        points = burst_timestamps(0.0, 0.0, duration=4.0)
        assert points == sorted(set(points))

    def test_count_one_yields_clamped_midpoint(self):
        assert burst_timestamps(60.0, 64.0, 600.0, count=1) == [62.0]

    def test_pulled_in_duration_keeps_points_off_media_end(self):
        # cmd_frames pulls the clamp ceiling in by 0.1s: a seek at exactly
        # t=duration yields no frame, so end-of-interview bursts must stay
        # strictly under the true duration.
        duration = 30.0
        points = burst_timestamps(29.0, 30.0, max(duration - 0.1, 0.0))
        assert points
        assert all(p <= duration - 0.1 for p in points)
