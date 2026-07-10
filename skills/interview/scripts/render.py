#!/usr/bin/env python3
"""Render final artifacts: a .docx transcript with gravity flags as anchored
Word comments, and the JSON sidecar. Raw OOXML via zipfile — stdlib only,
same approach as hand-rolled multipart in stt.py: the format is small and
predictable, so we write it directly rather than pulling python-docx."""
from __future__ import annotations

import copy
import re
import zipfile
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from dual_transcribe import ENGINE_SKIPPED, TRANSCRIPTION_FAILED

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments.xml"/>
</Relationships>"""


_XML_ILLEGAL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _xml_text(text: str) -> str:
    """Escape for XML and strip characters XML 1.0 cannot represent at all."""
    return escape(_XML_ILLEGAL_RE.sub("", text))


def format_hms(seconds: float) -> str:
    s = max(0, int(seconds or 0))
    if s >= 3600:
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    return f"{s // 60:02d}:{s % 60:02d}"


def _run(text: str, bold: bool = False) -> str:
    props = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return f'<w:r>{props}<w:t xml:space="preserve">{_xml_text(text)}</w:t></w:r>'


def _flag_comment_text(flag: dict) -> str:
    markers = ", ".join(flag.get("marker_types") or [])
    bits = [f"GRAVITY [{markers}]"]
    if flag.get("emotion"):
        bits.append(f"emotion: {flag['emotion']}")
    if flag.get("salience") is not None:
        bits.append(f"salience {flag['salience']}/5")
    bits.append(f"t={format_hms(flag.get('t_start', 0))}-{format_hms(flag.get('t_end', 0))}")
    if flag.get("note"):
        bits.append(flag["note"])
    if flag.get("visual_evidence"):
        bits.append(f"visual: {flag['visual_evidence']}")
    if flag.get("frame_paths"):
        bits.append(f"frames: {len(flag['frame_paths'])}")
    return " | ".join(bits)


def _paragraph_for_turn(turn: dict, turn_flags: list[tuple[int, dict]]) -> str:
    """One <w:p> per turn. Flags whose quote is found in the turn text get a
    comment range around exactly that substring; unfindable quotes anchor the
    whole turn text. Flags are applied left-to-right; overlaps fall back to
    whole-paragraph anchoring."""
    header = _run(f"[{format_hms(turn['start'])}] {turn['label']}: ", bold=True)
    text = turn["text"]

    spans = []  # (pos, end, comment_id) — non-overlapping, sorted
    whole_para: list[int] = []
    cursor_taken: list[tuple[int, int]] = []
    for cid, flag in turn_flags:
        pos = text.find(flag.get("quote") or "")
        if flag.get("quote") and pos >= 0:
            end = pos + len(flag["quote"])
            if any(not (end <= s or pos >= e) for s, e in cursor_taken):
                whole_para.append(cid)
                continue
            cursor_taken.append((pos, end))
            spans.append((pos, end, cid))
        else:
            whole_para.append(cid)
    spans.sort()

    body_parts: list[str] = []
    for cid in whole_para:
        body_parts.append(f'<w:commentRangeStart w:id="{cid}"/>')
    cursor = 0
    for pos, end, cid in spans:
        if pos > cursor:
            body_parts.append(_run(text[cursor:pos]))
        body_parts.append(f'<w:commentRangeStart w:id="{cid}"/>')
        body_parts.append(_run(text[pos:end]))
        body_parts.append(f'<w:commentRangeEnd w:id="{cid}"/>')
        body_parts.append(f'<w:r><w:commentReference w:id="{cid}"/></w:r>')
        cursor = end
    if cursor < len(text):
        body_parts.append(_run(text[cursor:]))
    for cid in whole_para:
        body_parts.append(f'<w:commentRangeEnd w:id="{cid}"/>')
        body_parts.append(f'<w:r><w:commentReference w:id="{cid}"/></w:r>')

    return f"<w:p>{header}{''.join(body_parts)}</w:p>"


def build_docx_parts(
    turns: list[dict],
    flags: list[dict],
    now: str | None = None,
    claim: str | None = None,
    notes: list[str] | None = None,
) -> dict[str, str]:
    """Pure: labeled turns + validated flags → {zip_name: xml_string}.

    When `claim` is set, an "Accuracy: <claim>" paragraph (plus one "Note: ..."
    paragraph per entry in `notes`) renders directly under the title — the
    .docx travels alone in document-based coding workflows, so the accuracy
    claim must live in both artifacts, not just the sidecar.

    With no turns, flags still emit comment entries but anchor nowhere
    (orphaned in comments.xml) — callers should not render flag-bearing
    documents with empty turns.
    """
    flag_to_turn: dict[str, list[tuple[int, dict]]] = {}
    comments_xml_items: list[str] = []
    date_attr = f' w:date="{now}"' if now else ""
    for cid, flag in enumerate(flags):
        home = None
        for turn in turns:
            in_time = turn["start"] - 2.0 <= flag.get("t_start", 0) <= turn["end"] + 2.0
            if in_time and (flag.get("quote") or "") in turn["text"]:
                home = turn
                break
        if home is None:  # fall back: strict time containment, then ±2s slop
            home = next(
                (t for t in turns if t["start"] <= flag.get("t_start", 0) <= t["end"]),
                None,
            ) or next(
                (t for t in turns
                 if t["start"] - 2.0 <= flag.get("t_start", 0) <= t["end"] + 2.0),
                turns[-1] if turns else None,
            )
        if home is not None:
            flag_to_turn.setdefault(home["id"], []).append((cid, flag))
        comments_xml_items.append(
            f'<w:comment w:id="{cid}" w:author="interview-skill" w:initials="IS"{date_attr}>'
            f"<w:p>{_run(_flag_comment_text(flag))}</w:p></w:comment>"
        )

    paragraphs = [
        "<w:p>" + _run("Interview Transcript", bold=True) + "</w:p>",
    ]
    if claim:
        paragraphs.append(
            "<w:p>" + _run("Accuracy: ", bold=True) + _run(claim) + "</w:p>"
        )
        for note in notes or []:
            paragraphs.append("<w:p>" + _run(f"Note: {note}") + "</w:p>")
    for turn in turns:
        paragraphs.append(_paragraph_for_turn(turn, flag_to_turn.get(turn["id"], [])))

    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W_NS}"><w:body>'
        + "".join(paragraphs)
        + "<w:sectPr/></w:body></w:document>"
    )
    comments = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:comments xmlns:w="{W_NS}">' + "".join(comments_xml_items) + "</w:comments>"
    )
    return {
        "[Content_Types].xml": CONTENT_TYPES,
        "_rels/.rels": ROOT_RELS,
        "word/_rels/document.xml.rels": DOC_RELS,
        "word/document.xml": document,
        "word/comments.xml": comments,
    }


def write_docx(parts: dict[str, str], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in parts.items():
            zf.writestr(name, content)
    return out_path


def build_sidecar(
    media: str,
    duration: float,
    engines: dict,
    degradation: list[str],
    segments: list[dict],
    turns: list[dict],
    adjudications: list[dict],
    flags: list[dict],
    partial_failures: list[str],
    codebook_version: str,
    now: str | None = None,
) -> dict:
    """Pure assembly of the machine-readable record. `now` injectable for tests."""
    dual = engines.get("groq") and engines.get("openai") and not any(
        ENGINE_SKIPPED in d or TRANSCRIPTION_FAILED in d for d in degradation
    )
    if not dual:
        claim = "single-engine UNVERIFIED"
    elif partial_failures:
        claim = ("dual-engine verified with logged adjudication; "
                 "INCOMPLETE — transcription gaps recorded")
    else:
        claim = "dual-engine verified with logged adjudication"
    return {
        "schema_version": "1.0",
        "interview": {
            "media": media,
            "duration_seconds": duration,
            "processed_at": now or datetime.now().astimezone().isoformat(timespec="seconds"),
        },
        "engines": engines,
        "accuracy_claim": claim,
        "degradation": degradation,
        "partial_failures": partial_failures,
        "segments": segments,
        "turns": turns,
        "adjudications": adjudications,
        "flags": [dict(copy.deepcopy(f), codebook_version=codebook_version) for f in flags],
    }
