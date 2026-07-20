"""Renderer: OOXML .docx with anchored comments + sidecar schema."""
from __future__ import annotations

import json
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from render import build_docx_parts, build_sidecar, format_hms, write_docx

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "interview" / "scripts"

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

# Sentinel for "delete this key" in the per-field comment fixtures below; None
# would only test the falsy branch, not the absent one.
_ABSENT = object()

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


class TestFlagCommentFields:
    """The .docx comment is the human coding surface for document-based review,
    so every codebook-declared field a flag actually carries must reach it. The
    sidecar was already complete; the comment read `emotion` alone, so a
    codebook declaring `affect_field: "affect"` lost its affect entirely, along
    with speaker_role, episode_id and attribution_uncertain."""

    @staticmethod
    def comment_text(**over):
        """Text of the single comment for one flag built from FLAGS[0]."""
        flag = dict(FLAGS[0])
        flag.update(over)
        for key, value in list(flag.items()):
            if value is _ABSENT:
                del flag[key]
        parts = build_docx_parts(TURNS, [flag])
        root = ET.fromstring(parts["word/comments.xml"])
        return "".join(t.text or "" for t in root.iter(f"{W}t"))

    def test_moral_flag_fields_all_reach_the_comment(self):
        text = self.comment_text(emotion=_ABSENT, affect="contempt",
                                 speaker_role="INTERVIEWEE", episode_id="e01",
                                 marker_types=["displacement_of_responsibility"])
        assert "speaker: INTERVIEWEE" in text
        assert "episode: e01" in text
        assert "affect: contempt" in text
        assert "displacement_of_responsibility" in text

    def test_narrative_flag_keeps_the_emotion_label(self):
        # the shipped narrative path must be byte-unchanged: its flags carry
        # `emotion`, and relabelling it "affect" would rewrite every existing
        # narrative .docx for no evidentiary gain
        text = self.comment_text()
        assert "emotion: anger" in text
        assert "affect" not in text

    def test_the_narrative_comment_line_is_byte_stable(self):
        """The exact narrative line, pinned whole.

        Two design decisions in this function exist to keep this string
        unchanged (the `GRAVITY` prefix stays literal; the affect segment keeps
        the label of the field the flag actually carries), and substring
        assertions cannot enforce either — nor can they catch an edit to the
        salience/t=/note/visual/frames tail, which would silently rewrite every
        existing narrative .docx while the suite stayed green.
        """
        assert self.comment_text() == (
            "GRAVITY [emotional_display] | emotion: anger | salience 4/5 | "
            "t=00:08-00:11 | anger tied to the layoff episode | "
            "visual: corroborates — jaw set, gesture sharpens | frames: 1")

    def test_every_shipped_codebook_declares_an_affect_field_this_reads(self):
        """`_flag_comment_text` hardcodes the pair 'affect'/'emotion'.

        It cannot consult `codebook["affect_field"]` — build_docx_parts never
        receives the codebook — so a third codebook declaring, say,
        `affect_field: "valence"` would silently drop affect from the .docx
        comment: byte-for-byte the defect this class was written to fix, one
        codebook later. Pin the coupling so it fails here, loudly, instead.
        """
        fields = {json.loads(p.read_text(encoding="utf-8")).get("affect_field",
                                                                "emotion")
                  for p in SCRIPTS.glob("codebook*.json")}
        assert fields, "no codebooks found — the glob went stale"
        assert fields <= {"emotion", "affect"}, (
            "_flag_comment_text hardcodes 'affect'/'emotion'; a codebook "
            "declaring another affect_field would silently drop it from the "
            ".docx comment. Thread the codebook into build_docx_parts, or "
            "extend the pair here.")

    def test_affect_wins_when_a_flag_carries_both(self):
        # a codebook-declared affect_field is the authority; a stale `emotion`
        # left behind by copy-editing a narrative codebook must not win
        text = self.comment_text(affect="contempt", emotion="anger", note=_ABSENT)
        assert "affect: contempt" in text
        assert "emotion:" not in text and "anger" not in text

    def test_attribution_uncertain_shows_only_when_true(self):
        assert "attribution uncertain" in self.comment_text(attribution_uncertain=True)
        assert "attribution uncertain" not in self.comment_text(
            attribution_uncertain=False)
        assert "attribution uncertain" not in self.comment_text()

    def test_absent_fields_leave_no_empty_segments(self):
        text = self.comment_text(emotion=_ABSENT, note=_ABSENT,
                                 frame_paths=_ABSENT, visual_evidence=_ABSENT)
        assert "speaker:" not in text and "episode:" not in text
        # "emotion:" not "emotion" — the marker id is `emotional_display`
        assert "affect" not in text and "emotion:" not in text
        assert "|  |" not in text and "| |" not in text
        assert not text.endswith("|") and not text.endswith("| ")

    def test_segments_stay_pipe_delimited_and_terse(self):
        text = self.comment_text(emotion=_ABSENT, affect="contempt",
                                 speaker_role="INTERVIEWEE", episode_id="e01",
                                 attribution_uncertain=True, note=_ABSENT,
                                 visual_evidence=_ABSENT)
        assert text == ("GRAVITY [emotional_display] | speaker: INTERVIEWEE | "
                        "attribution uncertain | episode: e01 | affect: contempt | "
                        "salience 4/5 | t=00:08-00:11 | frames: 1")


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
        assert sc["schema_version"] == "1.1"
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

    def test_episodes_persona_and_codebook_identity_recorded(self):
        eps = [{"id": "e01", "type": "confrontation", "t_start": 0.0, "t_end": 30.0,
                "target_descriptor": "woman", "target_speech": True,
                "arc": {"phases": ["threat", "defense"], "outcome": "refuses",
                        "turning_point": None}}]
        sc = build_sidecar(
            media="x.mp4", duration=10.0,
            engines={"groq": "whisper-large-v3", "openai": "whisper-1"},
            degradation=[], segments=[], turns=TURNS, adjudications=[], flags=[],
            partial_failures=[], codebook_version="1.0.0", now="2026-07-10T12:00:00",
            episodes=eps, persona="Agent Greg Gorey",
            codebook_file="codebook_moral_identity.json",
        )
        assert sc["schema_version"] == "1.1"
        assert sc["codebook_version"] == "1.0.0"
        assert sc["episodes"][0]["arc"]["outcome"] == "refuses"
        assert sc["interview"]["persona"] == "Agent Greg Gorey"
        assert sc["codebook_file"] == "codebook_moral_identity.json"
        # deep-copied — mutating the sidecar must not touch the caller's episodes
        sc["episodes"][0]["arc"]["phases"].append("exit")
        assert eps[0]["arc"]["phases"] == ["threat", "defense"]

    def test_episode_fields_absent_by_default(self):
        sc = self._sidecar()
        assert "episodes" not in sc
        assert "persona" not in sc["interview"]
        # codebook_file is a fixed slot, not an optional one: None says "the
        # builder was never told", which cmd_render never does
        assert sc["codebook_file"] is None

    def test_codebook_identity_serializes_ahead_of_the_flags_array(self):
        # a human opening the artifact must reach "which codebook?" without
        # scrolling past every flag
        keys = list(self._sidecar())
        assert keys.index("codebook_version") < keys.index("flags")
        assert keys.index("codebook_file") < keys.index("flags")

    def test_empty_persona_reads_as_absent(self):
        # the CLI refuses --persona "" outright (an unset shell variable); the
        # builder's own rule is that an empty character is no character
        sc = build_sidecar(
            media="x.mp4", duration=10.0,
            engines={"groq": "whisper-large-v3", "openai": "whisper-1"},
            degradation=[], segments=[], turns=TURNS, adjudications=[], flags=[],
            partial_failures=[], codebook_version="1.0.0", now="2026-07-10T12:00:00",
            persona="",
        )
        assert "persona" not in sc["interview"]

    def test_codebook_version_recorded_at_top_level_on_the_shipped_path(self):
        # identity belongs to the record, not only to each flag: a sidecar whose
        # flags list is empty must still say which codebook produced it
        sc = build_sidecar(
            media="x.mp4", duration=10.0,
            engines={"groq": "whisper-large-v3", "openai": "whisper-1"},
            degradation=[], segments=[], turns=TURNS, adjudications=[], flags=[],
            partial_failures=[], codebook_version="2.5.1", now="2026-07-10T12:00:00",
        )
        assert sc["codebook_version"] == "2.5.1"

    def test_empty_episode_list_is_recorded_not_dropped(self):
        # `episodes is not None`, not truthiness: "the episode pass ran and found
        # nothing" is a different research claim from "no episode pass ran"
        sc = build_sidecar(
            media="x.mp4", duration=10.0,
            engines={"groq": "whisper-large-v3", "openai": "whisper-1"},
            degradation=[], segments=[], turns=TURNS, adjudications=[], flags=[],
            partial_failures=[], codebook_version="1.0.0", now="2026-07-10T12:00:00",
            episodes=[],
        )
        assert sc["episodes"] == []
