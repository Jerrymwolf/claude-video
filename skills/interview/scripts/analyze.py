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

    Non-default path (--unit gap): useful only when speakers leave real
    silence between turns. The default diarization unit is the segment
    (see segment_turns) — rapid dyadic exchange defeats gap splitting.
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
    members — a turn is only as reliable as its weakest unit. UNCLEAR units
    never merge with each other: UNCLEAR means the panel could not assign a
    speaker, so adjacent UNCLEAR units may be different voices.
    """
    missing = [t.get("id", "?") for t in turns
               if "label" not in t or "concordance" not in t]
    if missing:
        raise ValueError(
            f"units missing label/concordance (run concordance first): {', '.join(missing[:5])}"
        )
    merged: list[dict] = []
    for t in turns:
        if merged and merged[-1]["label"] == t["label"] and t["label"] != "UNCLEAR":
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


def _find_quote_turn(flag: dict, turns: list[dict], label: str | None = None) -> dict | None:
    """The turn containing the flag's quote that best matches its timespan.

    Candidates are turns whose text contains the quote (optionally restricted to
    a label) and whose span falls inside the flag's [t_start-2, t_end+2] window
    (mirrors the docx anchor slop). The winner is the candidate with the MOST
    temporal overlap, first match breaking ties: short quotes ("Yeah.", "No.")
    recur constantly in confrontation transcripts, and resolving to a merely
    nearby turn would read the wrong turn's concordance. Falls back to the first
    text-only match when the flag carries no timestamps to anchor with.
    """
    quote = flag.get("quote")
    if not isinstance(quote, str) or not quote:
        return None
    t0, t1 = flag.get("t_start"), flag.get("t_end")
    timed = isinstance(t0, (int, float)) and isinstance(t1, (int, float))
    best: dict | None = None
    # -inf, not 0.0: a candidate inside the +/-2s slop but not truly overlapping
    # has NEGATIVE overlap and must still be selectable — that gap is exactly
    # what the slop exists to tolerate. A 0.0 floor would reject it.
    best_overlap = float("-inf")
    for turn in turns:
        if label is not None and turn.get("label") != label:
            continue
        if quote not in turn["text"]:
            continue
        if not timed:
            return turn
        if t0 > turn["end"] + 2.0 or t1 < turn["start"] - 2.0:
            continue
        overlap = min(t1, turn["end"]) - max(t0, turn["start"])
        if overlap > best_overlap:
            best, best_overlap = turn, overlap
    return best


def validate_flags(
    flags: list[dict],
    codebook: dict,
    duration: float,
    transcript_text: str | None = None,
    turns: list[dict] | None = None,
) -> list[str]:
    """Return a list of human-readable schema violations (empty = valid).

    When `transcript_text` is provided, every quote must be a verbatim
    substring of it — paraphrased quotes are research-record corruption.

    Codebook-declared behavior (every default preserves the shipped
    narrative-gravity codebook exactly):

    - `affect_field` — name of the affect key on each flag. Default "emotion".
    - `affect_vocabulary` — the closed vocabulary for that key. When
      `affect_field` is declared, this is the ONLY source: an `emotions` key
      left behind by copy-editing a narrative codebook is ignored, because a
      stale vocabulary silently admitting the wrong terms is worse than an
      empty one rejecting them. `emotions` is consulted as a fallback only
      when `affect_field` is absent (i.e. the legacy narrative codebook).
      Default: empty.
    - `markers[].requires_affect` / `requires_emotion` — markers demanding a
      value in `affect_field`. Default: not required.
    - `coding_scope` — the labels a flag's `speaker_role` may carry; the quote
      must then be found in a turn bearing that same role. Default
      ["INTERVIEWEE"]. Merely declaring this key turns the check on; so does
      listing `speaker_role` in `flag_schema.required`. Either alone is
      sufficient — the check does not wait for the schema to require the
      field. It runs only on flags that actually carry a `speaker_role`;
      a missing one is reported by the required-field check instead.
    - `enforce_attribution_gate` — demands `attribution_uncertain: true` on
      flags whose quoted turn has concordance < 1.0 or label UNCLEAR, and
      reports a flag whose quote resolves to no turn at all. Default False.

    A codebook declaring `coding_scope` or `enforce_attribution_gate` raises
    without labeled `turns`: those declarations are the author's attribution
    guarantee, and silently skipping them because an optional argument was
    omitted would pass corrupt flags as validated.
    """
    errors: list[str] = []
    marker_ids = {m["id"] for m in codebook["markers"]}
    # An explicitly declared affect_field owns its vocabulary: a codebook
    # copy-edited from the narrative one may still carry a stale `emotions`
    # key, which must not silently become the vocabulary for `affect`.
    affect_field = codebook.get("affect_field", "emotion")
    if "affect_field" in codebook:
        vocab = set(codebook.get("affect_vocabulary") or [])
    else:
        vocab = set(codebook.get("affect_vocabulary") or codebook.get("emotions") or [])
    requiring = {m["id"] for m in codebook["markers"]
                 if m.get("requires_affect") or m.get("requires_emotion")}
    required = codebook["flag_schema"]["required"]
    scope = set(codebook.get("coding_scope", ["INTERVIEWEE"]))
    check_role = "speaker_role" in required or "coding_scope" in codebook
    gate = bool(codebook.get("enforce_attribution_gate"))

    if gate or check_role:
        if turns is None:
            raise ValueError(
                "codebook declares coding_scope/enforce_attribution_gate but no "
                "turns were supplied — turn-level validation cannot be skipped"
            )
        unlabeled = [t.get("id", "?") for t in turns
                     if "label" not in t or "concordance" not in t]
        if unlabeled:
            raise ValueError(
                "turns missing label/concordance (run concordance first): "
                + ", ".join(unlabeled[:5])
            )

    for i, flag in enumerate(flags):
        ref = flag.get("id", f"flags[{i}]")
        for field in required:
            if flag.get(field) in (None, "", []):
                errors.append(f"{ref}: missing required field '{field}'")
        quote = flag.get("quote")
        if quote is not None and not isinstance(quote, str):
            errors.append(f"{ref}: quote must be a string (got {type(quote).__name__})")
            quote = None  # every downstream quote check needs a string
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
        affect_markers = sorted(m for m in markers if m in requiring)
        if affect_markers:
            value = flag.get(affect_field)
            names = ", ".join(affect_markers)
            if not value:
                errors.append(f"{ref}: marker '{names}' requires an {affect_field}")
            elif value not in vocab:
                errors.append(f"{ref}: {affect_field} '{value}' not in codebook vocabulary")
        role = flag.get("speaker_role")
        cited: dict | None = None  # the turn the speaker_role check resolved, if any
        if check_role and role:
            if role not in scope:
                errors.append(f"{ref}: speaker_role '{role}' not in coding scope {sorted(scope)}")
            elif quote:
                cited = _find_quote_turn(flag, turns, label=role)
                if cited is None:
                    errors.append(f"{ref}: no {role} turn near [{flag.get('t_start')}, "
                                  f"{flag.get('t_end')}] contains the quote")
        if gate and quote:
            # Reuse the turn the speaker_role check already resolved — a second,
            # unscoped lookup can legitimately land on a different turn and then
            # gate a correctly-attributed flag against a neighbour's concordance.
            home = cited if cited is not None else _find_quote_turn(flag, turns)
            if home is None:
                errors.append(f"{ref}: quote could not be located in any turn — "
                              f"attribution cannot be verified")
            elif home["label"] == "UNCLEAR" or float(home["concordance"]) < 1.0:
                if flag.get("attribution_uncertain") is not True:
                    reason = ("is labeled UNCLEAR" if home["label"] == "UNCLEAR"
                              else f"has concordance {home['concordance']}")
                    errors.append(f"{ref}: quoted turn {home['id']} {reason} — flag "
                                  f"must set attribution_uncertain: true")
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
