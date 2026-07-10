"""Renderer: OOXML .docx with anchored comments + sidecar schema."""
from __future__ import annotations

import json
import zipfile
import xml.etree.ElementTree as ET

from render import build_docx_parts, build_sidecar, format_hms, write_docx

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{W_NS}}}"


def labeled_turn(tid, start, end, text, label, concordance=1.0):
    return {"id": tid, "start": start, "end": end, "text": text,
            "label": label, "concordance": concordance}


TURNS = [
    labeled_turn("t0001", 0.0, 4.0, "Tell me about a difficult decision.", "INTERVIEWER"),
    labeled_turn("t0002", 6.0, 20.0,
                 "It was 2019 and I was furious about the layoff decision.", "INTERVIEWEE"),
]

FLAGS = [{
    "id": "g0001",
    "marker_types": ["emotional_display"],
    "emotion": "anger",
    "quote": "I was furious",
    "t_start": 8.0,
    "t_end": 11.0,
    "salience": 4,
    "note": "anger tied to the layoff episode",
    "frame_paths": ["frames/g0001/cue_0000.jpg"],
    "visual_evidence": "corroborates — jaw set, gesture sharpens",
}]


class TestFormatHms:
    def test_minutes_seconds(self):
        assert format_hms(62) == "01:02"

    def test_hours_rollover(self):
        assert format_hms(3723) == "1:02:03"


class TestDocx:
    def _document_xml(self, tmp_path):
        parts = build_docx_parts(TURNS, FLAGS)
        out = tmp_path / "transcript.docx"
        write_docx(parts, out)
        with zipfile.ZipFile(out) as zf:
            return {name: zf.read(name).decode("utf-8") for name in zf.namelist()}

    def test_package_contains_required_parts(self, tmp_path):
        contents = self._document_xml(tmp_path)
        assert "[Content_Types].xml" in contents
        assert "word/document.xml" in contents
        assert "word/comments.xml" in contents
        assert "word/_rels/document.xml.rels" in contents
        assert "comments+xml" in contents["[Content_Types].xml"]

    def test_every_turn_rendered_with_speaker_and_timestamp(self, tmp_path):
        doc = self._document_xml(tmp_path)["word/document.xml"]
        assert "[00:00] INTERVIEWER:" in doc
        assert "[00:06] INTERVIEWEE:" in doc
        assert "Tell me about a difficult decision." in doc

    def test_comment_range_wraps_exactly_the_quote(self, tmp_path):
        doc = self._document_xml(tmp_path)["word/document.xml"]
        root = ET.fromstring(doc)
        # walk the flagged paragraph in document order
        events, inside = [], False
        for el in root.iter():
            if el.tag == f"{W}commentRangeStart":
                inside = True
            elif el.tag == f"{W}commentRangeEnd":
                inside = False
            elif el.tag == f"{W}t" and inside:
                events.append(el.text or "")
        assert "".join(events) == "I was furious"

    def test_comment_body_carries_flag_metadata(self, tmp_path):
        comments = self._document_xml(tmp_path)["word/comments.xml"]
        assert "emotional_display" in comments
        assert "anger" in comments
        assert "salience 4/5" in comments
        assert "corroborates" in comments

    def test_unfindable_quote_anchors_whole_paragraph(self, tmp_path):
        flags = [dict(FLAGS[0], quote="words that appear nowhere")]
        parts = build_docx_parts(TURNS, flags)
        out = tmp_path / "t.docx"
        write_docx(parts, out)
        with zipfile.ZipFile(out) as zf:
            doc = zf.read("word/document.xml").decode("utf-8")
        assert "commentRangeStart" in doc  # anchored, not dropped


class TestSidecar:
    def _sidecar(self):
        return build_sidecar(
            media="bei_017.mp4",
            duration=1800.0,
            engines={"groq": "whisper-large-v3", "openai": "whisper-1"},
            degradation=[],
            segments=[{"start": 0.0, "end": 4.0, "text": "Tell me."}],
            turns=TURNS,
            adjudications=[{"id": "d0001", "t_start": 8.0, "t_end": 8.5,
                            "groq_text": "furious", "openai_text": "curious",
                            "chosen_text": "furious", "rationale": "context: anger episode"}],
            flags=FLAGS,
            partial_failures=[],
            codebook_version="1.0.0",
            now="2026-07-10T12:00:00",
        )

    def test_schema_shape(self):
        sc = self._sidecar()
        assert sc["schema_version"] == "1.0"
        assert sc["interview"]["media"] == "bei_017.mp4"
        assert sc["interview"]["processed_at"] == "2026-07-10T12:00:00"
        assert sc["accuracy_claim"] == "dual-engine verified with logged adjudication"
        assert len(sc["adjudications"]) == 1
        assert sc["flags"][0]["codebook_version"] == "1.0.0"
        assert sc["turns"][0]["label"] == "INTERVIEWER"

    def test_degradation_downgrades_accuracy_claim(self):
        sc = build_sidecar(
            media="x.mp4", duration=10.0, engines={"groq": "whisper-large-v3"},
            degradation=["openai: no API key — engine skipped"],
            segments=[], turns=[], adjudications=[], flags=[],
            partial_failures=[], codebook_version="1.0.0", now="2026-07-10T12:00:00",
        )
        assert sc["accuracy_claim"] == "single-engine UNVERIFIED"

    def test_partial_failures_mark_claim_incomplete(self):
        sc = build_sidecar(
            media="x.mp4", duration=10.0,
            engines={"groq": "whisper-large-v3", "openai": "whisper-1"},
            degradation=[],
            segments=[], turns=[], adjudications=[], flags=[],
            partial_failures=["groq: chunk chunk_002.mp3 failed — HTTP 500"],
            codebook_version="1.0.0", now="2026-07-10T12:00:00",
        )
        assert "INCOMPLETE" in sc["accuracy_claim"]
        assert sc["partial_failures"] == ["groq: chunk chunk_002.mp3 failed — HTTP 500"]

    def test_sidecar_is_json_serializable(self):
        json.dumps(self._sidecar())
