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
