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

    Episodes are a second hard barrier, parallel to the UNCLEAR rule: two units
    carrying DIFFERENT `episode_id`s never merge even when their labels agree.
    The videographer's turns either side of an episode boundary are the same
    speaker but different confrontations, and a merged turn can carry only one
    episode_id — fusing them would refile target B's exchange under target A,
    the exact defect episodes exist to prevent. The barrier is inert when
    `episode_id` is absent, so every pre-episode caller is unaffected. A merged
    turn claims an episode_id only when EVERY member carried the same one.
    """
    missing = [t.get("id", "?") for t in turns
               if "label" not in t or "concordance" not in t]
    if missing:
        raise ValueError(
            f"units missing label/concordance (run concordance first): {', '.join(missing[:5])}"
        )
    merged: list[dict] = []
    prev_ep = None
    for t in turns:
        ep = t.get("episode_id")
        crosses = prev_ep is not None and ep is not None and ep != prev_ep
        if (merged and merged[-1]["label"] == t["label"]
                and t["label"] != "UNCLEAR" and not crosses):
            m = merged[-1]
            m["text"] = f"{m['text']} {t['text']}".strip()
            m["end"] = max(m["end"], float(t["end"]))
            m["concordance"] = min(m["concordance"], t["concordance"])
            m["segment_indices"].extend(t["segment_indices"])
            # An unannotated member makes the claim unprovable — drop it rather
            # than let one member's id speak for units that never carried one.
            if ep is None or m.get("episode_id") != ep:
                m.pop("episode_id", None)
            prev_ep = ep
            continue
        new = {
            "id": f"m{len(merged) + 1:04d}",
            "start": float(t["start"]),
            "end": float(t["end"]),
            "text": t["text"],
            "label": t["label"],
            "concordance": float(t["concordance"]),
            "segment_indices": list(t["segment_indices"]),
        }
        if ep is not None:
            new["episode_id"] = ep
        merged.append(new)
        prev_ep = ep
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
    a label) and whose span INTERSECTS the flag's [t_start-2, t_end+2] window —
    overlapping it anywhere is enough; the turn need not be contained in it
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
      field. A flag omitting `speaker_role` entirely is still reported —
      by the required-field check when the schema requires it, otherwise by
      the scope check itself, so declaring `coding_scope` alone is enough to
      make an unattributed flag a finding.
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
        if check_role and not role and "speaker_role" not in required:
            # `coding_scope` is a declaration that speaker attribution matters.
            # Without this, a flag that simply omits `speaker_role` is checked by
            # neither the scope check nor the required-field check, and a quote
            # from an out-of-scope speaker validates clean. The `not in required`
            # guard avoids double-reporting the schema's own missing-field error.
            errors.append(f"{ref}: codebook declares coding_scope but flag has "
                          f"no speaker_role")
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


EPISODE_TYPES = {"confrontation", "commendation", "bystander", "to-camera"}
EPISODE_REQUIRED = ("id", "type", "t_start", "t_end")
EPISODE_CONFRONTATION_REQUIRED = ("target_descriptor", "target_speech")
ARC_PHASES = {"threat", "defense", "escalation", "softening", "flip", "repair", "exit"}
ARC_OUTCOMES = {"complies", "refuses", "escalates", "partial", "n/a"}
MAX_LISTED = 5


def _is_num(value: object) -> bool:
    """A real number, excluding bool. `"t_start": false` must not read as 0.0
    (mirrors the salience check in validate_flags)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _capped(items: list[str], label: str) -> list[str]:
    """One summary line per problem class, listing at most MAX_LISTED examples.

    episodes.json is LLM-authored: a single mistyped timestamp orphans EVERY
    turn, and hundreds of identical lines bury the one cause under its effects.
    Mirrors how validate_flags caps its unlabeled-turn list.
    """
    if not items:
        return []
    more = f" (+{len(items) - MAX_LISTED} more)" if len(items) > MAX_LISTED else ""
    return [f"{len(items)} {label}: {', '.join(items[:MAX_LISTED])}{more}"]


def _episode_required(codebook: dict | None) -> tuple[tuple, tuple]:
    """Required episode fields, preferring the codebook's declaration.

    Same contract as _episode_enums, and for the same reason: the file that
    defines the construct declares which fields it demands, so adding one to
    `episode_schema.required` actually enforces it instead of being silently
    ignored by a second copy in Python. Mirrors validate_flags reading
    `flag_schema.required`.
    """
    schema = (codebook or {}).get("episode_schema") or {}
    return (
        tuple(schema.get("required") or EPISODE_REQUIRED),
        tuple(schema.get("confrontation_required") or EPISODE_CONFRONTATION_REQUIRED),
    )


def _episode_enums(codebook: dict | None) -> tuple[set, set, set]:
    """Episode/arc enums, preferring the codebook's declaration.

    The constants above are the fallback for codebooks that declare no episode
    schema (the shipped narrative-gravity codebook). Reading the codebook first
    keeps this consistent with validate_flags: behavior is driven by the file
    that defines the construct, not by a second copy hidden in Python.
    """
    cb = codebook or {}
    ep = set((cb.get("episode_schema") or {}).get("types") or EPISODE_TYPES)
    arc = cb.get("arc_schema") or {}
    return ep, set(arc.get("phases") or ARC_PHASES), set(arc.get("outcomes") or ARC_OUTCOMES)


def _containing_episode(t: float, episodes: list[dict]) -> dict | None:
    """Half-open containment [t_start, t_end) so a time exactly on a shared
    boundary belongs to the LATER episode; the final episode is end-inclusive
    so the recording's last turn is never orphaned."""
    for i, e in enumerate(episodes):
        t0, t1 = e.get("t_start"), e.get("t_end")
        if not (_is_num(t0) and _is_num(t1)):
            continue
        last = i == len(episodes) - 1
        if t0 <= t < t1 or (last and t == t1):
            return e
    return None


def validate_episodes(
    episodes: list[dict], turns: list[dict], codebook: dict | None = None
) -> list[str]:
    """Return human-readable violations (empty = valid).

    Episodes are ordered, non-overlapping time spans. Gaps BETWEEN episodes are
    legal (silent B-roll holds no turns); coverage is enforced over turns —
    every turn's start must fall inside exactly one episode, and a turn whose
    END lands in a different episode is reported as straddling: that is a
    mis-drawn boundary, and authoring time is the only point at which the
    researcher can still fix it. Arc objects are optional; when present their
    enums are checked (turning_point may be a turn id or the literal
    "off-camera" — arcs can turn before the camera ran).

    Required fields and the episode/arc enums are read from the codebook
    (`episode_schema`, `arc_schema`); the module constants are only the
    fallback for codebooks that declare no episode schema.
    """
    errors: list[str] = []
    episode_types, arc_phases, arc_outcomes = _episode_enums(codebook)
    required, confrontation_required = _episode_required(codebook)
    if not isinstance(episodes, list) or not episodes:
        return ["episodes.json must be a non-empty array"]
    ids = [e.get("id") for e in episodes]
    for dup in sorted({i for i in ids if i and ids.count(i) > 1}):
        errors.append(f"{dup}: duplicate episode id")
    prev_start, prev_end, prev_id = None, None, None
    for i, e in enumerate(episodes):
        ref = e.get("id", f"episodes[{i}]")
        for field in required:
            if e.get(field) in (None, ""):
                errors.append(f"{ref}: missing required field '{field}'")
        etype = e.get("type")
        if etype and etype not in episode_types:
            errors.append(f"{ref}: unknown type '{etype}' (valid: {sorted(episode_types)})")
        t0, t1 = e.get("t_start"), e.get("t_end")
        # Timestamps are authored from a video clock, so "0:00"/"00:01:40" is a
        # likely failure. Say so once, here — otherwise the only symptom is
        # every turn reporting that it falls in no episode.
        for field, value in (("t_start", t0), ("t_end", t1)):
            if value not in (None, "") and not _is_num(value):
                errors.append(f"{ref}: {field} must be a number (got {value!r})")
        if _is_num(t0) and _is_num(t1):
            if t0 > t1:
                errors.append(f"{ref}: t_start > t_end")
            if prev_end is not None and t0 < prev_end:
                if prev_start is not None and t1 <= prev_start:
                    errors.append(f"{ref}: out of order — spans {t0}-{t1}, entirely before "
                                  f"{prev_id} which starts at {prev_start}")
                else:
                    errors.append(f"{ref}: overlaps {prev_id} (starts at {t0} before its end {prev_end})")
            prev_start, prev_end, prev_id = t0, t1, ref
        if etype == "confrontation":
            for field in confrontation_required:
                if field == "target_speech":
                    # a per-field TYPE rule: the target either spoke or did not
                    if not isinstance(e.get(field), bool):
                        errors.append(f"{ref}: target_speech must be true/false")
                elif not str(e.get(field) or "").strip():
                    errors.append(f"{ref}: confrontation requires a {field}")
        arc = e.get("arc")
        if arc is not None:
            if not isinstance(arc, dict):
                errors.append(f"{ref}: arc must be an object (got {type(arc).__name__})")
            else:
                phases = arc.get("phases", [])
                if not isinstance(phases, list):
                    # a bare string would iterate as characters, reporting six
                    # "unknown arc phase" errors for one mistyped "threat"
                    errors.append(f"{ref}: arc.phases must be a list "
                                  f"(got {type(phases).__name__})")
                    phases = []
                for ph in phases:
                    if ph not in arc_phases:
                        errors.append(f"{ref}: unknown arc phase '{ph}'")
                outcome = arc.get("outcome")
                if outcome is not None and outcome not in arc_outcomes:
                    errors.append(f"{ref}: unknown arc outcome '{outcome}'")
                tp = arc.get("turning_point")
                if tp is not None and not isinstance(tp, str):
                    errors.append(f"{ref}: turning_point must be a turn id, 'off-camera', or null")
    orphans: list[str] = []
    straddlers: list[str] = []
    for t in turns:
        tid = t.get("id", "?")
        start, end = t.get("start"), t.get("end")
        if not _is_num(start):
            errors.append(f"{tid}: start must be a number (got {start!r})")
            continue
        home = _containing_episode(float(start), episodes)
        if home is None:
            orphans.append(f"{tid} (start {start})")
            continue
        if _is_num(end):
            tail = _containing_episode(float(end), episodes)
            if tail is not None and tail is not home:
                straddlers.append(f"{tid} ({home.get('id')} → {tail.get('id')})")
    errors.extend(_capped(orphans, "turn(s) fall in no episode"))
    errors.extend(_capped(straddlers, "turn(s) straddle an episode boundary"))
    return errors


def assign_episode_ids(turns: list[dict], episodes: list[dict]) -> list[dict]:
    """Stamp episode_id onto each turn by start-time containment (in place).
    Call only after validate_episodes returns clean — assumes full coverage."""
    for t in turns:
        home = _containing_episode(float(t["start"]), episodes)
        if home is None:
            raise ValueError(f"{t.get('id', '?')}: start {t['start']} falls in no episode")
        t["episode_id"] = home["id"]
    return turns


def assign_flag_episodes(flags: list[dict], episodes: list[dict]) -> list[str]:
    """Stamp episode_id onto each flag by t_start containment (in place).

    Returns errors for flags outside every episode instead of raising — flag
    placement is a judgment product and its errors go back to the coder. Every
    flag is annotated either way: an unplaceable flag gets an explicit
    `episode_id: None`, because the list is mutated before the caller sees the
    errors and a caller that persists on the error path must not write a record
    where a missing key is indistinguishable from an unassigned one.

    A flag whose t_end lands in a different episode is reported as straddling
    and filed under its t_start's episode — a boundary drawn through a flag is
    a research-record problem, not something to resolve silently.
    """
    errors: list[str] = []
    for f in flags:
        ref = f.get("id", "?")
        t_start, t_end = f.get("t_start"), f.get("t_end")
        if not _is_num(t_start):
            f["episode_id"] = None
            errors.append(f"{ref}: t_start must be a number (got {t_start!r})")
            continue
        home = _containing_episode(float(t_start), episodes)
        if home is None:
            f["episode_id"] = None
            errors.append(f"{ref}: t_start {t_start} outside every episode")
            continue
        f["episode_id"] = home["id"]
        if _is_num(t_end):
            tail = _containing_episode(float(t_end), episodes)
            if tail is not None and tail is not home:
                errors.append(f"{ref}: straddles episodes {home['id']} → {tail['id']} "
                              f"(t_start {t_start}, t_end {t_end}); filed under {home['id']}")
    return errors
