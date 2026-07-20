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
# Dereferenced unconditionally downstream (assign_episode_ids, the CLI summary),
# so no codebook may narrow them away. See _episode_required.
EPISODE_STRUCTURAL = ("id", "t_start", "t_end")
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

    EPISODE_STRUCTURAL is the exception, and it is unioned in rather than
    overridable: `id`/`t_start`/`t_end` are invariants of the DATA MODEL, not
    codebook policy. assign_episode_ids dereferences `home["id"]` and the CLI
    summary prints `e['t_start']`, so a codebook declaring `"required": ["type"]`
    would otherwise validate clean and then crash with KeyError two lines later.
    A codebook may ADD required fields; it may never remove the ones the
    pipeline is built on.
    """
    schema = (codebook or {}).get("episode_schema") or {}
    declared = tuple(schema.get("required") or EPISODE_REQUIRED)
    required = declared + tuple(f for f in EPISODE_STRUCTURAL if f not in declared)
    return (
        required,
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


def _episodes_starting_inside(start: float, end: float, episodes: list[dict]) -> list[dict]:
    """Episodes whose t_start lies in (start, end) — EXCLUSIVE at both ends.

    Both bounds are load-bearing. Exclusive at the top: episodes are authored by
    snapping to turn boundaries, and half-open containment puts the boundary
    instant in the LATER episode, so a turn ending exactly at the next episode's
    t_start holds none of its content — an inclusive bound would report every
    correctly-drawn boundary. Exclusive at the bottom: a span that OPENS an
    episode must not read as straddling into it.

    This is the straddle test, and it deliberately is NOT "does the span's end
    resolve to a different episode". A span ending in a GAP resolves to no
    episode at all, so `e01(0-100), e02(100-120), gap, e03(130-200)` with a turn
    at 50-125 reported nothing while completely swallowing e02 — a whole
    separate confrontation with a different target, silently filed under e01.
    Asking which episodes the span *begins inside itself* catches that case and
    the ordinary two-episode straddle with one predicate.

    A span that merely overruns the FINAL episode's end (195-205 against a last
    episode ending at 200) begins no episode, so it stays silent: there is no
    competing episode there and its episode_id is unambiguous. That trailing
    overrun is the common, harmless case and must not become a finding.

    The span's own home episode can never appear here — containment gives
    `home.t_start <= start`, which cannot also be strictly greater than start —
    so no "is not home" filter is needed (it would be an unreachable branch).
    """
    return [e for e in episodes
            if _is_num(e.get("t_start")) and start < float(e["t_start"]) < end]


def validate_episodes(
    episodes: list[dict], turns: list[dict], codebook: dict | None = None
) -> list[str]:
    """Return human-readable violations (empty = valid).

    Episodes are ordered, non-overlapping time spans. Gaps BETWEEN episodes are
    legal (silent B-roll holds no turns); coverage is enforced over turns —
    every turn's start must fall inside exactly one episode, and a turn that
    spans the START of any other episode is reported as straddling (see
    _episodes_starting_inside): that is a mis-drawn boundary, and authoring time is the
    only point at which the researcher can still fix it. Arc objects are
    optional; when present their enums are checked (turning_point may be a turn
    id or the literal "off-camera" — arcs can turn before the camera ran).

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
            crossed = _episodes_starting_inside(float(start), float(end), episodes)
            if crossed:
                names = ", ".join(str(e.get("id")) for e in crossed)
                straddlers.append(f"{tid} ({home.get('id')} → {names})")
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

    A flag that spans the START of any other episode is reported as straddling
    (same predicate as validate_episodes — see _episodes_starting_inside) and
    filed under its t_start's episode: a boundary drawn through a flag is a
    research-record problem, not something to resolve silently.
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
            crossed = _episodes_starting_inside(float(t_start), float(t_end), episodes)
            if crossed:
                names = ", ".join(str(e.get("id")) for e in crossed)
                errors.append(f"{ref}: straddles episodes {home['id']} → {names} "
                              f"(t_start {t_start}, t_end {t_end}); filed under {home['id']}")
    return errors


def episode_drift(turns: list[dict], episodes: list[dict]) -> list[str]:
    """Display turns whose stamped episode_id no longer matches containment.

    Flags are stamped from episodes.json at validate-flags time, while turns
    were stamped at validate-episodes time. Nothing forces those two reads to
    be of the same file: a researcher re-draws a boundary and re-runs only
    validate-flags — exactly the between-stages hand-editing this layer exists
    for — and the two layers silently disagree. Under a codebook where episodes
    are different PEOPLE, a flag then quotes a turn filed under one target and
    is itself filed under another: the misattribution episodes exist to prevent.

    The invariant is exact, not approximate. The merge barrier guarantees a
    display turn never spans an episode, so its stamp must equal containment of
    its own start — anything else, including a MISSING stamp (a turn whose units
    disagreed, or a turn layer that was never annotated at all), is drift.
    """
    out: list[str] = []
    for t in turns:
        home = _containing_episode(float(t["start"]), episodes)
        want = home["id"] if home else None
        if t.get("episode_id") != want:
            out.append(f"{t.get('id', '?')} (stamped {t.get('episode_id')!r}, "
                       f"now falls in {want!r})")
    return _capped(out, "display turn(s) out of sync with episodes.json — "
                        "re-run validate-episodes")


def sidecar_codebook(sidecar: dict) -> str:
    """Which codebook a sidecar was coded against.

    Schema 1.1+ always records `codebook_file`. Pre-1.1 sidecars predate the
    field, and absence there legitimately means the shipped codebook — that
    inference is only valid below 1.1, which is why schema_version gates it
    rather than absence alone.
    """
    name = sidecar.get("codebook_file")
    if name:
        return str(name)
    return "codebook.json" if sidecar.get("schema_version", "1.0") == "1.0" else "unknown"


def summarize_corpus(sidecars: list[dict]) -> dict:
    """Aggregate per-interview sidecars into corpus counts.

    Works on both sidecar generations: pre-episode sidecars contribute marker
    and affect counts only (`emotion` is read as the affect fallback); episode
    sidecars additionally feed outcome counts and the marker x outcome
    cross-tab (keys "marker|outcome"), which counts only flags inside episodes
    carrying an arc outcome.

    Marker vocabularies are codebook-specific, so a corpus spanning more than
    one codebook sets `mixed_constructs` — the flat counts are then a sum over
    incompatible vocabularies and must not be read as one distribution.
    """
    by_marker: Counter = Counter()
    by_affect: Counter = Counter()
    outcomes: Counter = Counter()
    cross: Counter = Counter()
    personas: list[str] = []
    codebooks: Counter = Counter()
    rows: list[dict] = []
    for sc in sidecars:
        flags = sc.get("flags", [])
        episodes = sc.get("episodes", [])
        codebook = sidecar_codebook(sc)
        codebooks[codebook] += 1
        ep_outcome = {e["id"]: (e.get("arc") or {}).get("outcome")
                      for e in episodes if isinstance(e, dict) and e.get("id")}
        for f in flags:
            for m in f.get("marker_types", []):
                by_marker[m] += 1
            affect = f.get("affect") or f.get("emotion")
            if affect:
                by_affect[affect] += 1
            outcome = ep_outcome.get(f.get("episode_id"))
            if outcome:
                for m in f.get("marker_types", []):
                    cross[f"{m}|{outcome}"] += 1
        for e in episodes:
            if isinstance(e, dict) and e.get("type") == "confrontation":
                oc = (e.get("arc") or {}).get("outcome")
                if oc:
                    outcomes[oc] += 1
        persona = sc.get("interview", {}).get("persona")
        if persona:
            personas.append(persona)
        rows.append({"media": sc["interview"]["media"], "flags": len(flags),
                     "episodes": len(episodes), "codebook": codebook,
                     "claim": sc["accuracy_claim"]})
    return {"interviews": len(rows), "per_interview": rows,
            "codebooks": dict(codebooks),
            "mixed_constructs": len(codebooks) > 1,
            "flags_by_marker": dict(by_marker), "flags_by_affect": dict(by_affect),
            "episode_outcomes": dict(outcomes), "marker_by_outcome": dict(cross),
            "personas": personas}
