#!/usr/bin/env python3
"""Dual-engine transcription + word-level diff for the /interview skill.

Pure cores (unit-tested, no I/O): words_with_times, diff_transcripts,
apply_adjudications. Orchestration (transcribe_both) reuses stt.py — audio is
extracted and chunk-planned ONCE, then uploaded to each backend.

The diff is the backbone of the skill's accuracy claim: everything both
engines agree on (case/punctuation-insensitive) becomes the base transcript
(Groq surface forms); every disagreement becomes a numbered span that Claude
must adjudicate before the transcript can be finalized.
"""
from __future__ import annotations

import difflib
import re
import sys
from pathlib import Path

import stt

WORD_RE = re.compile(r"\S+")
NORM_RE = re.compile(r"[^\w']+", re.UNICODE)

# Degradation-record markers. A later task's sidecar builder imports these
# instead of grepping magic strings out of the degradation messages.
ENGINE_SKIPPED = "engine skipped"
TRANSCRIPTION_FAILED = "transcription failed"


def normalize_token(raw: str) -> str:
    """Lowercase and strip punctuation (keeping intra-word apostrophes).

    Curly apostrophes (U+2019, U+02BC) are folded to straight ones first —
    engines disagree on apostrophe style, and without folding every
    contraction would become a spurious disagreement.
    """
    raw = raw.replace("’", "'").replace("ʼ", "'")
    return NORM_RE.sub("", raw).lower()


def words_with_times(segments: list[dict]) -> list[dict]:
    """Flatten segments into words with linearly interpolated timestamps.

    Whisper verbose_json is segment-timed, not word-timed; interpolation is
    accurate enough to anchor a disagreement to within a second or two, which
    is all adjudication and flag anchoring need.
    """
    words: list[dict] = []
    for seg_idx, seg in enumerate(segments):
        tokens = WORD_RE.findall(seg["text"])
        if not tokens:
            continue
        span = max(float(seg["end"]) - float(seg["start"]), 0.0)
        step = span / len(tokens)
        for i, raw in enumerate(tokens):
            words.append({
                "raw": raw,
                # Punctuation-only tokens ("—", "...") normalize to "" and
                # would spuriously match each other across streams; fall
                # back to the raw form so they only match themselves.
                "key": normalize_token(raw) or raw.lower(),
                "t": round(float(seg["start"]) + i * step, 2),
                "seg": seg_idx,
            })
    return words


def diff_transcripts(
    groq_segments: list[dict],
    openai_segments: list[dict],
    context_words: int = 8,
) -> dict:
    """Align both word streams; return the agreed base stream + disagreements.

    Returns {"stream": [...], "disagreements": [...]} where stream items are
    {"kind": "word", raw, t, seg} or {"kind": "gap", id, t, seg} placeholders,
    and each disagreement is {id, t_start, t_end, groq_text, openai_text,
    context_before, context_after}. Agreements take Groq's surface form.
    """
    a = words_with_times(groq_segments)
    b = words_with_times(openai_segments)
    matcher = difflib.SequenceMatcher(
        None, [w["key"] for w in a], [w["key"] for w in b], autojunk=False
    )

    stream: list[dict] = []
    disagreements: list[dict] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for w in a[i1:i2]:
                stream.append({"kind": "word", "raw": w["raw"], "t": w["t"], "seg": w["seg"]})
            continue

        d_id = f"d{len(disagreements) + 1:04d}"
        g_words, o_words = a[i1:i2], b[j1:j2]
        anchor = g_words or o_words
        if anchor:
            t_start, t_end = anchor[0]["t"], anchor[-1]["t"]
        else:
            # unreachable by construction: a non-equal opcode always has
            # words on at least one side
            t_start = t_end = a[i1 - 1]["t"] if i1 > 0 else 0.0
        seg = g_words[0]["seg"] if g_words else (a[i1 - 1]["seg"] if i1 > 0 else 0)

        disagreements.append({
            "id": d_id,
            "t_start": t_start,
            "t_end": t_end,
            "groq_text": " ".join(w["raw"] for w in g_words),
            "openai_text": " ".join(w["raw"] for w in o_words),
            "context_before": " ".join(w["raw"] for w in a[max(0, i1 - context_words):i1]),
            "context_after": " ".join(w["raw"] for w in a[i2:i2 + context_words]),
        })
        stream.append({"kind": "gap", "id": d_id, "t": t_start, "seg": seg})

    return {"stream": stream, "disagreements": disagreements}


def apply_adjudications(
    stream: list[dict],
    disagreements: list[dict],
    decisions: dict,
) -> tuple[list[dict], list[dict]]:
    """Splice adjudicated text into the base stream; regroup into segments.

    decisions: {"d0001": {"text": "<chosen text>", "rationale": "<why>"}, ...}
    Every disagreement must have a decision (empty text = delete the span).
    Returns (final_segments, audit_log).
    """
    by_id = {d["id"]: d for d in disagreements}
    missing = sorted(d_id for d_id in by_id if d_id not in decisions)
    if missing:
        raise ValueError(f"missing adjudications for: {', '.join(missing)}")
    unknown = sorted(set(decisions) - set(by_id))
    if unknown:
        raise ValueError(
            f"decisions reference unknown disagreement ids: {', '.join(unknown)}"
        )

    words: list[dict] = []
    audit: list[dict] = []
    for item in stream:
        if item["kind"] == "word":
            words.append(item)
            continue
        d = by_id[item["id"]]
        decision = decisions[item["id"]]
        chosen = (decision.get("text") or "").strip()
        audit.append({
            "id": d["id"],
            "t_start": d["t_start"],
            "t_end": d["t_end"],
            "groq_text": d["groq_text"],
            "openai_text": d["openai_text"],
            "chosen_text": chosen,
            "rationale": (decision.get("rationale") or "").strip(),
        })
        for raw in WORD_RE.findall(chosen):
            words.append({"kind": "word", "raw": raw, "t": item["t"], "seg": item["seg"]})

    grouped: list[dict] = []
    for w in words:
        if grouped and grouped[-1]["seg"] == w["seg"]:
            grouped[-1]["words"].append(w)
        else:
            grouped.append({"seg": w["seg"], "words": [w]})

    final_segments = [
        {
            "start": g["words"][0]["t"],
            "end": g["words"][-1]["t"],
            "text": " ".join(x["raw"] for x in g["words"]),
        }
        for g in grouped
    ]
    return final_segments, audit


def transcribe_both(media_path: str, work_dir: Path) -> dict:
    """Extract audio once, upload to both engines. Returns per-engine segments.

    A missing key or a total engine failure degrades to single-engine with an
    explicit degradation record — it never fails the run silently.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    audio_path = stt.extract_audio(media_path, work_dir / "audio.mp3")
    audio_bytes = audio_path.stat().st_size

    if audio_bytes > stt.MAX_UPLOAD_BYTES:
        duration = stt.audio_duration(audio_path)
        plan = stt.plan_chunks(duration, audio_bytes, stt.MAX_UPLOAD_BYTES)
        chunks = stt.split_audio(audio_path, work_dir / "chunks", plan)
    else:
        chunks = [(audio_path, 0.0)]

    results: dict = {
        "groq": None,
        "openai": None,
        "degradation": [],
        "partial_failures": [],
    }

    def make_transcriber(backend: str, api_key: str):
        # stt.transcribe_chunks skips a failed chunk after logging to stderr
        # only; record the hole here so the sidecar never claims "dual-engine
        # verified" over a holed transcript.
        def transcribe_one(path: Path) -> list[dict]:
            try:
                return stt._transcribe_file(backend, api_key, path)
            except SystemExit as exc:
                results["partial_failures"].append(
                    f"{backend}: chunk {path.name} failed — {exc}"
                )
                raise
        return transcribe_one

    for backend in ("groq", "openai"):
        _, api_key = stt.load_api_key(preferred=backend)
        if not api_key:
            results["degradation"].append(
                f"{backend}: no API key — {ENGINE_SKIPPED}; dual-engine verification does not hold"
            )
            continue
        try:
            segments = stt.transcribe_chunks(chunks, make_transcriber(backend, api_key))
        except SystemExit as exc:
            results["degradation"].append(f"{backend}: {TRANSCRIPTION_FAILED} — {exc}")
            continue
        results[backend] = segments
        print(f"[interview] {backend}: {len(segments)} segments", file=sys.stderr)

    if results["groq"] is None and results["openai"] is None:
        raise SystemExit("Both engines failed or are unconfigured — cannot transcribe")
    return results
