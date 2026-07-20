"""Episode-aware corpus aggregation: analyze.summarize_corpus /
analyze.sidecar_codebook, and the cmd_corpus_summary wiring around them
(back-compat alias, the mixed-construct stderr warning, corpus_summary.json).

The central hazard under test: `flags_by_marker` is a sum over whatever marker
vocabularies the sidecars happen to carry. `emotional_display` (narrative
gravity) and `attribution_of_blame` (moral identity) are different constructs,
so a folder mixing codebooks must say so loudly rather than serve one
authoritative-looking table spanning two vocabularies.
"""
from __future__ import annotations

import json
import pytest

import interview
from analyze import sidecar_codebook, summarize_corpus
from render import build_sidecar

MORAL = "codebook_moral_identity.json"
NARRATIVE = "codebook.json"
DUAL = {"groq": "whisper-large-v3", "openai": "whisper-1"}
SOLO = {"groq": "whisper-large-v3"}
NOW = "2026-07-19T09:00:00-04:00"

DUAL_CLAIM = "dual-engine verified with logged adjudication"
SOLO_CLAIM = "single-engine UNVERIFIED"


def sidecar(media, *, flags=(), episodes=None, persona=None,
            codebook_file=MORAL, codebook_version="1.0.0", engines=None):
    """A realistic sidecar, built by the SAME function the pipeline uses.

    Hand-built sidecar fixtures drift out of representativeness silently (a
    Task 7 review found one testing nothing), so every fixture here goes
    through build_sidecar and only the fields under test vary.
    """
    return build_sidecar(
        media=media, duration=200.0, engines=dict(engines or DUAL),
        degradation=[], segments=[], turns=[], adjudications=[],
        flags=[dict(f) for f in flags], partial_failures=[],
        codebook_version=codebook_version, now=NOW,
        episodes=[dict(e) for e in episodes] if episodes is not None else None,
        persona=persona, codebook_file=codebook_file,
    )


def legacy_sidecar(media, *, flags=()):
    """A PRE-1.1 sidecar, derived from the real builder then walked back to the
    shape the pre-episode pipeline actually wrote: schema_version 1.0, no
    `codebook_file` key at all, no `episodes`, affect carried in `emotion`.

    Deriving it (rather than hand-writing a dict) keeps everything the two
    generations still share — interview block, accuracy claim, flag stamping —
    honest to the current builder.
    """
    sc = sidecar(media, flags=flags, codebook_file=None)
    sc["schema_version"] = "1.0"
    del sc["codebook_file"]
    assert "episodes" not in sc  # the fixture's whole point
    return sc


def write_corpus(tmp_path, objects):
    """{output-dir stem: any JSON object} → folder/<stem>_interview/sidecar.json"""
    folder = tmp_path / "corpus"
    folder.mkdir(parents=True, exist_ok=True)
    for stem, obj in objects.items():
        d = folder / f"{stem}_interview"
        d.mkdir(parents=True, exist_ok=True)
        (d / "sidecar.json").write_text(json.dumps(obj), encoding="utf-8")
    return folder


def corpus_args(folder):
    """Build args THROUGH the real parser — a hand-rolled namespace is a second
    copy of the CLI contract that keeps passing after the real one moves."""
    return interview.build_parser().parse_args(["corpus-summary", str(folder)])


def read_summary(folder):
    return json.loads((folder / "corpus_summary.json").read_text(encoding="utf-8"))


EPISODES_A = [
    {"id": "e01", "type": "confrontation", "t_start": 0.0, "t_end": 50.0,
     "target_descriptor": "woman in the garage", "target_speech": True,
     "arc": {"phases": ["threat", "softening"], "outcome": "complies"}},
    {"id": "e02", "type": "confrontation", "t_start": 50.0, "t_end": 100.0,
     "target_descriptor": "man with the hose", "target_speech": True,
     "arc": {"phases": ["threat", "escalation"], "outcome": "refuses"}},
    # Non-confrontation, yet carrying an outcome: episode_outcomes answers "how
    # do CONFRONTATIONS end", so this outcome must never appear there.
    {"id": "e03", "type": "to-camera", "t_start": 100.0, "t_end": 150.0,
     "arc": {"outcome": "n/a"}},
    # A confrontation whose arc was never coded: it contributes NO outcome (an
    # uncoded arc is not an outcome of "None"), and the flag filed here belongs
    # in no cross-tab cell either.
    {"id": "e04", "type": "confrontation", "t_start": 150.0, "t_end": 200.0,
     "target_descriptor": "the dog walker", "target_speech": False},
]

FLAGS_A = [
    {"id": "g0001", "marker_types": ["attribution_of_blame"], "affect": "anger",
     "quote": "Don't touch my property.", "t_start": 5.0, "t_end": 9.0,
     "salience": 3, "speaker_role": "INTERVIEWEE", "episode_id": "e01"},
    # Carries BOTH affect keys. `affect` is the moral-identity field; `emotion`
    # is the stale leftover a codebook copy-edited from the narrative one
    # leaves behind (the same hazard validate_flags guards its vocabulary
    # against). The 1.1 field must win.
    {"id": "g0002", "marker_types": ["attribution_of_blame", "camera_awareness"],
     "affect": "contempt", "emotion": "sadness",
     "quote": "You people are the problem.", "t_start": 60.0, "t_end": 66.0,
     "salience": 4, "speaker_role": "INTERVIEWEE", "episode_id": "e02"},
    {"id": "g0003", "marker_types": ["camera_awareness"],
     "quote": "You can film all you want.", "t_start": 160.0, "t_end": 164.0,
     "salience": 2, "speaker_role": "INTERVIEWEE", "episode_id": "e04"},
]

EPISODES_B = [
    {"id": "e01", "type": "confrontation", "t_start": 0.0, "t_end": 200.0,
     "target_descriptor": "the site foreman", "target_speech": True,
     "arc": {"phases": ["threat", "flip"], "outcome": "complies"}},
]

FLAGS_B = [
    {"id": "g0001", "marker_types": ["dehumanization"], "affect": "anger",
     "quote": "They're animals.", "t_start": 10.0, "t_end": 14.0,
     "salience": 5, "speaker_role": "INTERVIEWEE", "episode_id": "e01"},
]

NARRATIVE_FLAGS = [
    {"id": "g0001", "marker_types": ["emotional_display"], "emotion": "anger",
     "quote": "Don't touch my property.", "t_start": 5.0, "t_end": 9.0,
     "salience": 4},
]


def moral_pair():
    """Two episode-aware moral-identity sidecars — one dual-engine with a
    persona, one single-engine with a different persona."""
    return (
        sidecar("a.mp4", flags=FLAGS_A, episodes=EPISODES_A,
                persona="the loud neighbor"),
        sidecar("b.mp4", flags=FLAGS_B, episodes=EPISODES_B,
                persona="the polite surveyor", engines=SOLO),
    )


class TestSummarizeCorpus:
    def test_aggregates_markers_affect_outcomes_and_cross_tab(self):
        summary = summarize_corpus(list(moral_pair()))
        assert summary["interviews"] == 2
        assert summary["flags_by_marker"] == {
            "attribution_of_blame": 2, "camera_awareness": 2, "dehumanization": 1,
        }
        # `sadness` (the stale `emotion` on g0002) must not appear: `affect`
        # wins wherever both are present.
        assert summary["flags_by_affect"] == {"anger": 2, "contempt": 1}
        # e03's "n/a" is a to-camera outcome and is excluded; both
        # confrontations from A plus B's one are counted.
        assert summary["episode_outcomes"] == {"complies": 2, "refuses": 1}
        # g0003 sits in e04, which has no arc — it contributes no cell at all.
        assert summary["marker_by_outcome"] == {
            "attribution_of_blame|complies": 1,
            "attribution_of_blame|refuses": 1,
            "camera_awareness|refuses": 1,
            "dehumanization|complies": 1,
        }

    def test_per_interview_rows_and_personas(self):
        summary = summarize_corpus(list(moral_pair()))
        assert summary["per_interview"] == [
            {"media": "a.mp4", "flags": 3, "episodes": 4, "codebook": MORAL,
             "claim": DUAL_CLAIM},
            {"media": "b.mp4", "flags": 1, "episodes": 1, "codebook": MORAL,
             "claim": SOLO_CLAIM},
        ]
        # order follows the sidecar order, so a corpus stays traceable back to
        # which video wore which persona
        assert summary["personas"] == ["the loud neighbor", "the polite surveyor"]

    def test_single_codebook_corpus_is_not_mixed(self):
        summary = summarize_corpus(list(moral_pair()))
        assert summary["codebooks"] == {MORAL: 2}
        assert summary["mixed_constructs"] is False

    def test_mixed_codebooks_flag_incompatible_vocabularies(self):
        """THE hazard: two vocabularies summed into one table. The counts are
        still produced (they are per-interview-traceable), but the corpus must
        announce that the flat table spans incompatible constructs."""
        summary = summarize_corpus([
            sidecar("a.mp4", flags=FLAGS_A, episodes=EPISODES_A),
            sidecar("n.mp4", flags=NARRATIVE_FLAGS, codebook_file=NARRATIVE),
        ])
        assert summary["mixed_constructs"] is True
        assert summary["codebooks"] == {MORAL: 1, NARRATIVE: 1}
        # the sum that means nothing — and the per-row key that repairs it
        assert summary["flags_by_marker"]["emotional_display"] == 1
        assert summary["flags_by_marker"]["attribution_of_blame"] == 2
        assert [r["codebook"] for r in summary["per_interview"]] == [MORAL, NARRATIVE]

    def test_old_sidecars_without_episodes_still_aggregate(self):
        """Pre-1.1 sidecars are the existing corpus. They must keep summarizing:
        marker and affect counts from `emotion`, and no episode-derived keys."""
        summary = summarize_corpus([
            legacy_sidecar("old1.mp4", flags=NARRATIVE_FLAGS),
            legacy_sidecar("old2.mp4", flags=NARRATIVE_FLAGS),
        ])
        assert summary["flags_by_marker"] == {"emotional_display": 2}
        # read through the `emotion` fallback — these flags carry no `affect`
        assert summary["flags_by_affect"] == {"anger": 2}
        assert summary["episode_outcomes"] == {}
        # every flag has episode_id absent → no cross-tab cells at all
        assert summary["marker_by_outcome"] == {}
        assert summary["personas"] == []
        assert summary["codebooks"] == {NARRATIVE: 2}
        assert summary["mixed_constructs"] is False
        assert [r["episodes"] for r in summary["per_interview"]] == [0, 0]
        assert [r["codebook"] for r in summary["per_interview"]] == [NARRATIVE, NARRATIVE]

    def test_empty_corpus(self):
        summary = summarize_corpus([])
        assert summary["interviews"] == 0
        assert summary["mixed_constructs"] is False
        assert summary["codebooks"] == {}
        assert summary["personas"] == []

    def test_hand_edited_sidecars_do_not_crash_the_corpus(self):
        """corpus-summary walks sidecar.json files off disk, and nothing
        re-validates them: a researcher's hand-edit, or a foreign producer, can
        put a non-object in `episodes`, drop `marker_types`, or write an empty
        persona. None of that may take down the aggregation or invent counts."""
        broken = sidecar("x.mp4", flags=[{"id": "g0001", "affect": "anger",
                                          "episode_id": "e01"}],
                         episodes=[EPISODES_A[0]])
        broken["episodes"].append("e02")          # not an object
        broken["interview"]["persona"] = ""       # "" is not a persona
        bare = {"interview": {"media": "y.mp4"}, "accuracy_claim": SOLO_CLAIM,
                "schema_version": "1.0"}          # no flags, no episodes keys

        summary = summarize_corpus([broken, bare])

        assert summary["interviews"] == 2
        assert summary["flags_by_marker"] == {}   # the flag has no marker_types
        assert summary["flags_by_affect"] == {"anger": 1}
        assert summary["episode_outcomes"] == {"complies": 1}
        assert summary["marker_by_outcome"] == {}
        assert summary["personas"] == []
        assert [r["flags"] for r in summary["per_interview"]] == [1, 0]
        assert [r["episodes"] for r in summary["per_interview"]] == [2, 0]


class TestSidecarCodebook:
    def test_records_the_file_the_run_named(self):
        sc = sidecar("a.mp4", codebook_file=MORAL)
        assert sc["schema_version"] == "1.1"
        assert sidecar_codebook(sc) == MORAL

    def test_a_foreign_codebook_of_the_same_name_is_still_named(self):
        # identity is carried by the name; the version cannot repair it
        assert sidecar_codebook(sidecar("a.mp4", codebook_file="study7.json")) == "study7.json"

    def test_pre_11_absence_means_the_shipped_codebook(self):
        assert sidecar_codebook({"schema_version": "1.0"}) == NARRATIVE
        assert sidecar_codebook(legacy_sidecar("old.mp4")) == NARRATIVE

    def test_no_schema_version_at_all_is_pre_11(self):
        assert sidecar_codebook({}) == NARRATIVE

    def test_11_without_a_codebook_file_is_unknown_not_the_shipped_one(self):
        """The gate's whole point. 1.1 records `codebook_file` unconditionally,
        so its absence there is missing information — claiming the shipped
        codebook would manufacture a construct label out of nothing."""
        assert sidecar_codebook({"schema_version": "1.1"}) == "unknown"
        # build_sidecar writes the key as an explicit None when none was named
        sc = sidecar("a.mp4", codebook_file=None)
        assert sc["codebook_file"] is None
        assert sidecar_codebook(sc) == "unknown"

    def test_future_schema_versions_are_unknown_too(self):
        assert sidecar_codebook({"schema_version": "1.2"}) == "unknown"


class TestCmdCorpusSummary:
    def test_writes_the_summary_file_and_prints_it(self, tmp_path, capsys):
        a, b = moral_pair()
        folder = write_corpus(tmp_path, {"a": a, "b": b})

        assert interview.cmd_corpus_summary(corpus_args(folder)) == 0

        out = capsys.readouterr().out
        on_disk = read_summary(folder)
        # what is printed IS what is persisted — the two must not drift
        assert on_disk == json.loads(out)
        assert on_disk["interviews"] == 2
        assert on_disk["codebooks"] == {MORAL: 2}
        assert on_disk["episode_outcomes"] == {"complies": 2, "refuses": 1}

    def test_single_codebook_corpus_prints_no_warning(self, tmp_path, capsys):
        a, b = moral_pair()
        folder = write_corpus(tmp_path, {"a": a, "b": b})
        assert interview.cmd_corpus_summary(corpus_args(folder)) == 0
        err = capsys.readouterr().err
        assert err == ""
        assert read_summary(folder)["mixed_constructs"] is False

    def test_mixed_corpus_warns_loudly_on_stderr(self, tmp_path, capsys):
        folder = write_corpus(tmp_path, {
            "a": sidecar("a.mp4", flags=FLAGS_A, episodes=EPISODES_A),
            "n": sidecar("n.mp4", flags=NARRATIVE_FLAGS, codebook_file=NARRATIVE),
        })

        assert interview.cmd_corpus_summary(corpus_args(folder)) == 0

        err = capsys.readouterr().err
        assert "WARNING" in err
        assert "more than one codebook" in err
        assert MORAL in err and NARRATIVE in err
        # names the repair, not just the problem
        assert "per_interview[].codebook" in err
        assert read_summary(folder)["mixed_constructs"] is True

    def test_flags_by_emotion_alias_survives_for_old_consumers(self, tmp_path, capsys):
        folder = write_corpus(tmp_path, {
            "old": legacy_sidecar("old.mp4", flags=NARRATIVE_FLAGS),
        })
        assert interview.cmd_corpus_summary(corpus_args(folder)) == 0
        capsys.readouterr()
        on_disk = read_summary(folder)
        assert on_disk["flags_by_emotion"] == {"anger": 1}
        assert on_disk["flags_by_emotion"] == on_disk["flags_by_affect"]

    def test_alias_tracks_affect_from_the_11_field_too(self, tmp_path, capsys):
        """The alias is not "the old emotion counter" — it is the affect table
        under its old name, so a 1.1 corpus reaches old consumers as well."""
        folder = write_corpus(tmp_path, {
            "a": sidecar("a.mp4", flags=FLAGS_A, episodes=EPISODES_A),
        })
        assert interview.cmd_corpus_summary(corpus_args(folder)) == 0
        capsys.readouterr()
        on_disk = read_summary(folder)
        assert on_disk["flags_by_emotion"] == {"anger": 1, "contempt": 1}
        assert on_disk["flags_by_emotion"] == on_disk["flags_by_affect"]

    def test_non_interview_sidecar_is_skipped_with_a_warning(self, tmp_path, capsys):
        a, _ = moral_pair()
        folder = write_corpus(tmp_path, {
            "a": a,
            # a codebook parked in a sidecar.json — has neither `interview` nor
            # `accuracy_claim`, so it is not a research record
            "junk": {"codebook_version": "1.0.0", "markers": []},
        })

        assert interview.cmd_corpus_summary(corpus_args(folder)) == 0

        err = capsys.readouterr().err
        assert "skipping non-interview sidecar" in err
        summary = read_summary(folder)
        assert summary["interviews"] == 1
        # and it did not smuggle a phantom codebook into the corpus
        assert summary["codebooks"] == {MORAL: 1}
        assert summary["mixed_constructs"] is False

    def test_empty_folder_summarizes_to_zero(self, tmp_path, capsys):
        folder = write_corpus(tmp_path, {})
        assert interview.cmd_corpus_summary(corpus_args(folder)) == 0
        assert capsys.readouterr().err == ""
        assert read_summary(folder)["interviews"] == 0

    def test_corpus_summary_takes_no_codebook_argument(self, capsys):
        """Deliberate: aggregation is codebook-agnostic — it counts what the
        sidecars record. An accepted-and-ignored --codebook would read as a
        filter and mislead."""
        with pytest.raises(SystemExit):
            interview.build_parser().parse_args(
                ["corpus-summary", "somewhere", "--codebook", "x.json"])
