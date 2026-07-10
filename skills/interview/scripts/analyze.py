#!/usr/bin/env python3
"""Deterministic analysis helpers: turns, panel concordance, flag validation,
frame-burst targeting. All pure functions — the LLM judgment that produces
panel labels and gravity flags lives in SKILL.md, not here."""
from __future__ import annotations

from collections import Counter

VALID_LABELS = {"INTERVIEWER", "INTERVIEWEE", "OTHER"}
CONCORDANCE_THRESHOLD = 2 / 3


def build_turns(segments: list[dict], gap_seconds: float = 1.0) -> list[dict]:
    """Group consecutive segments into speaker-turn candidates, split on gaps.

    A turn is the diarization unit: the panel labels turns, not segments.
    """
    turns: list[dict] = []
    for idx, seg in enumerate(segments):
        if turns and float(seg["start"]) - float(turns[-1]["end"]) <= gap_seconds:
            turn = turns[-1]
            turn["text"] = f"{turn['text']} {seg['text']}".strip()
            turn["end"] = float(seg["end"])
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


def compute_concordance(turns: list[dict], panels: list[dict]) -> dict:
    """Merge panel label sets into a final label + concordance score per turn.

    Rules (locked by tests): invalid labels are discarded; fewer than 2 valid
    votes → UNCLEAR; majority below the 2/3 threshold → UNCLEAR. Concordance
    is majority_votes / valid_votes.
    """
    result: dict = {}
    for turn in turns:
        votes = [
            str(p.get(turn["id"], "")).upper()
            for p in panels
            if str(p.get(turn["id"], "")).upper() in VALID_LABELS
        ]
        if len(votes) < 2:
            result[turn["id"]] = {"label": "UNCLEAR", "concordance": 0.0, "votes": len(votes)}
            continue
        label, count = Counter(votes).most_common(1)[0]
        score = count / len(votes)
        if score < CONCORDANCE_THRESHOLD:
            label = "UNCLEAR"
        result[turn["id"]] = {
            "label": label,
            "concordance": round(score, 4),
            "votes": len(votes),
        }
    return result


def validate_flags(flags: list[dict], codebook: dict, duration: float) -> list[str]:
    """Return a list of human-readable schema violations (empty = valid)."""
    errors: list[str] = []
    marker_ids = {m["id"] for m in codebook["markers"]}
    emotions = set(codebook["emotions"])
    required = codebook["flag_schema"]["required"]

    for i, flag in enumerate(flags):
        ref = flag.get("id", f"flags[{i}]")
        for field in required:
            if flag.get(field) in (None, "", []):
                errors.append(f"{ref}: missing required field '{field}'")
        markers = flag.get("marker_types") or []
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
        if not isinstance(salience, int) or not 1 <= salience <= 5:
            errors.append(f"{ref}: salience must be an integer 1-5 (got {salience!r})")
        t_start, t_end = flag.get("t_start"), flag.get("t_end")
        if isinstance(t_start, (int, float)) and isinstance(t_end, (int, float)):
            if t_start > t_end:
                errors.append(f"{ref}: t_start > t_end")
            if t_end > duration + 1.0 or t_start < 0:
                errors.append(f"{ref}: timestamps outside media duration ({duration:.0f}s)")
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
    offsets = [(-spread + 2 * half * i) for i in range(count)]
    points = [min(max(mid + off, 0.0), float(duration)) for off in offsets]
    return sorted(set(round(p, 2) for p in points))
