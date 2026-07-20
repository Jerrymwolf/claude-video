"""Episode-aware corpus aggregation: analyze.summarize_corpus /
analyze.sidecar_codebook, and the cmd_corpus_summary wiring around them
(back-compat alias, the construct-validity warnings, corpus_summary.json).

The central hazard under test: `flags_by_marker` is a sum over whatever marker
vocabularies the sidecars happen to carry. `emotional_display` (narrative
gravity) and `attribution_of_blame` (moral identity) are different constructs,
so a folder mixing codebooks must say so loudly — in the persisted artifact,
not only on a terminal the reader may never have seen — and must publish the
disaggregated per-codebook truth beside the rollup.
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
    """{output-dir stem: any JSON object} → folder/<stem>_interview/sidecar.json

    Written in the mapping's own order, which is deliberately NOT always
    alphabetical — see test_rows_follow_sorted_path_order.
    """
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
    # Non-confrontation, yet carrying an outcome — and it HOLDS A FLAG, which
    # is what makes it pin the cross-tab as well as episode_outcomes. "n/a" on
    # a to-camera aside is not an answer to "how did the confrontation end", so
    # it must raise neither an outcome bucket nor a `marker|n/a` column.
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
    # Inside the to-camera episode that DOES carry an outcome.
    {"id": "g0004", "marker_types": ["audience_address"],
     "quote": "That is what they do, folks.", "t_start": 110.0, "t_end": 115.0,
     "salience": 2, "speaker_role": "INTERVIEWEE", "episode_id": "e03"},
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
    def test_aggregates_markers_and_affect(self):
        summary = summarize_corpus(list(moral_pair()))
        assert summary["interviews"] == 2
        assert summary["flags_by_marker"] == {
            "attribution_of_blame": 2, "camera_awareness": 2,
            "audience_address": 1, "dehumanization": 1,
        }
        # `sadness` (the stale `emotion` on g0002) must not appear: `affect`
        # wins wherever both are present.
        assert summary["flags_by_affect"] == {"anger": 2, "contempt": 1}

    def test_outcome_tables_share_one_confrontation_scope(self):
        """Both outcome tables answer "how did the confrontation end", so both
        draw on one set of episodes — and the corpus publishes that set's size
        rather than making the reader derive it."""
        summary = summarize_corpus(list(moral_pair()))
        # e03's to-camera "n/a" is excluded; e04's uncoded arc contributes
        # nothing; A's two coded confrontations plus B's one are counted.
        assert summary["episode_outcomes"] == {"complies": 2, "refuses": 1}
        assert summary["confrontations_with_outcome"] == 3
        # the reconciliation property, asserted rather than promised in prose
        assert summary["confrontations_with_outcome"] == sum(
            summary["episode_outcomes"].values())

    def test_cross_tab_excludes_non_confrontation_outcomes(self):
        """g0004 sits in e03 — a to-camera episode carrying outcome "n/a". An
        `audience_address|n/a` column would read as a real outcome column and
        mean nothing: the same class of error as summing two codebooks."""
        summary = summarize_corpus(list(moral_pair()))
        assert summary["marker_by_outcome"] == {
            "attribution_of_blame|complies": 1,
            "attribution_of_blame|refuses": 1,
            "camera_awareness|refuses": 1,
            "dehumanization|complies": 1,
        }
        # nothing is lost: the excluded flag still counts as a marker
        assert summary["flags_by_marker"]["audience_address"] == 1

    def test_per_interview_rows(self):
        summary = summarize_corpus(list(moral_pair()))
        assert summary["per_interview"] == [
            {"media": "a.mp4", "flags": 4, "episodes": 4, "codebook": MORAL,
             "persona": "the loud neighbor", "claim": DUAL_CLAIM},
            {"media": "b.mp4", "flags": 1, "episodes": 1, "codebook": MORAL,
             "persona": "the polite surveyor", "claim": SOLO_CLAIM},
        ]

    def test_persona_binds_to_its_row_when_only_some_have_one(self):
        """The row is the authoritative binding. The flat `personas` list is
        COMPACTED, so its positions do not line up with per_interview — reading
        personas[0] as the first interview's persona is wrong exactly here."""
        summary = summarize_corpus([
            sidecar("a.mp4", flags=FLAGS_A, episodes=EPISODES_A),  # no persona
            sidecar("b.mp4", flags=FLAGS_B, episodes=EPISODES_B,
                    persona="the polite surveyor"),
        ])
        assert [(r["media"], r["persona"]) for r in summary["per_interview"]] == [
            ("a.mp4", None), ("b.mp4", "the polite surveyor"),
        ]
        # the trap: index 0 of the flat list is interview TWO's persona
        assert summary["personas"] == ["the polite surveyor"]

    def test_personas_list_keeps_corpus_order(self):
        summary = summarize_corpus(list(moral_pair()))
        assert summary["personas"] == ["the loud neighbor", "the polite surveyor"]

    def test_single_codebook_corpus_is_not_mixed(self):
        summary = summarize_corpus(list(moral_pair()))
        assert summary["codebooks"] == {MORAL: 2}
        assert summary["mixed_constructs"] is False
        assert summary["warnings"] == []
        # one bucket, and it carries the whole corpus
        assert list(summary["by_codebook"]) == [MORAL]
        assert summary["by_codebook"][MORAL]["flags_by_marker"] == summary["flags_by_marker"]

    def test_mixed_codebooks_flag_incompatible_vocabularies(self):
        """THE hazard: two vocabularies summed into one table. The rollup is
        still produced (pre-1.1 consumers read it), but the corpus must
        announce the problem IN THE FILE and publish the honest breakdown."""
        summary = summarize_corpus([
            sidecar("a.mp4", flags=FLAGS_A, episodes=EPISODES_A),
            sidecar("n.mp4", flags=NARRATIVE_FLAGS, codebook_file=NARRATIVE),
        ])
        assert summary["mixed_constructs"] is True
        assert summary["codebooks"] == {MORAL: 1, NARRATIVE: 1}
        # the sum that means nothing — deliberately retained, not suppressed
        assert summary["flags_by_marker"]["emotional_display"] == 1
        assert summary["flags_by_marker"]["attribution_of_blame"] == 2
        # and the per-row key that repairs it
        assert [r["codebook"] for r in summary["per_interview"]] == [MORAL, NARRATIVE]

    def test_mixed_corpus_warns_in_the_persisted_record(self):
        summary = summarize_corpus([
            sidecar("a.mp4", flags=FLAGS_A, episodes=EPISODES_A),
            sidecar("n.mp4", flags=NARRATIVE_FLAGS, codebook_file=NARRATIVE),
        ])
        assert len(summary["warnings"]) == 1
        text = summary["warnings"][0]
        assert "more than one codebook" in text
        assert MORAL in text and NARRATIVE in text
        # names the repair, not just the problem
        assert "by_codebook" in text and "per_interview[].codebook" in text

    def test_by_codebook_disaggregates_the_rollup(self):
        summary = summarize_corpus([
            sidecar("a.mp4", flags=FLAGS_A, episodes=EPISODES_A),
            sidecar("n.mp4", flags=NARRATIVE_FLAGS, codebook_file=NARRATIVE),
        ])
        assert summary["by_codebook"] == {
            MORAL: {
                "flags_by_marker": {"attribution_of_blame": 2,
                                    "camera_awareness": 2,
                                    "audience_address": 1},
                "flags_by_affect": {"anger": 1, "contempt": 1},
                "episode_outcomes": {"complies": 1, "refuses": 1},
            },
            NARRATIVE: {
                "flags_by_marker": {"emotional_display": 1},
                "flags_by_affect": {"anger": 1},
                "episode_outcomes": {},
            },
        }

    def test_unrecorded_provenance_is_a_different_finding(self):
        """"codebook.json + unknown" is one known vocabulary plus sidecars that
        recorded none — possibly the same codebook, unprovably so. Reporting it
        in the words of the two-vocabulary case would overstate it."""
        no_provenance = sidecar("u.mp4", flags=NARRATIVE_FLAGS, codebook_file=None)
        assert no_provenance["schema_version"] == "1.1"  # so it resolves to "unknown"
        summary = summarize_corpus([
            legacy_sidecar("old.mp4", flags=NARRATIVE_FLAGS),
            no_provenance,
        ])
        assert summary["codebooks"] == {NARRATIVE: 1, "unknown": 1}
        assert summary["mixed_constructs"] is True  # conservative
        text = summary["warnings"][0]
        assert "unrecorded codebook provenance" in text
        assert "more than one codebook" not in text
        assert NARRATIVE in text and "unknown" in text

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
        assert summary["confrontations_with_outcome"] == 0
        # every flag has episode_id absent → no cross-tab cells at all
        assert summary["marker_by_outcome"] == {}
        assert summary["personas"] == []
        assert summary["codebooks"] == {NARRATIVE: 2}
        assert summary["mixed_constructs"] is False
        assert summary["warnings"] == []
        assert [r["episodes"] for r in summary["per_interview"]] == [0, 0]
        assert [r["codebook"] for r in summary["per_interview"]] == [NARRATIVE, NARRATIVE]
        assert [r["persona"] for r in summary["per_interview"]] == [None, None]

    def test_empty_corpus(self):
        summary = summarize_corpus([])
        assert summary["interviews"] == 0
        assert summary["mixed_constructs"] is False
        assert summary["codebooks"] == {}
        assert summary["by_codebook"] == {}
        assert summary["warnings"] == []
        assert summary["personas"] == []
        assert summary["confrontations_with_outcome"] == 0


class TestMalformedSidecars:
    """`summarize_corpus` is a pure function with no caller to assume — its own
    tests import it directly, and cmd_corpus_summary's pre-filter checks key
    PRESENCE, not shape. corpus-summary also runs ONCE at the end of a long,
    expensive batch: one hand-edited file must degrade to zero counts, never
    take the whole summary down with a traceback.
    """

    def test_hand_edited_episodes_and_flags(self):
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
        assert [r["persona"] for r in summary["per_interview"]] == [None, None]
        assert [r["flags"] for r in summary["per_interview"]] == [1, 0]
        assert [r["episodes"] for r in summary["per_interview"]] == [2, 0]

    def test_a_string_marker_types_does_not_invent_markers(self):
        """"abc" iterates as characters. Counting a, b and c would be silent
        count invention — the same hazard validate_episodes guards arc.phases
        against, one function over."""
        sc = sidecar("x.mp4", flags=[{"id": "g0001", "marker_types": "abc",
                                      "episode_id": "e01"}],
                     episodes=[EPISODES_A[0]])
        summary = summarize_corpus([sc])
        assert summary["flags_by_marker"] == {}
        assert summary["marker_by_outcome"] == {}
        assert summary["per_interview"][0]["flags"] == 1

    @pytest.mark.parametrize("block, media", [
        ("oops", None),          # a string where the block should be
        ({}, None),              # present but empty — no media key
        (None, None),
        ({"media": "z.mp4"}, "z.mp4"),
    ])
    def test_interview_block_shapes(self, block, media):
        summary = summarize_corpus([
            {"interview": block, "accuracy_claim": SOLO_CLAIM},
        ])
        assert summary["interviews"] == 1
        assert summary["per_interview"][0]["media"] == media

    @pytest.mark.parametrize("flags", [
        {"g1": {}},              # a map keyed by flag id
        "g0001",                 # a bare string
        ["g0001", 7, None],      # a list of non-objects
        None,
    ])
    def test_flag_container_shapes(self, flags):
        summary = summarize_corpus([
            {"interview": {"media": "z.mp4"}, "accuracy_claim": SOLO_CLAIM,
             "flags": flags},
        ])
        assert summary["flags_by_marker"] == {}
        assert summary["per_interview"][0]["flags"] == 0

    @pytest.mark.parametrize("episodes", [{"e01": {}}, "e01", 7, None])
    def test_episode_container_shapes(self, episodes):
        summary = summarize_corpus([
            {"interview": {"media": "z.mp4"}, "accuracy_claim": SOLO_CLAIM,
             "episodes": episodes},
        ])
        assert summary["episode_outcomes"] == {}
        assert summary["per_interview"][0]["episodes"] == 0

    def test_missing_accuracy_claim_reads_as_null_not_a_crash(self):
        summary = summarize_corpus([{"interview": {"media": "z.mp4"}}])
        assert summary["per_interview"][0]["claim"] is None

    def test_a_non_object_sidecar_is_skipped_entirely(self):
        summary = summarize_corpus(["not a sidecar", None,
                                    sidecar("a.mp4", flags=FLAGS_B)])
        assert summary["interviews"] == 1
        assert [r["media"] for r in summary["per_interview"]] == ["a.mp4"]

    def test_an_episode_without_a_usable_id_keys_nothing(self):
        """No flag's episode_id can name an episode that has no id, so such an
        episode can key no outcome — and dereferencing e["id"] to discover that
        would take the whole corpus down on one hand-edited file."""
        sc = sidecar("x.mp4", flags=[
            {"id": "g0001", "marker_types": ["dehumanization"],
             "episode_id": "e01"}],
            episodes=[
                {"type": "confrontation", "arc": {"outcome": "refuses"}},
                {"id": "", "type": "confrontation", "arc": {"outcome": "escalates"}},
                EPISODES_A[0],
            ])
        summary = summarize_corpus([sc])
        assert summary["episode_outcomes"] == {"complies": 1}
        assert summary["confrontations_with_outcome"] == 1
        assert summary["marker_by_outcome"] == {"dehumanization|complies": 1}
        # they are still episodes for counting purposes — just not keyed ones
        assert summary["per_interview"][0]["episodes"] == 3

    def test_duplicate_episode_ids_collapse_consistently(self):
        """validate_episodes rejects duplicate ids at authoring time, but this
        function reads sidecars off disk where nothing re-checks. One map feeds
        both outcome tables, so the collapse is last-wins in BOTH — the two can
        no longer disagree about how many episodes the corpus holds."""
        dup = sidecar("x.mp4", flags=[
            {"id": "g0001", "marker_types": ["dehumanization"],
             "episode_id": "e01"}],
            episodes=[
                dict(EPISODES_A[0]),
                dict(EPISODES_A[0], arc={"outcome": "refuses"}),
            ])
        summary = summarize_corpus([dup])
        assert summary["episode_outcomes"] == {"refuses": 1}
        assert summary["confrontations_with_outcome"] == 1
        assert summary["marker_by_outcome"] == {"dehumanization|refuses": 1}


class TestSidecarCodebook:
    def test_records_the_file_the_run_named(self):
        sc = sidecar("a.mp4", codebook_file=MORAL)
        assert sc["schema_version"] == "1.1"
        assert sidecar_codebook(sc) == MORAL

    def test_a_foreign_codebook_of_the_same_name_is_still_named(self):
        # identity is carried by the name; the version cannot repair it
        assert sidecar_codebook(sidecar("a.mp4", codebook_file="study7.json")) == "study7.json"

    def test_a_non_string_codebook_file_is_coerced(self):
        """The return value is used as a dict key and sorted into a warning
        message; a raw int would make `codebooks` un-sortable against the
        string keys beside it."""
        assert sidecar_codebook({"codebook_file": 7}) == "7"

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
        assert on_disk["confrontations_with_outcome"] == 3

    def test_rows_follow_sorted_path_order(self, tmp_path, capsys):
        """Path.glob's order is filesystem-dependent. Without the sort, row and
        persona order would vary by machine and the artifact would stop being
        reproducible — so the fixture is written OUT of alphabetical order."""
        folder = write_corpus(tmp_path, {
            "c": sidecar("c.mp4", persona="third"),
            "a": sidecar("a.mp4", persona="first"),
            "b": sidecar("b.mp4", persona="second"),
        })
        assert interview.cmd_corpus_summary(corpus_args(folder)) == 0
        capsys.readouterr()
        on_disk = read_summary(folder)
        assert [r["media"] for r in on_disk["per_interview"]] == [
            "a.mp4", "b.mp4", "c.mp4"]
        assert on_disk["personas"] == ["first", "second", "third"]

    def test_single_codebook_corpus_prints_no_warning(self, tmp_path, capsys):
        a, b = moral_pair()
        folder = write_corpus(tmp_path, {"a": a, "b": b})
        assert interview.cmd_corpus_summary(corpus_args(folder)) == 0
        assert capsys.readouterr().err == ""
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
        on_disk = read_summary(folder)
        assert on_disk["mixed_constructs"] is True
        # the terminal line and the persisted line are the same text by
        # construction, so a reader who only ever opens the file learns the
        # same thing the operator saw scroll past
        assert on_disk["warnings"] == [err.strip().removeprefix("WARNING: ")]

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

    def test_alias_is_a_copy_not_the_same_object(self, tmp_path, capsys, monkeypatch):
        """Two keys of a persisted artifact must not be one mutable object: an
        in-process consumer editing one would silently edit the other. Caught
        by intercepting the dict the command hands to _save."""
        saved = {}
        real_save = interview._save
        monkeypatch.setattr(interview, "_save",
                            lambda p, d: (saved.setdefault("summary", d),
                                          real_save(p, d))[1])
        a, _ = moral_pair()
        folder = write_corpus(tmp_path, {"a": a})
        assert interview.cmd_corpus_summary(corpus_args(folder)) == 0
        capsys.readouterr()
        summary = saved["summary"]
        assert summary["flags_by_emotion"] == summary["flags_by_affect"]
        assert summary["flags_by_emotion"] is not summary["flags_by_affect"]

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

    def test_a_sidecar_missing_only_its_claim_is_still_skipped(self, tmp_path, capsys):
        """Both halves of the pre-filter are load-bearing. An `interview` block
        with no accuracy claim is a truncated write, not a research record —
        admitting it would put a row with no accuracy claim in the corpus."""
        a, _ = moral_pair()
        folder = write_corpus(tmp_path, {
            "a": a,
            "half": {"interview": {"media": "half.mp4"}, "flags": []},
        })

        assert interview.cmd_corpus_summary(corpus_args(folder)) == 0

        assert "skipping non-interview sidecar" in capsys.readouterr().err
        summary = read_summary(folder)
        assert summary["interviews"] == 1
        assert [r["media"] for r in summary["per_interview"]] == ["a.mp4"]

    def test_a_sidecar_missing_its_interview_block_is_skipped(self, tmp_path, capsys):
        """The other half of the pre-filter. An accuracy claim with no
        interview block names no media — admitting it would put an anonymous
        row in the corpus that no researcher could trace to a video."""
        a, _ = moral_pair()
        folder = write_corpus(tmp_path, {
            "a": a,
            "anon": {"accuracy_claim": SOLO_CLAIM, "flags": [],
                     "schema_version": "1.0"},
        })

        assert interview.cmd_corpus_summary(corpus_args(folder)) == 0

        assert "skipping non-interview sidecar" in capsys.readouterr().err
        summary = read_summary(folder)
        assert summary["interviews"] == 1
        assert [r["media"] for r in summary["per_interview"]] == ["a.mp4"]

    def test_empty_folder_summarizes_to_zero(self, tmp_path, capsys):
        folder = write_corpus(tmp_path, {})
        assert interview.cmd_corpus_summary(corpus_args(folder)) == 0
        assert capsys.readouterr().err == ""
        assert read_summary(folder)["interviews"] == 0

    def test_corpus_summary_takes_no_codebook_argument(self):
        """Deliberate: aggregation is codebook-agnostic — it counts what the
        sidecars record. An accepted-and-ignored --codebook would read as a
        filter and mislead."""
        with pytest.raises(SystemExit):
            interview.build_parser().parse_args(
                ["corpus-summary", "somewhere", "--codebook", "x.json"])
