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


class TestComputeConcordance:
    def _turns(self):
        return [{"id": "t0001", "start": 0.0, "end": 4.0, "text": "x"},
                {"id": "t0002", "start": 6.0, "end": 9.0, "text": "y"}]

    def test_unanimous_panel_yields_full_concordance(self):
        panels = [{"t0001": "INTERVIEWER", "t0002": "INTERVIEWEE"}] * 3
        result = compute_concordance(self._turns(), panels)
        assert result["t0001"] == {"label": "INTERVIEWER", "concordance": 1.0, "votes": 3}
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
