#!/usr/bin/env python3
"""Deterministic analysis helpers: turns, panel concordance, flag validation,
frame-burst targeting. All pure functions — the LLM judgment that produces
panel labels and gravity flags lives in SKILL.md, not here."""
from __future__ import annotations

from collections import Counter

VALID_LABELS = {"INTERVIEWER", "INTERVIEWEE", "OTHER"}
# Must stay > 0.5: at exactly 0.5 a tie would pass the threshold and the
# winner would depend on Counter insertion order.
CONCORDANCE_THRESHOLD = 2 / 3


def build_turns(segments: list[dict], gap_seconds: float = 1.0) -> list[dict]:
    """Group consecutive segments into speaker-turn candidates, split on gaps.

    A turn is the diarization unit: the panel labels turns, not segments.
    """
    turns: list[dict] = []
    for idx, seg in sorted(enumerate(segments), key=lambda p: (float(p[1]["start"]), float(p[1]["end"]))):
        if turns and float(seg["start"]) - float(turns[-1]["end"]) <= gap_seconds:
            turn = turns[-1]
            turn["text"] = f"{turn['text']} {seg['text']}".strip()
            turn["end"] = max(turn["end"], float(seg["end"]))
            turn["segment_indices"].append(idx)
            continue
        turns.append({
            "id": f"t{len(turns) + 1:04d}",
            "start": float(seg["start"]),
            "end": float(seg["end"]),
            "text": seg["text"].strip(),
            "segment_indices": [idx],
        })
    return turns


def segment_turns(segments: list[dict]) -> list[dict]:
    """One diarization unit per transcript segment (sentence-scale).

    Gap-based grouping under-segments rapid dyadic exchange — speakers often
    alternate with no silence between them, so a single "turn" can swallow
    minutes of both voices. Segment-level units keep the labeling unit small;
    same-label units are merged AFTER concordance (merge_labeled_turns).
    """
    turns: list[dict] = []
    for idx, seg in sorted(enumerate(segments), key=lambda p: (float(p[1]["start"]), float(p[1]["end"]))):
        text = seg["text"].strip()
        if not text:
            continue
        turns.append({
            "id": f"t{len(turns) + 1:04d}",
            "start": float(seg["start"]),
            "end": float(seg["end"]),
            "text": text,
            "segment_indices": [idx],
        })
    return turns


def merge_labeled_turns(turns: list[dict]) -> list[dict]:
    """Merge consecutive same-label units into display turns, post-diarization.

    Turn boundaries are downstream of labeling, not upstream: units carry the
    panel's judgment, and adjacent units sharing a final label collapse into
    one readable turn. A merged turn's concordance is the MINIMUM of its
    members — a turn is only as reliable as its weakest unit.
    """
    merged: list[dict] = []
    for t in turns:
        if merged and merged[-1]["label"] == t["label"]:
            m = merged[-1]
            m["text"] = f"{m['text']} {t['text']}".strip()
            m["end"] = max(m["end"], float(t["end"]))
            m["concordance"] = min(m["concordance"], t["concordance"])
            m["segment_indices"].extend(t["segment_indices"])
            continue
        merged.append({
            "id": f"m{len(merged) + 1:04d}",
            "start": float(t["start"]),
            "end": float(t["end"]),
            "text": t["text"],
            "label": t["label"],
            "concordance": float(t["concordance"]),
            "segment_indices": list(t["segment_indices"]),
        })
    return merged


def compute_concordance(turns: list[dict], panels: list[dict]) -> dict:
    """Merge panel label sets into a final label + concordance score per turn.

    Rules (locked by tests): invalid labels are discarded; fewer than 2 valid
    votes → UNCLEAR; majority below the 2/3 threshold → UNCLEAR. Concordance
    is majority_votes / valid_votes. A turn labeled UNCLEAR by threshold keeps
    the discarded plurality's score — the score describes agreement among
    valid votes, not agreement that the turn is unclear.
    """
    result: dict = {}
    for turn in turns:
        present = [str(p[turn["id"]]).upper() for p in panels if turn["id"] in p]
        votes = [v for v in present if v in VALID_LABELS]
        invalid = len(present) - len(votes)
        if len(votes) < 2:
            result[turn["id"]] = {
                "label": "UNCLEAR",
                "concordance": 0.0,
                "votes": len(votes),
                "invalid": invalid,
            }
            continue
        label, count = Counter(votes).most_common(1)[0]
        score = count / len(votes)
        if score < CONCORDANCE_THRESHOLD:
            label = "UNCLEAR"
        result[turn["id"]] = {
            "label": label,
            "concordance": round(score, 4),
            "votes": len(votes),
            "invalid": invalid,
        }
    return result


def validate_flags(
    flags: list[dict],
    codebook: dict,
    duration: float,
    transcript_text: str | None = None,
) -> list[str]:
    """Return a list of human-readable schema violations (empty = valid).

    When `transcript_text` is provided, every quote must be a verbatim
    substring of it — paraphrased quotes are research-record corruption.
    """
    errors: list[str] = []
    marker_ids = {m["id"] for m in codebook["markers"]}
    emotions = set(codebook["emotions"])
    required = codebook["flag_schema"]["required"]

    for i, flag in enumerate(flags):
        ref = flag.get("id", f"flags[{i}]")
        for field in required:
            if flag.get(field) in (None, "", []):
                errors.append(f"{ref}: missing required field '{field}'")
        quote = flag.get("quote")
        if transcript_text is not None and quote and quote not in transcript_text:
            errors.append(f"{ref}: quote is not a verbatim substring of the transcript")
        markers = flag.get("marker_types")
        if markers in (None, "", []):
            markers = []  # already reported missing by the required-field check
        elif not isinstance(markers, list):
            errors.append(f"{ref}: marker_types must be a list (got {type(markers).__name__})")
            markers = []
        for m in markers:
            if m not in marker_ids:
                errors.append(f"{ref}: unknown marker '{m}'")
        if "emotional_display" in markers:
            emotion = flag.get("emotion")
            if not emotion:
                errors.append(f"{ref}: emotional_display requires an emotion")
            elif emotion not in emotions:
                errors.append(f"{ref}: emotion '{emotion}' not in codebook vocabulary")
        salience = flag.get("salience")
        if not isinstance(salience, int) or isinstance(salience, bool) or not 1 <= salience <= 5:
            errors.append(f"{ref}: salience must be an integer 1-5 (got {salience!r})")
        t_start, t_end = flag.get("t_start"), flag.get("t_end")
        if isinstance(t_start, (int, float)) and isinstance(t_end, (int, float)):
            if t_start > t_end:
                errors.append(f"{ref}: t_start > t_end")
            if t_end > duration + 1.0 or t_start < 0:
                dur_txt = "unknown" if duration == float("inf") else f"{duration:.0f}s"
                errors.append(f"{ref}: timestamps outside media duration ({dur_txt})")

    # Frame extraction keys output dirs by flag id — duplicate ids would
    # silently cross-contaminate each other's visual evidence.
    ids = [f.get("id") for f in flags if f.get("id")]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(f"{dup}: duplicate flag id")
    return errors


def burst_timestamps(
    t_start: float,
    t_end: float,
    duration: float,
    spread: float = 5.0,
    count: int = 5,
) -> list[float]:
    """Five clamped, deduped timestamps centered on the flag-span midpoint."""
    mid = (float(t_start) + float(t_end)) / 2
    half = spread / (count - 1) if count > 1 else 0.0
    offsets = [0.0] if count == 1 else [(-spread + 2 * half * i) for i in range(count)]
    points = [min(max(mid + off, 0.0), float(duration)) for off in offsets]
    return sorted(set(round(p, 2) for p in points))
