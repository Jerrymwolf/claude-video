"""Diff engine: word alignment across two Whisper outputs + adjudication apply."""
from __future__ import annotations

import pytest

from dual_transcribe import (
    apply_adjudications,
    diff_transcripts,
    normalize_token,
    words_with_times,
)


def seg(start, end, text):
    return {"start": start, "end": end, "text": text}


class TestWordsWithTimes:
    def test_interpolates_word_times_across_segment(self):
        words = words_with_times([seg(10.0, 14.0, "one two three four")])
        assert [w["raw"] for w in words] == ["one", "two", "three", "four"]
        assert [w["t"] for w in words] == [10.0, 11.0, 12.0, 13.0]
        assert all(w["seg"] == 0 for w in words)

    def test_normalization_strips_punct_and_case(self):
        assert normalize_token("Hello,") == "hello"
        assert normalize_token("didn't") == "didn't"
        assert normalize_token("(WOW)") == "wow"


class TestDiffTranscripts:
    def test_identical_inputs_produce_no_disagreements(self):
        a = [seg(0.0, 2.0, "I walked into the room")]
        result = diff_transcripts(a, a)
        assert result["disagreements"] == []
        assert [w["raw"] for w in result["stream"]] == ["I", "walked", "into", "the", "room"]

    def test_case_and_punct_differences_are_agreements_with_groq_surface(self):
        groq = [seg(0.0, 2.0, "Hello, world today")]
        openai = [seg(0.0, 2.0, "hello world today")]
        result = diff_transcripts(groq, openai)
        assert result["disagreements"] == []
        assert [w["raw"] for w in result["stream"]] == ["Hello,", "world", "today"]

    def test_substitution_becomes_disagreement_with_both_readings(self):
        groq = [seg(0.0, 3.0, "she felt very ecstatic about it")]
        openai = [seg(0.0, 3.0, "she felt very static about it")]
        result = diff_transcripts(groq, openai)
        assert len(result["disagreements"]) == 1
        d = result["disagreements"][0]
        assert d["id"] == "d0001"
        assert d["groq_text"] == "ecstatic"
        assert d["openai_text"] == "static"
        assert d["context_before"].endswith("very")
        assert d["context_after"].startswith("about")
        gaps = [item for item in result["stream"] if item["kind"] == "gap"]
        assert [g["id"] for g in gaps] == ["d0001"]

    def test_insertion_on_openai_side_yields_empty_groq_text(self):
        groq = [seg(0.0, 2.0, "we went home")]
        openai = [seg(0.0, 2.0, "we all went home")]
        result = diff_transcripts(groq, openai)
        assert len(result["disagreements"]) == 1
        d = result["disagreements"][0]
        assert d["groq_text"] == ""
        assert d["openai_text"] == "all"

    def test_disagreement_carries_time_estimate(self):
        groq = [seg(10.0, 12.0, "alpha beta gamma delta")]
        openai = [seg(10.0, 12.0, "alpha beta gomma delta")]
        result = diff_transcripts(groq, openai)
        d = result["disagreements"][0]
        assert 10.0 <= d["t_start"] <= 12.0
        assert d["t_start"] <= d["t_end"]


class TestApplyAdjudications:
    def _diffed(self):
        groq = [seg(0.0, 3.0, "she felt very ecstatic about it")]
        openai = [seg(0.0, 3.0, "she felt very static about it")]
        return diff_transcripts(groq, openai)

    def test_missing_decision_raises(self):
        r = self._diffed()
        with pytest.raises(ValueError, match="d0001"):
            apply_adjudications(r["stream"], r["disagreements"], {})

    def test_decision_text_is_spliced_into_final_segments(self):
        r = self._diffed()
        decisions = {"d0001": {"text": "ecstatic", "rationale": "context: felt very X about"}}
        segments, audit = apply_adjudications(r["stream"], r["disagreements"], decisions)
        assert len(segments) == 1
        assert segments[0]["text"] == "she felt very ecstatic about it"
        assert segments[0]["start"] == 0.0
        assert len(audit) == 1
        assert audit[0]["id"] == "d0001"
        assert audit[0]["chosen_text"] == "ecstatic"
        assert audit[0]["groq_text"] == "ecstatic"
        assert audit[0]["openai_text"] == "static"
        assert audit[0]["rationale"] == "context: felt very X about"

    def test_empty_decision_text_deletes_the_span(self):
        groq = [seg(0.0, 2.0, "we um went home")]
        openai = [seg(0.0, 2.0, "we went home")]
        r = diff_transcripts(groq, openai)
        decisions = {r["disagreements"][0]["id"]: {"text": "", "rationale": "filler; openai right"}}
        segments, _ = apply_adjudications(r["stream"], r["disagreements"], decisions)
        assert segments[0]["text"] == "we went home"

    def test_segments_regroup_across_original_boundaries(self):
        groq = [seg(0.0, 2.0, "first segment here"), seg(3.0, 5.0, "second segment there")]
        openai = [seg(0.0, 2.0, "first segment here"), seg(3.0, 5.0, "second segment there")]
        r = diff_transcripts(groq, openai)
        segments, audit = apply_adjudications(r["stream"], r["disagreements"], {})
        assert len(segments) == 2
        assert segments[0]["text"] == "first segment here"
        assert segments[1]["text"] == "second segment there"
        assert audit == []
