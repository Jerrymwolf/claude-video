# /interview Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a self-contained `skills/interview/` skill that ingests social-science interview recordings and produces a dual-engine-verified, speaker-diarized transcript with narrative-gravity flags — as a .docx with anchored comments plus a JSON sidecar. Spec: https://github.com/Jerrymwolf/claude-video/issues/1

**Architecture:** Deterministic pure-stdlib Python does everything mechanical (dual Whisper transcription, word-level diff, concordance math, frame bursts, OOXML rendering); all LLM judgment (diff adjudication, 3-analyst diarization panel, gravity codebook pass) lives in SKILL.md as Claude workflow steps that exchange JSON files with the scripts through a per-interview work directory. The skill folder is fully self-contained per AGENTS.md: the Whisper client and frame helpers are *copied* from `skills/watch/` under non-colliding module names (`stt.py`, `framegrab.py`), never imported across skill folders.

**Tech Stack:** Python 3.10+ stdlib only, ffmpeg/ffprobe, Groq `whisper-large-v3` + OpenAI `whisper-1` REST APIs, pytest (existing suite conventions: ffmpeg-synthesized fixtures, no network).

**Repo conventions that bind this plan (from AGENTS.md):** skill = one self-contained folder; SKILL.md resolves `SKILL_DIR` as the directory of the SKILL.md just Read (never `${CLAUDE_SKILL_DIR}`); no `commands/` wrapper — `/interview` derives from SKILL.md frontmatter (`name: interview`, `user-invocable: true`); never touch `skills/watch/`.

**File structure locked in by this plan:**

```
skills/interview/
├── SKILL.md                      # skill contract + all Claude-side judgment steps
└── scripts/
    ├── interview.py              # CLI entry: subcommands preflight|discover|transcribe|finalize|concordance|validate-flags|frames|render|corpus-summary
    ├── dual_transcribe.py        # dual-engine orchestration + PURE CORES: words_with_times, diff_transcripts, apply_adjudications
    ├── analyze.py                # PURE CORES: build_turns, compute_concordance, validate_flags, burst_timestamps
    ├── render.py                 # PURE CORES: build_docx_parts, write_docx, build_sidecar
    ├── codebook.json             # versioned narrative-gravity codebook (the construct definition)
    ├── stt.py                    # verbatim copy of skills/watch/scripts/whisper.py
    └── framegrab.py              # subset copy of skills/watch/scripts/frames.py (extract_at_timestamps + helpers)
tests/
├── conftest.py                   # MODIFY: add interview scripts dir to sys.path
├── test_interview_diff.py        # diff engine + adjudication application
├── test_interview_concordance.py # turn building + concordance + flag validation + burst timestamps
└── test_interview_render.py      # docx XML assertions + sidecar schema
```

Per-interview working layout produced at runtime (all retained — evidence policy):

```
<media_dir>/<stem>_interview/
├── transcript.docx               # deliverable 1
├── sidecar.json                  # deliverable 2
├── frames/<flag_id>/cue_*.jpg    # flag evidence bursts
└── work/                         # every intermediate, kept for audit
    ├── groq.json  openai.json  diff.json  adjudications.json
    ├── final_transcript.json  turns.json  panel_1.json  panel_2.json  panel_3.json
    ├── diarized.json  flags.json
```

---

## Task 1: Scaffold the skill folder (copied plumbing + codebook)

**Files:**
- Create: `skills/interview/scripts/stt.py` (copy)
- Create: `skills/interview/scripts/framegrab.py`
- Create: `skills/interview/scripts/codebook.json`

- [ ] **Step 1: Copy the Whisper client verbatim**

```bash
mkdir -p skills/interview/scripts
cp skills/watch/scripts/whisper.py skills/interview/scripts/stt.py
```

Do not edit `stt.py`. It is pure stdlib and self-contained; keeping it byte-identical to upstream makes provenance obvious and future upstream diffs trivial. The functions used later: `load_api_key(preferred)`, `extract_audio`, `audio_duration`, `plan_chunks`, `split_audio`, `transcribe_chunks`, `_transcribe_file`, `MAX_UPLOAD_BYTES`.

- [ ] **Step 2: Create `skills/interview/scripts/framegrab.py`**

A subset copy of `skills/watch/scripts/frames.py` — only what flag bursts need. Copy these functions **verbatim from frames.py** into a new file with this header (keeping their existing bodies exactly as they appear in `skills/watch/scripts/frames.py`): `parse_time` (frames.py:55), `format_time` (frames.py:77), `get_metadata` (frames.py:86), `_scale_filter` (frames.py:42), `_even_indices` (frames.py:283), `extract_at_timestamps` (frames.py:324).

```python
#!/usr/bin/env python3
"""Frame extraction helpers for the /interview skill.

Subset copy of skills/watch/scripts/frames.py (see that file for full context).
Copied, not imported: each skill folder must stay self-contained so installers
can copy it as a unit (AGENTS.md). Only timestamp-pinned extraction is needed
here — interviews never use scene/keyframe scanning.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

# ... paste the six functions listed above, unmodified ...
```

- [ ] **Step 3: Verify the copy imports cleanly**

Run: `python3 -c "import sys; sys.path.insert(0, 'skills/interview/scripts'); import stt, framegrab; print(framegrab.parse_time('2:15'), stt.MAX_UPLOAD_BYTES)"`
Expected: `135.0 25165824`

- [ ] **Step 4: Create `skills/interview/scripts/codebook.json`**

This file IS the narrative-gravity construct — versioned so any analysis run can cite the exact definition used.

```json
{
  "codebook_version": "1.0.0",
  "construct": "Narrative gravity: a moment in the interviewee's telling that carries unusual analytic weight, marked by one or more observable discourse markers.",
  "salience_scale": {
    "1": "Marker present but incidental; does not shape the surrounding narrative.",
    "2": "Marker colors the passage but the narrative would read the same without it.",
    "3": "Marker meaningfully shapes how the passage should be interpreted.",
    "4": "Marker dominates the passage; the moment is a clear analytic anchor.",
    "5": "Marker defines the interview; a moment the analysis cannot ignore."
  },
  "emotions": [
    "anger", "sadness", "excitement", "fear", "joy", "surprise",
    "disgust", "shame", "pride", "grief", "anxiety", "frustration",
    "relief", "contempt"
  ],
  "markers": [
    {
      "id": "emotional_display",
      "name": "Emotional display",
      "definition": "The interviewee's language, delivery (as evident in wording/disfluency), or visible expression indicates a felt emotion tied to the content being narrated.",
      "indicators": ["explicit emotion words about self", "exclamations", "voice-adjacent text cues (e.g. transcribed laughter, sighs)", "abrupt intensifiers", "visible affect in frames"],
      "requires_emotion": true
    },
    {
      "id": "repetition",
      "name": "Repetition",
      "definition": "The interviewee returns to the same event, phrase, or claim more than once without being re-asked.",
      "indicators": ["near-verbatim phrase recurrence", "same episode retold", "self-quoting of an earlier answer"],
      "requires_emotion": false
    },
    {
      "id": "quoted_speech",
      "name": "Direct quoted speech",
      "definition": "The interviewee re-enacts dialogue rather than reporting it ('and he said to me, ...').",
      "indicators": ["reported dialogue framing verbs", "first-person re-enactment", "shift into another's voice"],
      "requires_emotion": false
    },
    {
      "id": "temporal_shift",
      "name": "Tense/temporal shift",
      "definition": "The telling breaks timeline: a jump into historic present, a flash-forward/backward, or collapsed time marking heightened involvement.",
      "indicators": ["past narrative shifting into present tense", "sudden time jumps mid-episode", "conflation of then and now"],
      "requires_emotion": false
    },
    {
      "id": "disfluency_cluster",
      "name": "Disfluency cluster",
      "definition": "A localized spike in false starts, restarts, fillers, or trailing off, unusual against the speaker's own baseline fluency.",
      "indicators": ["stacked false starts", "mid-word abandonment", "uncharacteristic filler density", "sentence left hanging"],
      "requires_emotion": false
    },
    {
      "id": "pause_then_rush",
      "name": "Pause-then-rush",
      "definition": "A marked silence followed by unusually rapid or dense speech, visible in the segment timing as a long inter-segment gap followed by high word density.",
      "indicators": ["long gap between segments mid-answer", "burst of tightly packed speech after a gap"],
      "requires_emotion": false
    }
  ],
  "flag_schema": {
    "required": ["id", "marker_types", "quote", "t_start", "t_end", "salience"],
    "optional": ["emotion", "note", "frame_paths", "visual_evidence"],
    "rules": [
      "id: 'g' + 4-digit sequence, e.g. g0001",
      "marker_types: non-empty list of marker ids from this codebook",
      "emotion: required iff marker_types includes emotional_display; must be from the emotions list",
      "quote: verbatim substring of the final transcript (the interviewee's words only)",
      "t_start/t_end: seconds, within media duration, t_start <= t_end",
      "salience: integer 1-5 per salience_scale",
      "visual_evidence: one of corroborates|contradicts|neutral, plus a short note — set only after frames are read"
    ]
  }
}
```

- [ ] **Step 5: Validate the JSON parses**

Run: `python3 -c "import json; cb = json.load(open('skills/interview/scripts/codebook.json')); print(cb['codebook_version'], len(cb['markers']), len(cb['emotions']))"`
Expected: `1.0.0 6 14`

- [ ] **Step 6: Commit**

```bash
git add skills/interview/
git commit -m "feat(interview): scaffold skill folder — copied stt/framegrab plumbing + gravity codebook v1.0.0"
```

---

## Task 2: Diff engine (pure core of the accuracy claim)

**Files:**
- Create: `tests/test_interview_diff.py`
- Create: `skills/interview/scripts/dual_transcribe.py`
- Modify: `tests/conftest.py` (add interview scripts to sys.path)

- [ ] **Step 1: Add the interview scripts dir to the shared conftest**

In `tests/conftest.py`, directly below the existing `sys.path.insert(0, str(SCRIPTS_DIR))` line, add:

```python
# Interview skill scripts — distinct module names, so both dirs can coexist.
INTERVIEW_SCRIPTS_DIR = (
    Path(__file__).resolve().parent.parent / "skills" / "interview" / "scripts"
)
sys.path.insert(0, str(INTERVIEW_SCRIPTS_DIR))
```

(Module names were chosen to avoid collisions: watch owns `whisper/config/frames/transcribe`; interview owns `stt/framegrab/dual_transcribe/analyze/render/interview`.)

- [ ] **Step 2: Write the failing tests**

Create `tests/test_interview_diff.py`:

```python
"""Diff engine: word alignment across two Whisper outputs + adjudication apply."""
from __future__ import annotations

import pytest

from dual_transcribe import (
    apply_adjudications,
    diff_transcripts,
    normalize_token,
    words_with_times,
)


def seg(start, end, text):
    return {"start": start, "end": end, "text": text}


class TestWordsWithTimes:
    def test_interpolates_word_times_across_segment(self):
        words = words_with_times([seg(10.0, 14.0, "one two three four")])
        assert [w["raw"] for w in words] == ["one", "two", "three", "four"]
        assert [w["t"] for w in words] == [10.0, 11.0, 12.0, 13.0]
        assert all(w["seg"] == 0 for w in words)

    def test_normalization_strips_punct_and_case(self):
        assert normalize_token("Hello,") == "hello"
        assert normalize_token("didn't") == "didn't"
        assert normalize_token("(WOW)") == "wow"


class TestDiffTranscripts:
    def test_identical_inputs_produce_no_disagreements(self):
        a = [seg(0.0, 2.0, "I walked into the room")]
        result = diff_transcripts(a, a)
        assert result["disagreements"] == []
        assert [w["raw"] for w in result["stream"]] == ["I", "walked", "into", "the", "room"]

    def test_case_and_punct_differences_are_agreements_with_groq_surface(self):
        groq = [seg(0.0, 2.0, "Hello, world today")]
        openai = [seg(0.0, 2.0, "hello world today")]
        result = diff_transcripts(groq, openai)
        assert result["disagreements"] == []
        assert [w["raw"] for w in result["stream"]] == ["Hello,", "world", "today"]

    def test_substitution_becomes_disagreement_with_both_readings(self):
        groq = [seg(0.0, 3.0, "she felt very ecstatic about it")]
        openai = [seg(0.0, 3.0, "she felt very static about it")]
        result = diff_transcripts(groq, openai)
        assert len(result["disagreements"]) == 1
        d = result["disagreements"][0]
        assert d["id"] == "d0001"
        assert d["groq_text"] == "ecstatic"
        assert d["openai_text"] == "static"
        assert d["context_before"].endswith("very")
        assert d["context_after"].startswith("about")
        gaps = [item for item in result["stream"] if item["kind"] == "gap"]
        assert [g["id"] for g in gaps] == ["d0001"]

    def test_insertion_on_openai_side_yields_empty_groq_text(self):
        groq = [seg(0.0, 2.0, "we went home")]
        openai = [seg(0.0, 2.0, "we all went home")]
        result = diff_transcripts(groq, openai)
        assert len(result["disagreements"]) == 1
        d = result["disagreements"][0]
        assert d["groq_text"] == ""
        assert d["openai_text"] == "all"

    def test_disagreement_carries_time_estimate(self):
        groq = [seg(10.0, 12.0, "alpha beta gamma delta")]
        openai = [seg(10.0, 12.0, "alpha beta gomma delta")]
        result = diff_transcripts(groq, openai)
        d = result["disagreements"][0]
        assert 10.0 <= d["t_start"] <= 12.0
        assert d["t_start"] <= d["t_end"]


class TestApplyAdjudications:
    def _diffed(self):
        groq = [seg(0.0, 3.0, "she felt very ecstatic about it")]
        openai = [seg(0.0, 3.0, "she felt very static about it")]
        return diff_transcripts(groq, openai)

    def test_missing_decision_raises(self):
        r = self._diffed()
        with pytest.raises(ValueError, match="d0001"):
            apply_adjudications(r["stream"], r["disagreements"], {})

    def test_decision_text_is_spliced_into_final_segments(self):
        r = self._diffed()
        decisions = {"d0001": {"text": "ecstatic", "rationale": "context: felt very X about"}}
        segments, audit = apply_adjudications(r["stream"], r["disagreements"], decisions)
        assert len(segments) == 1
        assert segments[0]["text"] == "she felt very ecstatic about it"
        assert segments[0]["start"] == 0.0
        assert len(audit) == 1
        assert audit[0]["id"] == "d0001"
        assert audit[0]["chosen_text"] == "ecstatic"
        assert audit[0]["groq_text"] == "ecstatic"
        assert audit[0]["openai_text"] == "static"
        assert audit[0]["rationale"] == "context: felt very X about"

    def test_empty_decision_text_deletes_the_span(self):
        groq = [seg(0.0, 2.0, "we um went home")]
        openai = [seg(0.0, 2.0, "we went home")]
        r = diff_transcripts(groq, openai)
        decisions = {r["disagreements"][0]["id"]: {"text": "", "rationale": "filler; openai right"}}
        segments, _ = apply_adjudications(r["stream"], r["disagreements"], decisions)
        assert segments[0]["text"] == "we went home"

    def test_segments_regroup_across_original_boundaries(self):
        groq = [seg(0.0, 2.0, "first segment here"), seg(3.0, 5.0, "second segment there")]
        openai = [seg(0.0, 2.0, "first segment here"), seg(3.0, 5.0, "second segment there")]
        r = diff_transcripts(groq, openai)
        segments, audit = apply_adjudications(r["stream"], r["disagreements"], {})
        assert len(segments) == 2
        assert segments[0]["text"] == "first segment here"
        assert segments[1]["text"] == "second segment there"
        assert audit == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_interview_diff.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'dual_transcribe'`

- [ ] **Step 4: Implement the pure core in `skills/interview/scripts/dual_transcribe.py`**

```python
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


def normalize_token(raw: str) -> str:
    """Lowercase and strip punctuation (keeping intra-word apostrophes)."""
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
                "key": normalize_token(raw),
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
        else:  # degenerate; anchor to the previous kept word
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

    results: dict = {"groq": None, "openai": None, "degradation": []}
    for backend in ("groq", "openai"):
        found, api_key = stt.load_api_key(preferred=backend)
        if not api_key:
            results["degradation"].append(
                f"{backend}: no API key — engine skipped; dual-engine verification does not hold"
            )
            continue
        try:
            segments = stt.transcribe_chunks(
                chunks, lambda p, b=backend, k=api_key: stt._transcribe_file(b, k, p)
            )
        except SystemExit as exc:
            results["degradation"].append(f"{backend}: transcription failed — {exc}")
            continue
        results[backend] = segments
        print(f"[interview] {backend}: {len(segments)} segments", file=sys.stderr)

    if results["groq"] is None and results["openai"] is None:
        raise SystemExit("Both engines failed or are unconfigured — cannot transcribe")
    return results
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_interview_diff.py -q`
Expected: all PASS (11 tests)

- [ ] **Step 6: Run the full suite to prove no regression to watch tests**

Run: `python3 -m pytest -q`
Expected: all PASS (existing suite + 12 new)

- [ ] **Step 7: Commit**

```bash
git add tests/conftest.py tests/test_interview_diff.py skills/interview/scripts/dual_transcribe.py
git commit -m "feat(interview): word-level dual-engine diff + adjudication apply, with tests"
```

---

## Task 3: Turn building, concordance, flag validation, frame bursts

> **Amended by Task 3 review (see the `fix(interview): harden analyze core` commit — the code, not the blocks below, is current):** build_turns iterates segments in start-time order (preserving original indices) and never moves a turn's end backward; compute_concordance records gain an `"invalid"` count (present-but-invalid panel labels no longer silently inflate concordance); validate_flags rejects bool salience and non-list marker_types; burst_timestamps(count=1) returns the clamped midpoint.

**Files:**
- Create: `tests/test_interview_concordance.py`
- Create: `skills/interview/scripts/analyze.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_interview_concordance.py`:

```python
"""Turn grouping, panel concordance, gravity-flag validation, frame bursts."""
from __future__ import annotations

import json
from pathlib import Path

from analyze import build_turns, burst_timestamps, compute_concordance, validate_flags

CODEBOOK = json.loads(
    (Path(__file__).resolve().parent.parent
     / "skills" / "interview" / "scripts" / "codebook.json").read_text()
)


def seg(start, end, text):
    return {"start": start, "end": end, "text": text}


class TestBuildTurns:
    def test_groups_contiguous_segments_and_splits_on_gap(self):
        segments = [
            seg(0.0, 2.0, "So tell me about"),
            seg(2.3, 4.0, "a time you led."),      # 0.3s gap → same turn
            seg(6.0, 9.0, "Well, it was 2019."),   # 2.0s gap → new turn
        ]
        turns = build_turns(segments, gap_seconds=1.0)
        assert [t["id"] for t in turns] == ["t0001", "t0002"]
        assert turns[0]["text"] == "So tell me about a time you led."
        assert turns[0]["start"] == 0.0 and turns[0]["end"] == 4.0
        assert turns[1]["text"] == "Well, it was 2019."
        assert turns[0]["segment_indices"] == [0, 1]
        assert turns[1]["segment_indices"] == [2]


class TestComputeConcordance:
    def _turns(self):
        return [{"id": "t0001", "start": 0.0, "end": 4.0, "text": "x"},
                {"id": "t0002", "start": 6.0, "end": 9.0, "text": "y"}]

    def test_unanimous_panel_yields_full_concordance(self):
        panels = [{"t0001": "INTERVIEWER", "t0002": "INTERVIEWEE"}] * 3
        result = compute_concordance(self._turns(), panels)
        assert result["t0001"] == {"label": "INTERVIEWER", "concordance": 1.0, "votes": 3}
        assert result["t0002"]["label"] == "INTERVIEWEE"

    def test_two_of_three_majority_meets_threshold(self):
        panels = [
            {"t0001": "INTERVIEWER", "t0002": "INTERVIEWEE"},
            {"t0001": "INTERVIEWER", "t0002": "INTERVIEWEE"},
            {"t0001": "INTERVIEWEE", "t0002": "INTERVIEWEE"},
        ]
        result = compute_concordance(self._turns(), panels)
        assert result["t0001"]["label"] == "INTERVIEWER"
        assert round(result["t0001"]["concordance"], 2) == 0.67

    def test_three_way_split_falls_through_to_unclear(self):
        panels = [{"t0001": "INTERVIEWER"}, {"t0001": "INTERVIEWEE"}, {"t0001": "OTHER"}]
        result = compute_concordance(self._turns()[:1], panels)
        assert result["t0001"]["label"] == "UNCLEAR"

    def test_fewer_than_two_votes_is_unclear(self):
        panels = [{"t0001": "INTERVIEWER"}, {}, {}]
        result = compute_concordance(self._turns()[:1], panels)
        assert result["t0001"]["label"] == "UNCLEAR"
        assert result["t0001"]["votes"] == 1

    def test_invalid_labels_are_discarded_not_counted(self):
        panels = [{"t0001": "NARRATOR"}, {"t0001": "INTERVIEWER"}, {"t0001": "INTERVIEWER"}]
        result = compute_concordance(self._turns()[:1], panels)
        assert result["t0001"]["label"] == "INTERVIEWER"
        assert result["t0001"]["votes"] == 2


class TestValidateFlags:
    def _flag(self, **overrides):
        flag = {
            "id": "g0001",
            "marker_types": ["emotional_display"],
            "emotion": "anger",
            "quote": "I was furious",
            "t_start": 62.0,
            "t_end": 65.5,
            "salience": 4,
        }
        flag.update(overrides)
        return flag

    def test_valid_flag_passes(self):
        assert validate_flags([self._flag()], CODEBOOK, duration=600.0) == []

    def test_unknown_marker_rejected(self):
        errors = validate_flags([self._flag(marker_types=["vibes"])], CODEBOOK, 600.0)
        assert any("vibes" in e for e in errors)

    def test_emotional_display_requires_valid_emotion(self):
        errors = validate_flags([self._flag(emotion=None)], CODEBOOK, 600.0)
        assert any("emotion" in e for e in errors)
        errors = validate_flags([self._flag(emotion="hangry")], CODEBOOK, 600.0)
        assert any("hangry" in e for e in errors)

    def test_salience_bounds_and_time_bounds(self):
        assert validate_flags([self._flag(salience=0)], CODEBOOK, 600.0)
        assert validate_flags([self._flag(salience=6)], CODEBOOK, 600.0)
        assert validate_flags([self._flag(t_start=700.0, t_end=701.0)], CODEBOOK, 600.0)
        assert validate_flags([self._flag(t_start=10.0, t_end=5.0)], CODEBOOK, 600.0)

    def test_missing_required_field_rejected(self):
        flag = self._flag()
        del flag["quote"]
        errors = validate_flags([flag], CODEBOOK, 600.0)
        assert any("quote" in e for e in errors)


class TestBurstTimestamps:
    def test_five_points_centered_on_span_midpoint(self):
        points = burst_timestamps(60.0, 64.0, duration=600.0)
        assert points == [57.0, 59.5, 62.0, 64.5, 67.0]

    def test_clamped_at_media_edges(self):
        points = burst_timestamps(1.0, 2.0, duration=600.0)
        assert points[0] == 0.0
        points = burst_timestamps(598.0, 599.0, duration=600.0)
        assert points[-1] == 600.0

    def test_clamping_dedupes(self):
        points = burst_timestamps(0.0, 0.0, duration=4.0)
        assert points == sorted(set(points))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_interview_concordance.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'analyze'`

- [ ] **Step 3: Implement `skills/interview/scripts/analyze.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_interview_concordance.py -q`
Expected: all PASS (15 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_interview_concordance.py skills/interview/scripts/analyze.py
git commit -m "feat(interview): turns, panel concordance, flag validation, frame bursts — with tests"
```

---

## Task 4: Renderer — .docx with anchored comments + JSON sidecar

**Files:**
- Create: `tests/test_interview_render.py`
- Create: `skills/interview/scripts/render.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_interview_render.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_interview_render.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'render'`

- [ ] **Step 3: Implement `skills/interview/scripts/render.py`**

```python
#!/usr/bin/env python3
"""Render final artifacts: a .docx transcript with gravity flags as anchored
Word comments, and the JSON sidecar. Raw OOXML via zipfile — stdlib only,
same approach as hand-rolled multipart in stt.py: the format is small and
predictable, so we write it directly rather than pulling python-docx."""
from __future__ import annotations

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


def format_hms(seconds: float) -> str:
    s = int(seconds)
    if s >= 3600:
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    return f"{s // 60:02d}:{s % 60:02d}"


def _run(text: str, bold: bool = False) -> str:
    props = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return f'<w:r>{props}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def _flag_comment_text(flag: dict) -> str:
    markers = ", ".join(flag.get("marker_types") or [])
    bits = [f"GRAVITY [{markers}]"]
    if flag.get("emotion"):
        bits.append(f"emotion: {flag['emotion']}")
    bits.append(f"salience {flag.get('salience')}/5")
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


def build_docx_parts(turns: list[dict], flags: list[dict]) -> dict[str, str]:
    """Pure: labeled turns + validated flags → {zip_name: xml_string}."""
    flag_to_turn: dict[str, list[tuple[int, dict]]] = {}
    comments_xml_items: list[str] = []
    for cid, flag in enumerate(flags):
        home = None
        for turn in turns:
            in_time = turn["start"] - 2.0 <= flag.get("t_start", 0) <= turn["end"] + 2.0
            if in_time and (flag.get("quote") or "") in turn["text"]:
                home = turn
                break
        if home is None:  # fall back: best time overlap, else last turn
            home = next(
                (t for t in turns
                 if t["start"] - 2.0 <= flag.get("t_start", 0) <= t["end"] + 2.0),
                turns[-1] if turns else None,
            )
        if home is not None:
            flag_to_turn.setdefault(home["id"], []).append((cid, flag))
        comments_xml_items.append(
            f'<w:comment w:id="{cid}" w:author="interview-skill" w:initials="IS">'
            f"<w:p>{_run(_flag_comment_text(flag))}</w:p></w:comment>"
        )

    paragraphs = [
        "<w:p>" + _run("Interview Transcript", bold=True) + "</w:p>",
    ]
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
            "processed_at": now or datetime.now().isoformat(timespec="seconds"),
        },
        "engines": engines,
        "accuracy_claim": claim,
        "degradation": degradation,
        "partial_failures": partial_failures,
        "segments": segments,
        "turns": turns,
        "adjudications": adjudications,
        "flags": [dict(f, codebook_version=codebook_version) for f in flags],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_interview_render.py -q`
Expected: all PASS (10 tests)

- [ ] **Step 5: Open a generated .docx in Word/Pages to eyeball it once**

Run: `python3 - <<'EOF'` (generate a sample from the test fixtures into `/tmp/interview_sample.docx`, then `open /tmp/interview_sample.docx`)

```python
import sys
sys.path.insert(0, "skills/interview/scripts")
from render import build_docx_parts, write_docx
turns = [
    {"id": "t0001", "start": 0.0, "end": 4.0, "text": "Tell me about a difficult decision.", "label": "INTERVIEWER", "concordance": 1.0},
    {"id": "t0002", "start": 6.0, "end": 20.0, "text": "It was 2019 and I was furious about the layoff decision.", "label": "INTERVIEWEE", "concordance": 1.0},
]
flags = [{"id": "g0001", "marker_types": ["emotional_display"], "emotion": "anger",
          "quote": "I was furious", "t_start": 8.0, "t_end": 11.0, "salience": 4,
          "note": "anger tied to layoff episode"}]
write_docx(build_docx_parts(turns, flags), __import__("pathlib").Path("/tmp/interview_sample.docx"))
EOF
```

Expected: file opens; two speaker paragraphs; a comment balloon anchored on "I was furious" containing the GRAVITY metadata.

- [ ] **Step 6: Commit**

```bash
git add tests/test_interview_render.py skills/interview/scripts/render.py
git commit -m "feat(interview): OOXML docx renderer with anchored comments + sidecar builder, with tests"
```

---

## Task 5: CLI orchestrator (`interview.py`)

**Files:**
- Create: `skills/interview/scripts/interview.py`

No unit tests for this file (thin argparse wiring over tested cores + network calls); verification is the scripted smoke run in Step 3.

- [ ] **Step 1: Implement `skills/interview/scripts/interview.py`**

```python
#!/usr/bin/env python3
"""CLI entry for the /interview skill. Subcommands are pipeline stages;
Claude (per SKILL.md) runs them in order and supplies the judgment files
(adjudications.json, panel_*.json, flags.json) between stages."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import framegrab
import stt
from analyze import build_turns, burst_timestamps, compute_concordance, validate_flags
from dual_transcribe import apply_adjudications, diff_transcripts, transcribe_both
from render import build_docx_parts, build_sidecar, format_hms, write_docx

MEDIA_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4a", ".wav", ".mp3", ".aac", ".flac"}
AUDIO_ONLY_EXTS = {".m4a", ".wav", ".mp3", ".aac", ".flac"}
CODEBOOK_PATH = Path(__file__).resolve().parent / "codebook.json"


def out_dirs(media: Path, out_override: str | None) -> tuple[Path, Path]:
    base = Path(out_override) if out_override else media.parent / f"{media.stem}_interview"
    return base, base / "work"


def _load(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def cmd_preflight(args) -> int:
    missing = [b for b in ("ffmpeg", "ffprobe") if shutil.which(b) is None]
    _, groq = stt.load_api_key(preferred="groq")
    _, openai = stt.load_api_key(preferred="openai")
    status = {
        "binaries_ok": not missing,
        "missing_binaries": missing,
        "groq_key": bool(groq),
        "openai_key": bool(openai),
        "dual_ok": bool(groq and openai),
    }
    print(json.dumps(status, indent=2))
    if missing:
        print("Install ffmpeg (includes ffprobe): brew install ffmpeg", file=sys.stderr)
        return 2
    if not (groq or openai):
        return 3
    return 0


def cmd_discover(args) -> int:
    folder = Path(args.folder)
    files = sorted(
        str(p) for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in MEDIA_EXTS
    )
    print(json.dumps({"folder": str(folder), "media": files}, indent=2))
    return 0


def cmd_transcribe(args) -> int:
    media = Path(args.media)
    base, work = out_dirs(media, args.out_dir)
    results = transcribe_both(str(media), work)
    for backend in ("groq", "openai"):
        if results[backend] is not None:
            _save(work / f"{backend}.json", results[backend])

    groq, openai = results["groq"], results["openai"]
    if groq and openai:
        diffed = diff_transcripts(groq, openai)
    else:  # degraded single-engine: everything is "agreed", nothing to adjudicate
        only = groq or openai
        diffed = diff_transcripts(only, only)
    diffed["degradation"] = results["degradation"]
    diffed["partial_failures"] = results["partial_failures"]
    _save(work / "diff.json", diffed)

    n = len(diffed["disagreements"])
    print(f"WORK_DIR: {work}")
    print(f"DEGRADATION: {results['degradation'] or 'none'}")
    print(f"PARTIAL_FAILURES: {results['partial_failures'] or 'none'}")
    print(f"DISAGREEMENTS: {n}")
    for d in diffed["disagreements"]:
        print(
            f"  {d['id']} @{format_hms(d['t_start'])} | "
            f"groq: {d['groq_text']!r} | openai: {d['openai_text']!r} | "
            f"…{d['context_before']} [?] {d['context_after']}…"
        )
    if n == 0:
        print("No adjudication needed — write an empty adjudications.json: {}")
    return 0


def cmd_finalize(args) -> int:
    work = Path(args.work)
    diffed = _load(work / "diff.json")
    decisions = _load(work / "adjudications.json")
    segments, audit = apply_adjudications(
        diffed["stream"], diffed["disagreements"], decisions
    )
    _save(work / "final_transcript.json", segments)
    _save(work / "audit_log.json", audit)
    turns = build_turns(segments)
    _save(work / "turns.json", turns)
    print(f"SEGMENTS: {len(segments)}  TURNS: {len(turns)}  ADJUDICATED: {len(audit)}")
    for t in turns:
        print(f"  {t['id']} [{format_hms(t['start'])}-{format_hms(t['end'])}] {t['text']}")
    return 0


def cmd_concordance(args) -> int:
    work = Path(args.work)
    turns = _load(work / "turns.json")
    panel_files = sorted(work.glob("panel_*.json"))
    if len(panel_files) < 2:
        print(f"ERROR: need >=2 panel files, found {len(panel_files)}", file=sys.stderr)
        return 1
    panels = [_load(p) for p in panel_files]
    scores = compute_concordance(turns, panels)
    for t in turns:
        t["label"] = scores[t["id"]]["label"]
        t["concordance"] = scores[t["id"]]["concordance"]
        t["votes"] = scores[t["id"]]["votes"]
        t["invalid"] = scores[t["id"]]["invalid"]
    _save(work / "diarized.json", turns)
    from collections import Counter
    counts = Counter(t["label"] for t in turns)
    print(f"PANELS: {len(panels)}  LABELS: {dict(counts)}")
    low = [t for t in turns if t["label"] == "UNCLEAR" or t["concordance"] < 1.0]
    for t in low:
        print(f"  LOW: {t['id']} [{format_hms(t['start'])}] {t['label']} "
              f"({t['concordance']:.2f}) {t['text'][:80]}")
    return 0


def cmd_validate_flags(args) -> int:
    work = Path(args.work)
    flags = _load(work / "flags.json")
    codebook = _load(CODEBOOK_PATH)
    duration = float(args.duration) if args.duration else float("inf")
    errors = validate_flags(flags, codebook, duration)
    if errors:
        print("INVALID FLAGS:")
        for e in errors:
            print(f"  {e}")
        return 1
    print(f"OK: {len(flags)} flags valid against codebook {codebook['codebook_version']}")
    return 0


def cmd_frames(args) -> int:
    media = Path(args.media)
    base, work = out_dirs(media, args.out_dir)
    if media.suffix.lower() in AUDIO_ONLY_EXTS:
        print("AUDIO-ONLY MEDIA: frame pass skipped (noted for sidecar)")
        return 0
    flags = _load(work / "flags.json")
    meta = framegrab.get_metadata(str(media))
    duration = float(meta.get("duration_seconds") or 0.0)
    for flag in flags:
        points = burst_timestamps(flag["t_start"], flag["t_end"], duration)
        flag_dir = base / "frames" / flag["id"]
        frames, _ = framegrab.extract_at_timestamps(str(media), flag_dir, points)
        flag["frame_paths"] = [f["path"] for f in frames]
        print(f"{flag['id']} ({', '.join(flag['marker_types'])}):")
        for f in frames:
            print(f"  t={format_hms(f['timestamp_seconds'])} {f['path']}")
    _save(work / "flags.json", flags)
    return 0


def cmd_render(args) -> int:
    media = Path(args.media)
    base, work = out_dirs(media, args.out_dir)
    turns = _load(work / "diarized.json")
    flags = _load(work / "flags.json")
    segments = _load(work / "final_transcript.json")
    audit = _load(work / "audit_log.json")
    diffed = _load(work / "diff.json")
    codebook = _load(CODEBOOK_PATH)

    try:
        meta = framegrab.get_metadata(str(media))
        duration = float(meta.get("duration_seconds") or 0.0)
    except SystemExit:
        duration = segments[-1]["end"] if segments else 0.0

    degradation = list(diffed.get("degradation") or [])
    if media.suffix.lower() in AUDIO_ONLY_EXTS:
        degradation.append("audio-only media: no frame evidence available")

    engines = {}
    if (work / "groq.json").exists():
        engines["groq"] = "whisper-large-v3"
    if (work / "openai.json").exists():
        engines["openai"] = "whisper-1"

    docx_path = write_docx(build_docx_parts(turns, flags), base / "transcript.docx")
    sidecar = build_sidecar(
        media=media.name, duration=duration, engines=engines,
        degradation=degradation, segments=segments, turns=turns,
        adjudications=audit, flags=flags,
        partial_failures=list(diffed.get("partial_failures") or []),
        codebook_version=codebook["codebook_version"],
    )
    _save(base / "sidecar.json", sidecar)
    print(f"DOCX: {docx_path}")
    print(f"SIDECAR: {base / 'sidecar.json'}")
    print(f"CLAIM: {sidecar['accuracy_claim']}")
    return 0


def cmd_corpus_summary(args) -> int:
    folder = Path(args.folder)
    sidecars = sorted(folder.glob("*_interview/sidecar.json"))
    from collections import Counter
    by_marker, by_emotion = Counter(), Counter()
    rows = []
    for path in sidecars:
        sc = _load(path)
        flags = sc.get("flags", [])
        for f in flags:
            for m in f.get("marker_types", []):
                by_marker[m] += 1
            if f.get("emotion"):
                by_emotion[f["emotion"]] += 1
        rows.append({"media": sc["interview"]["media"], "flags": len(flags),
                     "claim": sc["accuracy_claim"]})
    summary = {"interviews": len(rows), "per_interview": rows,
               "flags_by_marker": dict(by_marker), "flags_by_emotion": dict(by_emotion)}
    _save(folder / "corpus_summary.json", summary)
    print(json.dumps(summary, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="interview.py")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("preflight")
    p = sub.add_parser("discover"); p.add_argument("folder")
    p = sub.add_parser("transcribe"); p.add_argument("media"); p.add_argument("--out-dir")
    p = sub.add_parser("finalize"); p.add_argument("--work", required=True)
    p = sub.add_parser("concordance"); p.add_argument("--work", required=True)
    p = sub.add_parser("validate-flags"); p.add_argument("--work", required=True); p.add_argument("--duration")
    p = sub.add_parser("frames"); p.add_argument("media"); p.add_argument("--out-dir")
    p = sub.add_parser("render"); p.add_argument("media"); p.add_argument("--out-dir")
    p = sub.add_parser("corpus-summary"); p.add_argument("folder")

    args = parser.parse_args()
    handlers = {
        "preflight": cmd_preflight, "discover": cmd_discover,
        "transcribe": cmd_transcribe, "finalize": cmd_finalize,
        "concordance": cmd_concordance, "validate-flags": cmd_validate_flags,
        "frames": cmd_frames, "render": cmd_render,
        "corpus-summary": cmd_corpus_summary,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Verify CLI wiring**

Run: `python3 skills/interview/scripts/interview.py preflight`
Expected: JSON status block; exit 0 if ffmpeg + at least one key present.

- [ ] **Step 3: Network-free end-to-end smoke run (fabricated engine outputs)**

This exercises every stage except the two Whisper uploads by planting `groq.json`/`openai.json` and driving the pipeline over an ffmpeg-synthesized clip:

```bash
python3 - <<'EOF'
import json, subprocess, sys
from pathlib import Path
sys.path.insert(0, "skills/interview/scripts")
from dual_transcribe import diff_transcripts

work = Path("/tmp/smoke_interview/work"); work.mkdir(parents=True, exist_ok=True)
subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y",
    "-f","lavfi","-t","30","-i","color=c=navy:s=320x240:r=10",
    "-f","lavfi","-t","30","-i","anullsrc=r=16000:cl=mono",
    "-shortest","-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac",
    "/tmp/smoke.mp4"], check=True)
groq   = [{"start":0.0,"end":3.0,"text":"Tell me about a hard decision."},
          {"start":5.0,"end":12.0,"text":"I was furious when they cancelled the program."}]
openai = [{"start":0.0,"end":3.0,"text":"Tell me about a hard decision."},
          {"start":5.0,"end":12.0,"text":"I was curious when they cancelled the program."}]
json.dump(groq, open(work/"groq.json","w")); json.dump(openai, open(work/"openai.json","w"))
json.dump(dict(diff_transcripts(groq, openai), degradation=[]), open(work/"diff.json","w"))
json.dump({"d0001":{"text":"furious","rationale":"emotional register of the episode"}},
          open(work/"adjudications.json","w"))
EOF
P=skills/interview/scripts/interview.py
python3 $P finalize --work /tmp/smoke_interview/work
python3 - <<'EOF'
import json
from pathlib import Path
work = Path("/tmp/smoke_interview/work")
turns = json.load(open(work/"turns.json"))
labels = {"t0001":"INTERVIEWER"} | {t["id"]:"INTERVIEWEE" for t in turns[1:]}
for i in (1,2,3): json.dump(labels, open(work/f"panel_{i}.json","w"))
json.dump([{"id":"g0001","marker_types":["emotional_display"],"emotion":"anger",
  "quote":"I was furious","t_start":5.0,"t_end":8.0,"salience":4}],
  open(work/"flags.json","w"))
EOF
python3 $P concordance --work /tmp/smoke_interview/work
python3 $P validate-flags --work /tmp/smoke_interview/work --duration 30
python3 $P frames /tmp/smoke.mp4 --out-dir /tmp/smoke_interview
python3 $P render /tmp/smoke.mp4 --out-dir /tmp/smoke_interview
```

Expected: `finalize` prints 1 adjudication + turn list; `concordance` prints label counts; `validate-flags` prints OK; `frames` lists ~5 cue paths under `frames/g0001/`; `render` prints DOCX/SIDECAR paths and `CLAIM: dual-engine verified with logged adjudication`. Open `/tmp/smoke_interview/transcript.docx` and confirm the comment on "I was furious".

- [ ] **Step 4: Commit**

```bash
git add skills/interview/scripts/interview.py
git commit -m "feat(interview): CLI orchestrator with stage subcommands + smoke-tested pipeline"
```

---

## Task 6: SKILL.md — the skill contract and all Claude-side judgment

**Files:**
- Create: `skills/interview/SKILL.md`

- [ ] **Step 1: Write `skills/interview/SKILL.md`**

Frontmatter and required sections below. Follow the SKILL_DIR-resolution pattern from `skills/watch/SKILL.md` verbatim (adapted paths). Full required content:

```markdown
---
name: interview
version: "0.1.0"
description: Ingest a social-science interview recording (or a folder of them). Produces a dual-engine verified, speaker-diarized transcript with narrative-gravity flags — a .docx with anchored comments plus a JSON sidecar. Local media first; URLs allowed for non-sensitive material.
argument-hint: "<media-file-or-folder> [notes]"
allowed-tools: Bash, Read, Write, Agent, AskUserQuestion
homepage: https://github.com/Jerrymwolf/claude-video
license: MIT
user-invocable: true
---

# /interview

You are the judgment layer of a research transcription pipeline. Python scripts do
everything deterministic; YOU do exactly three judgment jobs: (1) adjudicate
disagreements between two Whisper engines, (2) sit as a 3-analyst diarization panel,
(3) code the transcript against the narrative-gravity codebook. Every judgment you
make is written to a JSON file and retained — you are producing research data,
not a chat answer.

## Resolve SKILL_DIR
[Copy the SKILL_DIR resolution block from skills/watch/SKILL.md, substituting
skills/interview — including the guard snippet that checks scripts/interview.py exists.]

## Step 0 — Preflight
Run: python3 "${SKILL_DIR}/scripts/interview.py" preflight
- exit 0 with "dual_ok": true → proceed silently.
- "dual_ok": false but one key present → WARN the user: output will be marked
  single-engine UNVERIFIED. Offer to add the missing GROQ_API_KEY / OPENAI_API_KEY
  to ~/.config/watch/.env (AskUserQuestion), then proceed either way.
- exit 2 → ffmpeg missing; give the printed install command and stop.
- exit 3 → no keys at all; help the user add at least one, or stop.

## Step 1 — Resolve input
- Folder → run discover; process every listed file sequentially through Steps 2-8;
  after the last one run corpus-summary and report it.
- URL → download first with yt-dlp to a local file (only for non-sensitive material),
  then treat as a file.
- Audio-only file (.m4a/.wav/.mp3/.aac/.flac) → same pipeline; frames are skipped
  automatically.

## Step 2 — Dual transcription
Run: python3 "${SKILL_DIR}/scripts/interview.py" transcribe "<media>"
Note the printed WORK_DIR — every later stage uses it. This uploads audio to BOTH
Groq and OpenAI Whisper (only when captions don't exist — interviews never have
them) and prints every disagreement between the engines.

## Step 3 — Adjudicate (judgment job 1)
For EVERY printed disagreement decide the correct reading. Rules:
- Choose based on discourse context, speaker register, and plausibility. You may
  synthesize a correction only when both readings are clearly mangled versions of
  an obvious intended word; NEVER invent content absent from both readings.
- Empty text deletes the span (e.g. one engine hallucinated a filler).
- Rationale ≤ 15 words, concrete ("proper noun consistent with t=12:40 mention").
Write WORK_DIR/adjudications.json:
{"d0001": {"text": "<chosen>", "rationale": "<why>"}, ...}
(No disagreements → write {}.) Then run:
python3 "${SKILL_DIR}/scripts/interview.py" finalize --work WORK_DIR

## Step 4 — Diarization panel (judgment job 2)
finalize printed the numbered turns. Dispatch THREE independent subagents via the
Agent tool IN ONE MESSAGE (parallel, no shared context). Each gets this prompt with
the full turn list appended:

  "You are analyst {N} of an independent diarization panel. Below is a numbered,
  timestamped transcript of a two-party research interview. Label EVERY turn:
  INTERVIEWER (asks, probes, manages the protocol), INTERVIEWEE (narrates,
  answers), or OTHER (third voice, interruption, unattributable crosstalk).
  Judge from discourse role, not word count. Return ONLY a JSON object:
  {\"t0001\": \"INTERVIEWER\", ...} — every turn id, no commentary."

Write their three outputs verbatim to WORK_DIR/panel_1.json, panel_2.json,
panel_3.json. Then run:
python3 "${SKILL_DIR}/scripts/interview.py" concordance --work WORK_DIR
Review the LOW lines it prints — do not relabel; low concordance is data.

## Step 5 — Gravity pass (judgment job 3)
Read "${SKILL_DIR}/scripts/codebook.json" and WORK_DIR/diarized.json. Code ONLY
INTERVIEWEE turns. For each moment matching one or more codebook markers, build a
flag exactly per flag_schema. Quotes must be verbatim substrings of a turn.
Salience per the scale — reserve 5 for genuinely interview-defining moments.
Expect roughly 5-20 flags for a 60-minute interview; zero flags is a valid outcome
for a flat interview — do not invent gravity. Write the array to WORK_DIR/flags.json,
then validate (fix and re-run until OK):
python3 "${SKILL_DIR}/scripts/interview.py" validate-flags --work WORK_DIR --duration <seconds>

## Step 6 — Frame evidence (video only)
Run: python3 "${SKILL_DIR}/scripts/interview.py" frames "<media>"
Read EVERY printed frame in one message. For each flag, set "visual_evidence" in
WORK_DIR/flags.json: "corroborates — <note>", "contradicts — <note>", or
"neutral — <note>". NEVER delete a flag because frames contradict it — record the
contradiction; the sidecar keeps both signals.

## Step 7 — Render
Run: python3 "${SKILL_DIR}/scripts/interview.py" render "<media>"

## Step 8 — Report to the user (per interview)
Accuracy claim (verbatim from render output) · engine disagreement count and how
many adjudications were nontrivial · label counts + any UNCLEAR turns · flag count
by marker, top-salience moments with timestamps · artifact paths.
Batch mode: per-interview one-line summaries + the corpus summary.

## Retention
NEVER delete the work directory or frames — they are the audit trail (evidence
retention is this skill's compensating control for being fully automatic).

## Failure modes
- One engine fails/keyless → pipeline continues; artifacts and your report MUST
  carry "single-engine UNVERIFIED".
- A transcription chunk fails → it is recorded in the sidecar's partial_failures
  and the accuracy claim is marked INCOMPLETE; note it in your report.
- validate-flags rejects → fix flags.json per the printed errors; never bypass.
- Never claim the transcript is "error-free" — the honest claim is printed by render.

## Security & Permissions
[Adapt the watch SKILL.md section: audio (never video) goes to api.groq.com and/or
api.openai.com; artifacts persist next to the media file BY DESIGN (research data);
keys live in ~/.config/watch/.env; scripts are pure stdlib.]
```

- [ ] **Step 2: Sanity-check frontmatter parses (name/user-invocable present)**

Run: `python3 - <<'EOF'`
```python
import re
text = open("skills/interview/SKILL.md").read()
fm = re.search(r"^---\n(.*?)\n---", text, re.S).group(1)
assert "name: interview" in fm and "user-invocable: true" in fm
print("frontmatter OK")
EOF
```
Expected: `frontmatter OK`

- [ ] **Step 3: Commit**

```bash
git add skills/interview/SKILL.md
git commit -m "feat(interview): SKILL.md contract — adjudication, diarization panel, gravity pass"
```

---

## Task 7: Docs, full suite, wrap-up

**Files:**
- Modify: `README.md` (short new section)
- Modify: `AGENTS.md` (structure note)

- [ ] **Step 1: Add a README section**

After the existing `## Limits` section, add `## /interview (fork addition)` — 10-15 lines: what it does (dual-engine verified transcript, panel diarization, gravity flags, .docx + sidecar), one usage example (`/interview ~/Interviews/bei_017.mp4`), the honest accuracy-claim language, pointer to `skills/interview/scripts/codebook.json` and issue #1 as the spec.

- [ ] **Step 2: Add the skill to AGENTS.md structure list**

Under `## Structure`, add one line: `- skills/interview/ — self-contained interview-ingestion skill (fork addition): dual-engine Whisper diff → Claude adjudication → panel diarization → gravity codebook → .docx + sidecar. Scripts mirror watch conventions; stt.py/framegrab.py are copies of watch's whisper.py/frames.py (keep byte-close for upstream diffing).`

- [ ] **Step 3: Full test suite + final smoke**

Run: `python3 -m pytest -q`
Expected: all PASS (upstream suite + 37 new interview tests, 0 failures)

- [ ] **Step 4: Commit**

```bash
git add README.md AGENTS.md
git commit -m "docs(interview): README + AGENTS.md coverage for the interview skill"
```

- [ ] **Step 5: Update the AgentOS registry card**

Outside this repo: set `status`/`last_activity` in
`/Users/jeremiahwolf/Desktop/Projects/APPs/AgentOS/registry/projects/claude-video-interview.md`
(state: implementation complete on branch `interview-skill`; tests green).

---

## Deliberately NOT in this plan (matches PRD Out of Scope)

Prosody features; human review workflow; N-speaker diarization; authenticated cloud sources; DB integration; local transcription; real-time; any change under `skills/watch/`; `.claude-plugin`/`.codex-plugin` version bumps (release mechanics happen when cutting a tag, not in this feature branch).

## Self-review notes (already applied)

- Spec coverage: PRD user stories 1-22 → Tasks 2 (stories 2-4), 3 (5-8), 4 (10-13, 21), 5 (1, 14-18, 20, 22), 6 (7-9, 19); story 19 also enforced by "never touch skills/watch".
- Type consistency: segment shape `{start, end, text}` everywhere (matches stt/watch); stream items `{kind, raw|id, t, seg}`; turn shape `{id, start, end, text, segment_indices}` + `label`/`concordance` added by concordance stage; flag shape per codebook.json flag_schema.
- The `transcribe` command falls back to a self-diff when one engine is missing so `finalize` works unchanged in degraded mode, and the sidecar's accuracy claim downgrade is computed from the degradation list, tested in test_interview_render.py.
```
