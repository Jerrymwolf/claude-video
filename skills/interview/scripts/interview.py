#!/usr/bin/env python3
"""CLI entry for the /interview skill. Subcommands are pipeline stages;
Claude (per SKILL.md) runs them in order and supplies the judgment files
(adjudications.json, panel_*.json, flags.json) between stages."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections import Counter
from pathlib import Path

import framegrab
import stt
from analyze import (
    assign_episode_ids,
    assign_flag_episodes,
    build_turns,
    burst_timestamps,
    compute_concordance,
    episode_drift,
    merge_labeled_turns,
    segment_turns,
    summarize_corpus,
    validate_episodes,
    validate_flags,
)
from dual_transcribe import apply_adjudications, diff_transcripts, transcribe_both
from render import build_docx_parts, build_sidecar, format_hms, write_docx

MEDIA_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4a", ".wav", ".mp3", ".aac", ".flac"}
AUDIO_ONLY_EXTS = {".m4a", ".wav", ".mp3", ".aac", ".flac"}
CODEBOOK_PATH = Path(__file__).resolve().parent / "codebook.json"

# Keys live in the same file /watch uses, so a machine with either skill shares
# one config. stt.load_api_key reads this path (plus env and ./.env).
CONFIG_DIR = Path.home() / ".config" / "watch"
CONFIG_FILE = CONFIG_DIR / ".env"
GROQ_KEYS_URL = "https://console.groq.com/keys"
OPENAI_KEYS_URL = "https://platform.openai.com/api-keys"

ENV_TEMPLATE = """\
# Whisper API keys for Gravitas (/interview) and /watch.
#
# Gravitas transcribes every interview with BOTH engines and diffs them — that
# dual-engine cross-check is the tool's core accuracy guarantee, so you supply
# YOUR OWN key for each. They are not bundled and never shared.
#
#   Groq   (whisper-large-v3):  https://console.groq.com/keys       (free tier)
#   OpenAI (whisper-1):         https://platform.openai.com/api-keys (paid, ~$0.04/interview-hour)
#
# Both keys -> "dual-engine verified with logged adjudication". One key still
# runs the full pipeline, but every artifact is honestly marked
# "single-engine UNVERIFIED". Paste each key after its = sign, no quotes.

GROQ_API_KEY=
OPENAI_API_KEY=
"""


def scaffold_env_file(path: Path, template: str) -> bool:
    """Create the key file with placeholders if absent; never clobber existing
    keys. Returns True if it created the file. Opened O_CREAT|O_EXCL at 0600 so
    the file is owner-only from birth and an existing file is never truncated,
    even under a race (this file will later hold API-key secrets)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(template)
    return True


def out_dirs(media: Path, out_override: str | None) -> tuple[Path, Path]:
    base = Path(out_override) if out_override else media.parent / f"{media.stem}_interview"
    return base, base / "work"


def _load(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_checked(path: Path, expect: type | tuple = (dict, list)) -> dict | list:
    """_load, but with actionable failures for HAND-AUTHORED inputs.

    episodes.json and --codebook are written by a person (or by Claude) between
    stages, so a trailing comma or a mistyped path is the expected failure, not
    the exceptional one. A raw JSONDecodeError reports a line and column but no
    filename, and work/ holds four JSON files; a raw FileNotFoundError reports a
    traceback. Both read as crashes rather than as the fixable input errors they
    are.

    Exits 2, never 1: a broken input must stay distinguishable from a
    legitimate validation finding, which is what 1 means at these stages.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"ERROR: {path}: {exc.strerror or exc}", file=sys.stderr)
        raise SystemExit(2)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"ERROR: {path.name}: line {exc.lineno} column {exc.colno} — {exc.msg}",
              file=sys.stderr)
        raise SystemExit(2)
    types = expect if isinstance(expect, tuple) else (expect,)
    if not isinstance(data, types):
        want = " or ".join(t.__name__ for t in types)
        print(f"ERROR: {path.name}: expected a JSON {want}, got {type(data).__name__}",
              file=sys.stderr)
        raise SystemExit(2)
    return data


def _load_codebook(args) -> tuple[Path, dict]:
    """Resolve --codebook (default: the shipped narrative-gravity codebook).

    `args.codebook` is read directly, not via getattr: every subparser offering
    this stage defines the flag, and a defensive default would silently fall
    back to the shipped codebook if a future subcommand forgot to wire it.
    """
    path = Path(args.codebook) if args.codebook else CODEBOOK_PATH
    codebook = _load_checked(path, expect=dict)
    # Two keys, not one. `codebook_version` alone stopped discriminating the
    # moment sidecar schema 1.1 began recording its OWN top-level
    # codebook_version: --codebook <a prior run's sidecar.json> then loaded
    # clean and died several frames later on codebook["markers"] — verbatim the
    # traceback this guard exists to prevent. `markers` is that dereference, so
    # requiring it here turns the KeyError into this message. Positive
    # discriminator ("has what a codebook has") rather than a sidecar
    # blocklist: it rejects every non-codebook, not only the one file type we
    # happened to think of.
    missing = [k for k in ("codebook_version", "markers") if k not in codebook]
    if missing:
        print(f"ERROR: {path.name}: not a codebook — no "
              + " or ".join(f"'{k}'" for k in missing)
              + " key (did you point --codebook at the wrong file?)",
              file=sys.stderr)
        raise SystemExit(2)
    return path, codebook


def _save(path: Path, data) -> None:
    # Atomic: several stages rewrite judgment files (e.g. flags.json) in
    # place; a crash mid-write must never leave a truncated JSON behind.
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def cmd_setup(args) -> int:
    """Guided key setup: scaffold the .env, report which keys are present, and
    point the user at the Groq/OpenAI signup pages (--open launches them)."""
    created = scaffold_env_file(CONFIG_FILE, ENV_TEMPLATE)
    _, groq = stt.load_api_key(preferred="groq")
    _, openai = stt.load_api_key(preferred="openai")

    print("Gravitas setup — Whisper API keys")
    print(f"  key file: {CONFIG_FILE}"
          + ("  (created with placeholders)" if created else "  (already present — left untouched)"))
    print(f"  Groq key:   {'present' if groq else 'MISSING'}")
    print(f"  OpenAI key: {'present' if openai else 'MISSING'}")

    if groq and openai:
        print("  Ready: dual-engine verified transcription.")
    elif groq or openai:
        have, need, url = (
            ("Groq", "OpenAI", OPENAI_KEYS_URL) if groq else ("OpenAI", "Groq", GROQ_KEYS_URL)
        )
        print(f"  One key present ({have}). The pipeline runs as SINGLE-ENGINE UNVERIFIED.")
        print(f"  Add the {need} key for dual-engine verification: {url}")
    else:
        print("  You supply your own keys — Gravitas does not bundle or share them.")
        print(f"    1. Groq key (free tier):  {GROQ_KEYS_URL}")
        print(f"    2. OpenAI key (paid):     {OPENAI_KEYS_URL}")
        print(f"    3. Paste each key into:   {CONFIG_FILE}")
        print("  Then re-run:  interview.py preflight")

    if getattr(args, "open", False):
        import webbrowser
        wanted = [u for u, missing in (
            (GROQ_KEYS_URL, not groq), (OPENAI_KEYS_URL, not openai),
        ) if missing]
        opened = 0
        for u in wanted:
            try:
                if webbrowser.open(u):
                    opened += 1
            except Exception:  # headless / odd BROWSER= — --open is best-effort
                pass
        if not wanted:
            print("  All keys already present — nothing to open.")
        elif opened:
            print(f"  Opened {opened} signup page(s) in your browser.")
        else:
            print("  Could not open a browser here — visit the URLs above manually.")
    return 0


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
    stems: dict[str, list[str]] = {}
    for f in files:
        stems.setdefault(Path(f).stem, []).append(f)
    duplicates = {s: fs for s, fs in stems.items() if len(fs) > 1}
    print(json.dumps({"folder": str(folder), "media": files,
                      "duplicate_stems": duplicates}, indent=2))
    if duplicates:
        print(f"WARNING: {len(duplicates)} stem collision(s) — same-stem files share "
              f"an output dir; process only one per stem or use --out-dir",
              file=sys.stderr)
    return 0


def cmd_transcribe(args) -> int:
    media = Path(args.media)
    base, work = out_dirs(media, args.out_dir)
    results = transcribe_both(str(media), work)
    for backend in ("groq", "openai"):
        if results[backend] is not None:
            _save(work / f"{backend}.json", results[backend])

    groq, openai = results["groq"], results["openai"]
    if groq is not None and openai is not None:
        # An empty result still counts as present: diffing [] against a real
        # transcript surfaces everything as one disagreement to adjudicate,
        # instead of silently self-diffing and claiming dual verification.
        diffed = diff_transcripts(groq, openai)
    else:  # degraded single-engine: everything is "agreed", nothing to adjudicate
        only = groq if groq is not None else openai
        diffed = diff_transcripts(only, only)
    diffed["degradation"] = results["degradation"]
    diffed["partial_failures"] = results["partial_failures"]
    # Engine provenance travels with the diff — file-existence inference at
    # render time goes stale when a re-run degrades (old groq.json lingers).
    diffed["engines"] = {
        backend: model
        for backend, model in (("groq", "whisper-large-v3"), ("openai", "whisper-1"))
        if results[backend] is not None
    }
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
    if args.unit == "gap":
        turns = build_turns(segments)
    else:  # segment-scale units: rapid dyadic exchange defeats gap splitting
        turns = segment_turns(segments)
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
    uncovered = sorted({t["id"] for t in turns} - set().union(*(set(p) for p in panels)))
    if uncovered:
        print(f"WARNING: {len(uncovered)} turn id(s) have no panel votes — unit "
              f"mismatch? (e.g. finalize re-run with a different --unit): "
              f"{', '.join(uncovered[:5])}", file=sys.stderr)
    scores = compute_concordance(turns, panels)
    for t in turns:
        t["label"] = scores[t["id"]]["label"]
        t["concordance"] = scores[t["id"]]["concordance"]
        t["votes"] = scores[t["id"]]["votes"]
        t["invalid"] = scores[t["id"]]["invalid"]
    _save(work / "diarized.json", turns)
    counts = Counter(t["label"] for t in turns)
    print(f"PANELS: {len(panels)}  LABELS: {dict(counts)}")
    low = [t for t in turns if t["label"] == "UNCLEAR" or t["concordance"] < 1.0]
    for t in low:
        print(f"  LOW: {t['id']} [{format_hms(t['start'])}] {t['label']} "
              f"({t['concordance']:.2f}) {t['text'][:80]}")
    return 0


def cmd_validate_episodes(args) -> int:
    """Validate LLM-authored episodes.json, then stamp episode_id onto every
    diarized unit. Runs between concordance and validate-flags: flags inherit
    their episode from the turn layer this stage annotates."""
    work = Path(args.work)
    episodes = _load_checked(work / "episodes.json", expect=list)
    turns = _load_checked(work / "diarized.json", expect=list)
    _, codebook = _load_codebook(args)
    if not turns:
        # An episode layer covering nothing is not a valid episode layer: every
        # episode would print turns=0 and the stage would report success.
        print("ERROR: diarized.json holds no turns — run concordance first",
              file=sys.stderr)
        return 1
    errors = validate_episodes(episodes, turns, codebook=codebook)
    if errors:
        print("INVALID EPISODES:")
        for e in errors:
            print(f"  {e}")
        return 1
    assign_episode_ids(turns, episodes)
    _save(work / "diarized.json", turns)
    per_ep = Counter(t["episode_id"] for t in turns)
    print(f"EPISODES: {len(episodes)}")
    for e in episodes:
        etype = e.get("type")
        desc = f' target="{e.get("target_descriptor", "")}"' if etype == "confrontation" else ""
        print(f"  {e['id']} {etype} [{format_hms(e['t_start'])}-{format_hms(e['t_end'])}] "
              f"turns={per_ep.get(e['id'], 0)}{desc}")
    return 0


def cmd_validate_flags(args) -> int:
    work = Path(args.work)
    flags = _load(work / "flags.json")
    codebook_path, codebook = _load_codebook(args)
    duration = float(args.duration) if args.duration else float("inf")
    if not args.duration and (work / "final_transcript.json").exists():
        segments = _load(work / "final_transcript.json")
        if segments:  # auto-derive: last segment end ≈ media duration
            duration = float(segments[-1]["end"])
    transcript_text = None
    turns = None      # unit-level, exactly as concordance wrote them
    merged = None     # display turns; None when the units are not labeled yet
    if (work / "diarized.json").exists():
        turns = _load(work / "diarized.json")
        if turns and all("label" in t for t in turns):
            # Validate against the same merged view the docx anchors against,
            # so a verbatim quote spanning two same-speaker sentences passes.
            merged = merge_labeled_turns(turns)
            transcript_text = "\n".join(t["text"] for t in merged)
        else:
            transcript_text = "\n".join(t["text"] for t in turns)
    # `turns=` is load-bearing, not a convenience: a codebook declaring
    # coding_scope or enforce_attribution_gate RAISES without turns rather than
    # silently skipping its attribution guarantees. Unlabeled units are handed
    # over as-is rather than as None, so validate_flags reports the real cause
    # ("run concordance first") instead of the inaccurate "no turns supplied".
    errors = validate_flags(flags, codebook, duration,
                            transcript_text=transcript_text,
                            turns=merged if merged is not None else turns)
    ep_path = work / "episodes.json"
    if not errors and ep_path.exists():
        episodes = _load_checked(ep_path, expect=list)
        if merged is None:
            # Stamping flags now would file them against an episode layer the
            # turns were never reconciled with — half the record annotated.
            errors = ["episodes.json is present but there is no labeled turn "
                      "layer to reconcile it against — run concordance, then "
                      "validate-episodes, before validate-flags"]
        else:
            errors = episode_drift(merged, episodes)
        if not errors:
            errors = assign_flag_episodes(flags, episodes)
            if not errors:
                _save(work / "flags.json", flags)
    if errors:
        print("INVALID FLAGS:")
        for e in errors:
            print(f"  {e}")
        return 1
    print(f"OK: {len(flags)} flags valid against codebook {codebook['codebook_version']} "
          f"({codebook_path.name})")
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
        # Pull the clamp ceiling in slightly: a seek at exactly t=duration
        # yields no frame, so every end-of-interview flag would silently
        # shrink its burst.
        points = burst_timestamps(
            flag["t_start"], flag["t_end"], max(duration - 0.1, 0.0)
        )
        flag_dir = base / "frames" / flag["id"]
        frames, _ = framegrab.extract_at_timestamps(str(media), flag_dir, points)
        # Sidecar paths are relative to the interview dir — research artifacts
        # must stay portable across machines. Printed lines stay absolute
        # (Claude Reads those files directly).
        flag["frame_paths"] = [str(Path(f["path"]).relative_to(base)) for f in frames]
        flag.pop("frames_missing", None)  # a healthy re-run must clear stale records
        missing = len(points) - len(frames)
        if missing > 0:
            flag["frames_missing"] = missing
            print(f"WARNING: {flag['id']}: {missing} frame(s) not extracted")
        print(f"{flag['id']} ({', '.join(flag['marker_types'])}):")
        for f in frames:
            print(f"  t={format_hms(f['timestamp_seconds'])} {f['path']}")
    _save(work / "flags.json", flags)
    return 0


def cmd_render(args) -> int:
    if args.persona is not None and not args.persona.strip():
        # `--persona "$PERSONA"` with the variable unset. Recording "" would
        # assert this video HAS a persona and that it is the empty string;
        # dropping it silently would swallow a batch-run mistake. Exit 2, like
        # the other broken-input paths — a bad invocation, not a finding.
        print("ERROR: --persona was given an empty value — omit the flag "
              "entirely if this video has no persona", file=sys.stderr)
        return 2
    media = Path(args.media)
    base, work = out_dirs(media, args.out_dir)
    turns = _load(work / "diarized.json")
    flags = _load(work / "flags.json")
    segments = _load(work / "final_transcript.json")
    audit = _load(work / "audit_log.json")
    diffed = _load(work / "diff.json")
    codebook_path, codebook = _load_codebook(args)
    # The episode layer is optional (the narrative pipeline predates it), but
    # when it exists it is part of the research record, not a staging artifact.
    ep_path = work / "episodes.json"
    episodes = _load_checked(ep_path, expect=list) if ep_path.exists() else None

    try:
        meta = framegrab.get_metadata(str(media))
        duration = float(meta.get("duration_seconds") or 0.0)
    except SystemExit:
        duration = segments[-1]["end"] if segments else 0.0

    degradation = list(diffed.get("degradation") or [])
    if media.suffix.lower() in AUDIO_ONLY_EXTS:
        degradation.append("audio-only media: no frame evidence available")

    engines = dict(diffed.get("engines") or {})
    if not engines:  # older work dirs predate the engines record in diff.json
        if (work / "groq.json").exists():
            engines["groq"] = "whisper-large-v3"
        if (work / "openai.json").exists():
            engines["openai"] = "whisper-1"

    partial = list(diffed.get("partial_failures") or [])
    # Optional display names for the two roles (+ OTHER/UNCLEAR). Canonical
    # role labels stay in the sidecar record; names are a docx display layer.
    names = {
        role: getattr(args, attr)
        for role, attr in (("INTERVIEWER", "interviewer"), ("INTERVIEWEE", "interviewee"),
                           ("OTHER", "other"), ("UNCLEAR", "unclear"))
        if getattr(args, attr, None)
    } or None
    # Sidecar first: the docx carries the sidecar's accuracy claim, because
    # the .docx travels alone in document-based coding workflows.
    sidecar = build_sidecar(
        media=media.name, duration=duration, engines=engines,
        degradation=degradation, segments=segments, turns=turns,
        adjudications=audit, flags=flags,
        partial_failures=partial,
        codebook_version=codebook["codebook_version"],
        speaker_names=names,
        episodes=episodes,
        persona=args.persona,
        # Unconditional. An absent key would record that the DEFAULT WAS TAKEN
        # — a fact about the invocation, not about the codebook — and it lies
        # both ways: --codebook <the shipped file, spelled relatively> is not
        # the default path yet names the same document, while a foreign
        # study/codebook.json is indistinguishable by name from the shipped
        # one. Both codebooks are independently at 1.0.0, so the version field
        # cannot repair either; the name is what carries identity.
        codebook_file=codebook_path.name,
    )
    notes = degradation + (
        ["transcription gaps: " + "; ".join(partial)] if partial else []
    )
    # The docx displays consecutive same-label units merged into readable
    # turns; the sidecar keeps the unit-level labels (the research record).
    if not turns or not all("label" in t for t in turns):
        print("ERROR: render requires labeled turns — run concordance first",
              file=sys.stderr)
        return 1
    if episodes is not None and not all("episode_id" in t for t in turns):
        # Same fail-closed shape as the guard directly above. render stays pure
        # assembly and does not re-validate the layer — but recording an
        # episode layer the turn layer was never reconciled against writes a
        # research record whose two halves disagree, and nothing else in the
        # pipeline forces validate-episodes to have run before render.
        print("ERROR: episodes.json is present but the turns carry no "
              "episode_id — run validate-episodes first", file=sys.stderr)
        return 1
    display_turns = merge_labeled_turns(turns)
    docx_path = write_docx(
        build_docx_parts(display_turns, flags, claim=sidecar["accuracy_claim"],
                         notes=notes, names=names),
        base / "transcript.docx",
    )
    _save(base / "sidecar.json", sidecar)
    print(f"DOCX: {docx_path}")
    print(f"SIDECAR: {base / 'sidecar.json'}")
    print(f"CLAIM: {sidecar['accuracy_claim']}")
    return 0


def cmd_corpus_summary(args) -> int:
    """Aggregate every sidecar under `folder` into corpus_summary.json.

    Deliberately takes NO --codebook: aggregation is codebook-agnostic — it
    counts whatever the sidecars themselves record. An accepted-and-ignored
    argument would read as a filter and mislead.
    """
    folder = Path(args.folder)
    sidecar_paths = sorted(folder.glob("*_interview/sidecar.json"))
    sidecars = []
    for path in sidecar_paths:
        sc = _load(path)
        if not isinstance(sc, dict) or "interview" not in sc or "accuracy_claim" not in sc:
            print(f"WARNING: skipping non-interview sidecar: {path}", file=sys.stderr)
            continue
        sidecars.append(sc)
    summary = summarize_corpus(sidecars)
    # Back-compat alias: pre-episode consumers read flags_by_emotion.
    summary["flags_by_emotion"] = summary["flags_by_affect"]
    if summary["mixed_constructs"]:
        print("WARNING: this corpus spans more than one codebook "
              f"({', '.join(sorted(summary['codebooks']))}). Marker vocabularies "
              "differ between codebooks, so flags_by_marker and marker_by_outcome "
              "sum incompatible constructs — read per_interview[].codebook instead.",
              file=sys.stderr)
    _save(folder / "corpus_summary.json", summary)
    print(json.dumps(summary, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    """The full subcommand parser.

    Split out of main() so tests can build their `args` THROUGH it rather than
    hand-rolling a namespace: a hand-rolled one is a second copy of this
    contract, and it keeps passing after a subcommand gains an argument the
    real CLI now requires.
    """
    parser = argparse.ArgumentParser(prog="interview.py")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("preflight")
    p = sub.add_parser("setup"); p.add_argument("--open", action="store_true")
    p = sub.add_parser("discover"); p.add_argument("folder")
    p = sub.add_parser("transcribe"); p.add_argument("media"); p.add_argument("--out-dir")
    p = sub.add_parser("finalize"); p.add_argument("--work", required=True); p.add_argument("--unit", choices=["segment", "gap"], default="segment")
    p = sub.add_parser("concordance"); p.add_argument("--work", required=True)
    p = sub.add_parser("validate-episodes"); p.add_argument("--work", required=True); p.add_argument("--codebook", metavar="PATH", help="codebook whose episode_schema/arc_schema govern validation (default: shipped codebook.json)")
    p = sub.add_parser("validate-flags"); p.add_argument("--work", required=True); p.add_argument("--duration"); p.add_argument("--codebook", metavar="PATH", help="alternate codebook file (default: shipped codebook.json)")
    p = sub.add_parser("frames"); p.add_argument("media"); p.add_argument("--out-dir")
    p = sub.add_parser("render"); p.add_argument("media"); p.add_argument("--out-dir")
    # Optional speaker display names (default: the canonical role labels).
    p.add_argument("--interviewer", metavar="NAME", help="display name for INTERVIEWER turns")
    p.add_argument("--interviewee", metavar="NAME", help="display name for INTERVIEWEE turns")
    p.add_argument("--other", metavar="NAME", help="display name for OTHER turns")
    p.add_argument("--unclear", metavar="NAME", help="display name for UNCLEAR turns")
    p.add_argument("--codebook", metavar="PATH", help="alternate codebook file (default: shipped codebook.json)")
    p.add_argument("--persona", metavar="NAME", help="the confronter's per-video persona, recorded in the sidecar")
    p = sub.add_parser("corpus-summary"); p.add_argument("folder")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    handlers = {
        "preflight": cmd_preflight, "setup": cmd_setup, "discover": cmd_discover,
        "transcribe": cmd_transcribe, "finalize": cmd_finalize,
        "concordance": cmd_concordance,
        "validate-episodes": cmd_validate_episodes,
        "validate-flags": cmd_validate_flags,
        "frames": cmd_frames, "render": cmd_render,
        "corpus-summary": cmd_corpus_summary,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
