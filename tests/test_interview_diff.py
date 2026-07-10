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

    def test_curly_vs_straight_apostrophes_are_agreements(self):
        groq = [seg(0.0, 2.0, "I don’t know")]  # curly apostrophe (U+2019)
        openai = [seg(0.0, 2.0, "I don't know")]  # straight apostrophe
        result = diff_transcripts(groq, openai)
        assert result["disagreements"] == []

    def test_empty_vs_nonempty_engine_is_one_big_disagreement(self):
        """An engine that returned zero segments must not be treated as absent:
        the CLI diffs [] against the other engine, surfacing the whole
        transcript as a disagreement to adjudicate instead of silently
        self-diffing and claiming dual-engine verification."""
        result = diff_transcripts([], [seg(0.0, 1.0, "hi")])
        assert len(result["disagreements"]) == 1
        d = result["disagreements"][0]
        assert d["groq_text"] == ""
        assert d["openai_text"] == "hi"

    def test_punctuation_only_tokens_do_not_falsely_agree(self):
        groq = [seg(0.0, 2.0, "wait — no")]
        openai = [seg(0.0, 2.0, "wait ... no")]
        result = diff_transcripts(groq, openai)
        assert len(result["disagreements"]) == 1
        d = result["disagreements"][0]
        assert d["groq_text"] == "—"
        assert d["openai_text"] == "..."
        agreed = [w["raw"] for w in result["stream"] if w["kind"] == "word"]
        assert agreed == ["wait", "no"]


class TestApplyAdjudications:
    def _diffed(self):
        groq = [seg(0.0, 3.0, "she felt very ecstatic about it")]
        openai = [seg(0.0, 3.0, "she felt very static about it")]
        return diff_transcripts(groq, openai)

    def test_missing_decision_raises(self):
        r = self._diffed()
        with pytest.raises(ValueError, match="d0001"):
            apply_adjudications(r["stream"], r["disagreements"], {})

    def test_unknown_decision_id_raises(self):
        r = self._diffed()
        decisions = {
            "d0001": {"text": "ecstatic", "rationale": "context"},
            "d0099": {"text": "ghost", "rationale": "no such disagreement"},
        }
        with pytest.raises(ValueError, match="d0099"):
            apply_adjudications(r["stream"], r["disagreements"], decisions)

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

    def test_adjudication_can_delete_an_entire_segment(self):
        groq = [seg(0.0, 1.0, "only word"), seg(2.0, 4.0, "keep this")]
        openai = [seg(2.0, 4.0, "keep this")]
        r = diff_transcripts(groq, openai)
        assert len(r["disagreements"]) == 1
        d = r["disagreements"][0]
        assert d["groq_text"] == "only word"
        assert d["openai_text"] == ""
        decisions = {d["id"]: {"text": "", "rationale": "hallucinated; openai right"}}
        segments, audit = apply_adjudications(r["stream"], r["disagreements"], decisions)
        assert len(segments) == 1
        assert segments[0]["text"] == "keep this"
        assert segments[0]["start"] == 2.0
        assert len(audit) == 1
        assert audit[0]["chosen_text"] == ""


class TestTranscribeBoth:
    def test_missing_engine_key_records_degradation(self, monkeypatch, tmp_path):
        import stt

        import dual_transcribe

        def fake_extract_audio(video_path, out_path):
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"fake-mp3-bytes")
            return out_path

        def fake_load_api_key(preferred=None):
            if preferred == "groq":
                return ("groq", "k")
            return (None, None)

        def fake_transcribe_chunks(chunks, transcribe_one):
            return [{"start": 0.0, "end": 1.0, "text": "hi"}]

        monkeypatch.setattr(stt, "extract_audio", fake_extract_audio)
        monkeypatch.setattr(stt, "load_api_key", fake_load_api_key)
        monkeypatch.setattr(stt, "transcribe_chunks", fake_transcribe_chunks)

        results = dual_transcribe.transcribe_both("fake.mp4", tmp_path / "work")
        assert results["groq"] == [{"start": 0.0, "end": 1.0, "text": "hi"}]
        assert results["openai"] is None
        assert len(results["degradation"]) == 1
        assert "engine skipped" in results["degradation"][0]
        assert results["partial_failures"] == []

    def test_partial_chunk_failure_is_recorded(self, tmp_path, monkeypatch):
        """The per-chunk wrapper records failures into partial_failures before
        re-raising, so holes in a transcript are visible to the sidecar."""
        import stt
        from dual_transcribe import transcribe_both

        fake_audio = tmp_path / "audio.mp3"
        fake_audio.write_bytes(b"x" * 10)
        monkeypatch.setattr(stt, "extract_audio", lambda media, out: fake_audio)
        monkeypatch.setattr(
            stt, "load_api_key",
            lambda preferred=None: ("groq", "k") if preferred == "groq" else (None, None),
        )
        calls = {"n": 0}

        def flaky_transcribe(backend, key, path):
            calls["n"] += 1
            if calls["n"] == 1:
                raise SystemExit("HTTP 500")
            return [{"start": 0.0, "end": 1.0, "text": "recovered"}]

        monkeypatch.setattr(stt, "_transcribe_file", flaky_transcribe)
        real_chunks = stt.transcribe_chunks
        monkeypatch.setattr(
            stt, "transcribe_chunks",
            lambda chunks, fn: real_chunks([(fake_audio, 0.0), (fake_audio, 5.0)], fn),
        )
        results = transcribe_both("whatever.mp4", tmp_path / "work")
        # chunk 2 carries offset 5.0, so shift_segments shifts its 0.0-1.0
        # segment into 5.0-6.0 source time — the hole is chunk 1 (0.0-5.0).
        assert results["groq"] == [{"start": 5.0, "end": 6.0, "text": "recovered"}]
        assert len(results["partial_failures"]) == 1
        assert "groq: chunk" in results["partial_failures"][0]
        assert "HTTP 500" in results["partial_failures"][0]
        assert any("openai" in d for d in results["degradation"])
