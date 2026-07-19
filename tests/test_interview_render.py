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

    def test_negative_and_none_clamp_to_zero(self):
        assert format_hms(-115) == "00:00"
        assert format_hms(None) == "00:00"


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

    @staticmethod
    def _anchored_paragraph_texts(document_xml):
        """Text of every <w:p> that contains a commentRangeStart."""
        root = ET.fromstring(document_xml)
        return [
            "".join(t.text or "" for t in p.iter(f"{W}t"))
            for p in root.iter(f"{W}p")
            if p.find(f"{W}commentRangeStart") is not None
        ]

    @staticmethod
    def _assert_comment_ids_consistent(parts):
        """Every range id has a matching end, reference, and comment body."""
        doc = ET.fromstring(parts["word/document.xml"])
        starts = sorted(e.get(f"{W}id") for e in doc.iter(f"{W}commentRangeStart"))
        ends = sorted(e.get(f"{W}id") for e in doc.iter(f"{W}commentRangeEnd"))
        refs = sorted(e.get(f"{W}id") for e in doc.iter(f"{W}commentReference"))
        comments = ET.fromstring(parts["word/comments.xml"])
        bodies = {e.get(f"{W}id") for e in comments.iter(f"{W}comment")}
        assert starts == ends == refs
        assert set(starts) <= bodies

    def test_unfindable_quote_anchors_whole_paragraph(self, tmp_path):
        flags = [dict(FLAGS[0], quote="words that appear nowhere")]
        parts = build_docx_parts(TURNS, flags)
        out = tmp_path / "t.docx"
        write_docx(parts, out)
        with zipfile.ZipFile(out) as zf:
            doc = zf.read("word/document.xml").decode("utf-8")
        assert "commentRangeStart" in doc  # anchored, not dropped
        anchored = self._anchored_paragraph_texts(doc)
        assert len(anchored) == 1
        assert "INTERVIEWEE" in anchored[0]  # t_start=8.0 → home turn t0002

    def test_flag_between_slop_windows_anchors_to_containing_turn(self):
        turns = [
            labeled_turn("t0101", 450.0, 458.0,
                         "And what happened after that?", "INTERVIEWER"),
            labeled_turn("t0102", 459.0, 467.0,
                         "The whole team walked out.", "INTERVIEWEE"),
        ]
        flags = [dict(FLAGS[0], quote="words that appear nowhere",
                      t_start=460.0, t_end=462.0)]
        parts = build_docx_parts(turns, flags)
        anchored = self._anchored_paragraph_texts(parts["word/document.xml"])
        assert len(anchored) == 1
        # strict containment (459-467) must beat the earlier turn's +2s slop
        assert "INTERVIEWEE" in anchored[0]

    def test_two_quote_flags_one_turn_both_anchored_in_order(self):
        flags = [
            FLAGS[0],
            dict(FLAGS[0], id="g0002", marker_types=["repetition"], emotion=None,
                 quote="the layoff decision", t_start=14.0, t_end=17.0),
        ]
        parts = build_docx_parts(TURNS, flags)
        root = ET.fromstring(parts["word/document.xml"])
        order = [e.get(f"{W}id") for e in root.iter(f"{W}commentRangeStart")]
        assert order == ["0", "1"]  # document order matches text position order
        self._assert_comment_ids_consistent(parts)

    def test_overlapping_quotes_second_flag_wraps_whole_paragraph(self):
        flags = [
            FLAGS[0],  # "I was furious"
            dict(FLAGS[0], id="g0002", quote="was furious about"),
        ]
        parts = build_docx_parts(TURNS, flags)
        root = ET.fromstring(parts["word/document.xml"])  # must stay well-formed
        events = []
        for el in root.iter():
            if el.tag == f"{W}commentRangeStart":
                events.append(("start", el.get(f"{W}id")))
            elif el.tag == f"{W}commentRangeEnd":
                events.append(("end", el.get(f"{W}id")))
        # flag 1 falls back to whole-paragraph and encloses flag 0's exact range
        assert events == [("start", "1"), ("start", "0"), ("end", "0"), ("end", "1")]
        self._assert_comment_ids_consistent(parts)

    def test_control_chars_stripped_document_still_parses(self):
        turns = [labeled_turn("t0001", 0.0, 4.0, "clean\x0bbreak", "INTERVIEWER")]
        parts = build_docx_parts(turns, [])
        root = ET.fromstring(parts["word/document.xml"])  # raises if \x0b leaked
        text = "".join(t.text or "" for t in root.iter(f"{W}t"))
        assert "\x0b" not in text
        assert "cleanbreak" in text

    def test_xml_special_chars_round_trip(self):
        raw = 'Q3 P&L was < plan after the "restructuring"'
        turns = [labeled_turn("t0001", 0.0, 4.0, raw, "INTERVIEWER")]
        parts = build_docx_parts(turns, [])
        root = ET.fromstring(parts["word/document.xml"])
        text = "".join(t.text or "" for t in root.iter(f"{W}t"))
        assert raw in text

    def test_comment_omits_salience_when_absent(self):
        flags = [{k: v for k, v in FLAGS[0].items() if k != "salience"}]
        parts = build_docx_parts(TURNS, flags)
        assert "salience" not in parts["word/comments.xml"]

    def test_comment_date_attribute_only_when_now_provided(self):
        dated = build_docx_parts(TURNS, FLAGS, now="2026-07-10T12:00:00-04:00")
        assert 'w:date="2026-07-10T12:00:00-04:00"' in dated["word/comments.xml"]
        assert "w:date" not in build_docx_parts(TURNS, FLAGS)["word/comments.xml"]

    def test_degraded_claim_and_notes_rendered_in_docx(self):
        sc = build_sidecar(
            media="x.mp4", duration=10.0, engines={"groq": "whisper-large-v3"},
            degradation=["openai: no API key — engine skipped"],
            segments=[], turns=[], adjudications=[], flags=[],
            partial_failures=[], codebook_version="1.0.0", now="2026-07-10T12:00:00",
        )
        parts = build_docx_parts(TURNS, FLAGS, claim=sc["accuracy_claim"],
                                 notes=sc["degradation"])
        doc = parts["word/document.xml"]
        ET.fromstring(doc)  # claim/notes must not break well-formedness
        assert "single-engine UNVERIFIED" in doc
        assert "Note: openai: no API key — engine skipped" in doc

    def test_clean_dual_claim_directly_under_title(self):
        sc = build_sidecar(
            media="x.mp4", duration=10.0,
            engines={"groq": "whisper-large-v3", "openai": "whisper-1"},
            degradation=[], segments=[], turns=[], adjudications=[], flags=[],
            partial_failures=[], codebook_version="1.0.0", now="2026-07-10T12:00:00",
        )
        parts = build_docx_parts(TURNS, FLAGS, claim=sc["accuracy_claim"], notes=[])
        root = ET.fromstring(parts["word/document.xml"])
        paras = list(root.iter(f"{W}p"))
        second = "".join(t.text or "" for t in paras[1].iter(f"{W}t"))
        assert second == "Accuracy: dual-engine verified with logged adjudication"

    def test_no_claim_means_no_accuracy_paragraph(self):
        assert "Accuracy:" not in build_docx_parts(TURNS, FLAGS)["word/document.xml"]

    def test_speaker_names_override_labels(self):
        names = {"INTERVIEWER": "Greg", "INTERVIEWEE": "Participant"}
        doc = build_docx_parts(TURNS, FLAGS, names=names)["word/document.xml"]
        assert "[00:00] Greg:" in doc
        assert "[00:06] Participant:" in doc
        assert "INTERVIEWER:" not in doc
        assert "INTERVIEWEE:" not in doc

    def test_unmapped_label_falls_back_to_role(self):
        # only INTERVIEWEE renamed → INTERVIEWER keeps its canonical role label
        doc = build_docx_parts(TURNS, FLAGS, names={"INTERVIEWEE": "Scott"})["word/document.xml"]
        assert "[00:00] INTERVIEWER:" in doc
        assert "[00:06] Scott:" in doc

    def test_default_names_none_keeps_roles(self):
        doc = build_docx_parts(TURNS, FLAGS)["word/document.xml"]
        assert "[00:00] INTERVIEWER:" in doc
        assert "[00:06] INTERVIEWEE:" in doc


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
        # sidecar must not share nested structures with the caller's flags
        sc["flags"][0]["frame_paths"].append("mutated.jpg")
        assert "mutated.jpg" not in FLAGS[0]["frame_paths"]

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

    def test_speaker_names_recorded_when_provided(self):
        sc = build_sidecar(
            media="x.mp4", duration=10.0,
            engines={"groq": "whisper-large-v3", "openai": "whisper-1"},
            degradation=[], segments=[], turns=TURNS, adjudications=[], flags=[],
            partial_failures=[], codebook_version="1.0.0", now="2026-07-10T12:00:00",
            speaker_names={"INTERVIEWER": "Greg", "INTERVIEWEE": "Participant"},
        )
        assert sc["speaker_names"] == {"INTERVIEWER": "Greg", "INTERVIEWEE": "Participant"}
        # the machine-readable research record keeps canonical role labels
        assert sc["turns"][0]["label"] == "INTERVIEWER"

    def test_speaker_names_absent_by_default(self):
        assert "speaker_names" not in self._sidecar()
