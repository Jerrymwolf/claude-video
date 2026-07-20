"""CLI stage wiring: validate-episodes, validate-flags' --codebook /
turn-passing / flag-episode stamping / turn-flag drift detection, and render's
--codebook / --persona / episodes.json → sidecar recording."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import interview
from render import build_sidecar

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "interview" / "scripts"
SHIPPED_CODEBOOK = SCRIPTS / "codebook.json"
MORAL_CODEBOOK = SCRIPTS / "codebook_moral_identity.json"


def unit(tid, t0, t1, text, label="INTERVIEWEE", concordance=1.0, **over):
    u = {"id": tid, "start": t0, "end": t1, "text": text, "label": label,
         "concordance": concordance, "segment_indices": [0]}
    u.update(over)
    return u


EPISODES = [
    {"id": "e01", "type": "confrontation", "t_start": 0.0, "t_end": 100.0,
     "target_descriptor": "woman in the garage", "target_speech": True},
    {"id": "e02", "type": "to-camera", "t_start": 100.0, "t_end": 200.0},
]

TURNS = [
    unit("t0001", 0.0, 4.0, "Why is this cart here?", label="INTERVIEWER"),
    unit("t0002", 5.0, 9.0, "Don't touch my property."),
    unit("t0003", 105.0, 109.0, "You can film all you want."),
]

# Valid against codebook_moral_identity.json: real marker ids, real affect
# vocabulary, speaker_role inside coding_scope, full-concordance quoted turns.
MORAL_FLAGS = [
    {"id": "g0001", "marker_types": ["attribution_of_blame"],
     "quote": "Don't touch my property.", "t_start": 5.0, "t_end": 9.0,
     "salience": 3, "speaker_role": "INTERVIEWEE", "affect": "anger"},
    {"id": "g0002", "marker_types": ["camera_awareness"],
     "quote": "You can film all you want.", "t_start": 105.0, "t_end": 109.0,
     "salience": 2, "speaker_role": "INTERVIEWEE"},
]

# Valid against the shipped narrative-gravity codebook.json.
NARRATIVE_FLAGS = [
    {"id": "g0001", "marker_types": ["emotional_display"], "emotion": "anger",
     "quote": "Don't touch my property.", "t_start": 5.0, "t_end": 9.0,
     "salience": 4},
]


def make_work(tmp_path, *, turns=None, flags=None, episodes=None):
    work = tmp_path / "work"
    work.mkdir(parents=True, exist_ok=True)
    for name, data in (("diarized.json", turns), ("flags.json", flags),
                       ("episodes.json", episodes)):
        if data is not None:
            (work / name).write_text(json.dumps(data), encoding="utf-8")
    return work


def args_for(work, *extra, cmd="validate-episodes"):
    """Build args THROUGH the real parser, not a hand-rolled namespace — the
    fixture is then the CLI contract, and a newly-required argument fails here
    instead of passing against a stale parallel copy."""
    return interview.build_parser().parse_args([cmd, "--work", str(work), *extra])


def flag_args(work, *extra):
    return args_for(work, "--duration", "200", *extra, cmd="validate-flags")


def read(work, name):
    return json.loads((work / name).read_text(encoding="utf-8"))


class TestCmdValidateEpisodes:
    def test_valid_episodes_stamp_turns(self, tmp_path, capsys):
        work = make_work(tmp_path, turns=TURNS, episodes=EPISODES)
        assert interview.cmd_validate_episodes(args_for(work)) == 0
        # the stamped turn layer must reach DISK — the next stage reads the file
        assert [t["episode_id"] for t in read(work, "diarized.json")] == ["e01", "e01", "e02"]
        out = capsys.readouterr().out
        assert "EPISODES: 2" in out
        assert "e01 confrontation" in out and "turns=2" in out
        assert 'target="woman in the garage"' in out
        assert "e02 to-camera" in out and "turns=1" in out
        # target_descriptor belongs to confrontations only
        assert out.count("target=") == 1

    def test_invalid_episodes_error_and_leave_turns_unstamped(self, tmp_path, capsys):
        # e02 removed: t0003 at 105s now falls in no episode
        work = make_work(tmp_path, turns=TURNS, episodes=EPISODES[:1])
        assert interview.cmd_validate_episodes(args_for(work)) == 1
        assert "INVALID EPISODES" in capsys.readouterr().out
        assert all("episode_id" not in t for t in read(work, "diarized.json"))

    def test_codebook_flag_selects_episode_schema(self, tmp_path, capsys):
        cb = tmp_path / "narrow.json"
        cb.write_text(json.dumps({"codebook_version": "9.9.9", "markers": {},
                                  "episode_schema": {"types": ["confrontation"]}}),
                      encoding="utf-8")
        work = make_work(tmp_path, turns=TURNS, episodes=EPISODES)
        # the default (shipped codebook.json, no episode_schema) accepts to-camera
        assert interview.cmd_validate_episodes(args_for(work)) == 0
        capsys.readouterr()
        assert interview.cmd_validate_episodes(args_for(work, "--codebook", str(cb))) == 1
        assert "unknown type 'to-camera'" in capsys.readouterr().out

    def test_moral_codebook_episode_schema_accepts_the_pilot_shape(self, tmp_path):
        work = make_work(tmp_path, turns=TURNS, episodes=EPISODES)
        assert interview.cmd_validate_episodes(
            args_for(work, "--codebook", str(MORAL_CODEBOOK))) == 0

    def test_empty_turn_layer_is_rejected(self, tmp_path, capsys):
        # an episode layer covering nothing is not a valid episode layer: every
        # episode would print turns=0 and the stage would report success
        work = make_work(tmp_path, turns=[], episodes=EPISODES)
        assert interview.cmd_validate_episodes(args_for(work)) == 1
        assert "run concordance first" in capsys.readouterr().err

    def test_codebook_cannot_narrow_away_structural_fields(self, tmp_path, capsys):
        # `id`/`t_start`/`t_end` are data-model invariants: assign_episode_ids
        # and the summary loop dereference them, so a codebook narrowing
        # `required` must produce findings, never a KeyError traceback
        cb = tmp_path / "narrow.json"
        cb.write_text(json.dumps({"codebook_version": "9.9.9", "markers": {},
                                  "episode_schema": {"required": ["type"]}}),
                      encoding="utf-8")
        episodes = [{"type": "to-camera"}]
        work = make_work(tmp_path, turns=TURNS, episodes=episodes)
        assert interview.cmd_validate_episodes(args_for(work, "--codebook", str(cb))) == 1
        out = capsys.readouterr().out
        for field in ("id", "t_start", "t_end"):
            assert f"missing required field '{field}'" in out, out

    def test_main_dispatches_validate_episodes_with_codebook(self, tmp_path, monkeypatch):
        # pins both the dispatch-dict entry and the --codebook parser argument
        work = make_work(tmp_path, turns=TURNS, episodes=EPISODES)
        monkeypatch.setattr(sys, "argv", [
            "interview.py", "validate-episodes", "--work", str(work),
            "--codebook", str(MORAL_CODEBOOK)])
        assert interview.main() == 0
        assert read(work, "diarized.json")[2]["episode_id"] == "e02"


class TestHandAuthoredInputFailures:
    """episodes.json and --codebook are written by a person between stages, so
    a typo is the expected failure. Exit 2, never 1: a broken input must stay
    distinguishable from a legitimate validation finding."""

    @staticmethod
    def _exits_2(fn, args):
        with pytest.raises(SystemExit) as exc:
            fn(args)
        assert exc.value.code == 2
        return exc

    def test_missing_episodes_json(self, tmp_path, capsys):
        work = make_work(tmp_path, turns=TURNS)
        self._exits_2(interview.cmd_validate_episodes, args_for(work))
        assert "episodes.json" in capsys.readouterr().err

    def test_missing_diarized_json(self, tmp_path, capsys):
        work = make_work(tmp_path, episodes=EPISODES)
        self._exits_2(interview.cmd_validate_episodes, args_for(work))
        assert "diarized.json" in capsys.readouterr().err

    def test_malformed_episodes_json_names_the_file_and_the_spot(self, tmp_path, capsys):
        work = make_work(tmp_path, turns=TURNS)
        (work / "episodes.json").write_text('[{"id": "e01",}]', encoding="utf-8")
        self._exits_2(interview.cmd_validate_episodes, args_for(work))
        err = capsys.readouterr().err
        # work/ holds four JSON files — the raw decoder error names none of them
        assert "episodes.json" in err and "line 1 column" in err

    def test_malformed_episodes_json_at_validate_flags_too(self, tmp_path, capsys):
        work = make_work(tmp_path, turns=TURNS, flags=NARRATIVE_FLAGS)
        (work / "episodes.json").write_text("[oops]", encoding="utf-8")
        self._exits_2(interview.cmd_validate_flags, flag_args(work))
        assert "episodes.json" in capsys.readouterr().err

    def test_codebook_path_typo(self, tmp_path, capsys):
        work = make_work(tmp_path, turns=TURNS, flags=NARRATIVE_FLAGS)
        self._exits_2(interview.cmd_validate_flags,
                      flag_args(work, "--codebook", str(tmp_path / "nope.json")))
        assert "nope.json" in capsys.readouterr().err

    def test_codebook_path_typo_at_validate_episodes_too(self, tmp_path, capsys):
        # both stages take --codebook, so both need the same guard
        work = make_work(tmp_path, turns=TURNS, episodes=EPISODES)
        self._exits_2(interview.cmd_validate_episodes,
                      args_for(work, "--codebook", str(tmp_path / "nope.json")))
        assert "nope.json" in capsys.readouterr().err

    def test_codebook_pointed_at_a_json_array_at_validate_episodes(self, tmp_path, capsys):
        work = make_work(tmp_path, turns=TURNS, episodes=EPISODES)
        self._exits_2(interview.cmd_validate_episodes,
                      args_for(work, "--codebook", str(work / "episodes.json")))
        assert "expected a JSON dict" in capsys.readouterr().err

    def test_codebook_pointed_at_a_json_array(self, tmp_path, capsys):
        # --codebook work/episodes.json is a realistic slip; a list would blow up
        # on codebook["markers"] several frames later
        work = make_work(tmp_path, turns=TURNS, flags=NARRATIVE_FLAGS,
                         episodes=EPISODES)
        self._exits_2(interview.cmd_validate_flags,
                      flag_args(work, "--codebook", str(work / "episodes.json")))
        assert "expected a JSON dict" in capsys.readouterr().err

    @staticmethod
    def _real_sidecar(path):
        """A genuine sidecar, from the real builder — not a hand-rolled stand-in.

        The previous fixture here was `{"schema_version": "1.0"}`, which was
        representative when written and went vacuous the moment schema 1.1
        started recording a top-level `codebook_version`: a real sidecar now
        satisfies a codebook_version-only discriminator, so this test passed
        while `--codebook <a prior run's sidecar.json>` sailed through. Built
        by build_sidecar so it cannot drift out of representativeness again.
        """
        path.write_text(json.dumps(build_sidecar(
            media="prior_run.mp4", duration=9.0,
            engines={"groq": "whisper-large-v3", "openai": "whisper-1"},
            degradation=[], segments=[], turns=[], adjudications=[], flags=[],
            partial_failures=[], codebook_version="1.0.0",
            codebook_file="codebook.json")), encoding="utf-8")
        return path

    def test_codebook_pointed_at_some_other_object(self, tmp_path, capsys):
        other = self._real_sidecar(tmp_path / "prior_run_sidecar.json")
        # the trap this fixture exists to spring
        assert "codebook_version" in json.loads(other.read_text(encoding="utf-8"))
        work = make_work(tmp_path, turns=TURNS, flags=NARRATIVE_FLAGS)
        self._exits_2(interview.cmd_validate_flags,
                      flag_args(work, "--codebook", str(other)))
        err = capsys.readouterr().err
        assert "not a codebook" in err
        # names the key that is actually missing, not the one that happens to
        # be present — a KeyError on codebook["markers"] is what this prevents
        assert "'markers'" in err

    def test_codebook_missing_its_version(self, tmp_path, capsys):
        # the other half of the discriminator, and the half that predates this
        # commit: codebook["codebook_version"] is dereferenced bare by the
        # stage summaries and stamped onto every flag in the sidecar, so a
        # marker list on its own is not a codebook either
        cb = tmp_path / "markers_only.json"
        cb.write_text(json.dumps({"markers": {"emotional_display": {}}}),
                      encoding="utf-8")
        work = make_work(tmp_path, turns=TURNS, flags=NARRATIVE_FLAGS)
        self._exits_2(interview.cmd_validate_flags,
                      flag_args(work, "--codebook", str(cb)))
        err = capsys.readouterr().err
        assert "not a codebook" in err and "'codebook_version'" in err

    def test_codebook_pointed_at_a_sidecar_at_validate_episodes_too(
            self, tmp_path, capsys):
        other = self._real_sidecar(tmp_path / "prior_run_sidecar.json")
        work = make_work(tmp_path, turns=TURNS, episodes=EPISODES)
        self._exits_2(interview.cmd_validate_episodes,
                      args_for(work, "--codebook", str(other)))
        assert "not a codebook" in capsys.readouterr().err


class TestCmdValidateFlagsWiring:
    def test_moral_codebook_flags_pass_and_get_episode_ids(self, tmp_path, capsys):
        work = make_work(tmp_path, turns=TURNS, episodes=EPISODES, flags=MORAL_FLAGS)
        assert interview.cmd_validate_episodes(args_for(work)) == 0
        capsys.readouterr()
        rc = interview.cmd_validate_flags(flag_args(work, "--codebook", str(MORAL_CODEBOOK)))
        assert rc == 0, capsys.readouterr().out
        # stamped AND persisted — render/corpus read flags.json, not memory
        assert [f["episode_id"] for f in read(work, "flags.json")] == ["e01", "e02"]
        assert "codebook_moral_identity.json" in capsys.readouterr().out

    def test_codebook_flag_actually_selects_the_codebook(self, tmp_path, capsys):
        # the same flags under the shipped codebook are nonsense: its markers do
        # not include attribution_of_blame
        work = make_work(tmp_path, turns=TURNS, episodes=EPISODES, flags=MORAL_FLAGS)
        assert interview.cmd_validate_episodes(args_for(work)) == 0
        capsys.readouterr()
        assert interview.cmd_validate_flags(flag_args(work)) == 1
        assert "unknown marker 'attribution_of_blame'" in capsys.readouterr().out

    def test_default_codebook_unchanged(self, tmp_path, capsys):
        # shipped path: no --codebook, no episodes, flags left exactly as
        # authored. The turn layer is in the fixture because the quote check is
        # no longer skippable (TestQuoteCheckCannotBeSkipped) — every assertion
        # below is the one this test always made.
        work = make_work(tmp_path, turns=TURNS, flags=NARRATIVE_FLAGS)
        assert interview.cmd_validate_flags(flag_args(work)) == 0
        out = capsys.readouterr().out
        assert "OK: 1 flags valid against codebook 1.0.0 (codebook.json)" in out
        assert read(work, "flags.json") == NARRATIVE_FLAGS

    def test_default_codebook_with_turns_still_uses_the_merged_transcript(self, tmp_path):
        # pre-existing property: a quote spanning two same-speaker units passes
        # because validation runs against the merged view the docx anchors to
        turns = [unit("t0001", 0.0, 3.0, "It was a huge success."),
                 unit("t0002", 3.0, 6.0, "We shipped it on time.")]
        flags = [{"id": "g0001", "marker_types": ["repetition"],
                  "quote": "huge success. We shipped it", "t_start": 1.0,
                  "t_end": 4.0, "salience": 2}]
        work = make_work(tmp_path, turns=turns, flags=flags)
        assert interview.cmd_validate_flags(flag_args(work)) == 0

    def test_turns_are_passed_so_gate_codebook_does_not_raise(self, tmp_path, capsys):
        # codebook_moral_identity declares coding_scope AND
        # enforce_attribution_gate, so validate_flags RAISES when `turns` is
        # omitted. No episodes.json here: this isolates the turns= wiring.
        work = make_work(tmp_path, turns=TURNS, flags=MORAL_FLAGS)
        rc = interview.cmd_validate_flags(flag_args(work, "--codebook", str(MORAL_CODEBOOK)))
        assert rc == 0, capsys.readouterr().out
        # no episodes.json → flags stay unstamped
        assert all("episode_id" not in f for f in read(work, "flags.json"))

    def test_gate_still_fires_through_the_cli(self, tmp_path, capsys):
        # the turns handed to validate_flags must be the real labeled ones, not
        # a stub that would satisfy the raise and then gate nothing
        turns = [dict(t) for t in TURNS]
        turns[1]["concordance"] = 0.6667
        work = make_work(tmp_path, turns=turns, flags=MORAL_FLAGS)
        rc = interview.cmd_validate_flags(flag_args(work, "--codebook", str(MORAL_CODEBOOK)))
        assert rc == 1
        assert "attribution_uncertain" in capsys.readouterr().out

    def test_unlabeled_turns_raise_naming_the_real_cause(self, tmp_path):
        # `turns=None` would make validate_flags report "no turns were supplied"
        # — turns WERE supplied, they are unlabeled, and its own message says so
        bare = [{"id": "t0001", "start": 5.0, "end": 9.0,
                 "text": "Don't touch my property."}]
        work = make_work(tmp_path, turns=bare, flags=MORAL_FLAGS)
        with pytest.raises(ValueError, match="missing label/concordance"):
            interview.cmd_validate_flags(flag_args(work, "--codebook", str(MORAL_CODEBOOK)))

    def test_flag_outside_every_episode_errors_and_flags_are_not_saved(self, tmp_path, capsys):
        episodes = [{"id": "e01", "type": "to-camera", "t_start": 0.0, "t_end": 4.0}]
        turns = [unit("t0001", 0.0, 4.0, "Don't touch my property.", episode_id="e01")]
        work = make_work(tmp_path, turns=turns, episodes=episodes, flags=NARRATIVE_FLAGS)
        assert interview.cmd_validate_flags(flag_args(work)) == 1
        assert "outside every episode" in capsys.readouterr().out
        # the on-disk record must not gain a half-assigned episode_id: None
        assert read(work, "flags.json") == NARRATIVE_FLAGS

    def test_main_dispatches_validate_flags_with_codebook(self, tmp_path, monkeypatch):
        work = make_work(tmp_path, turns=TURNS, episodes=EPISODES, flags=MORAL_FLAGS)
        assert interview.cmd_validate_episodes(args_for(work)) == 0
        monkeypatch.setattr(sys, "argv", [
            "interview.py", "validate-flags", "--work", str(work),
            "--duration", "200", "--codebook", str(MORAL_CODEBOOK)])
        assert interview.main() == 0
        assert read(work, "flags.json")[1]["episode_id"] == "e02"


class TestTurnFlagDrift:
    """Flags are stamped from episodes.json at validate-flags time; turns were
    stamped at validate-episodes time. Nothing forces those two reads to be of
    the same file, and under the moral codebook two episodes are two PEOPLE."""

    def test_redrawn_boundary_without_rerunning_validate_episodes_is_caught(
            self, tmp_path, capsys):
        work = make_work(tmp_path, turns=TURNS, episodes=EPISODES, flags=MORAL_FLAGS)
        assert interview.cmd_validate_episodes(args_for(work)) == 0
        capsys.readouterr()
        # the researcher moves the e01|e02 boundary from 100s to 3s and re-runs
        # ONLY validate-flags — the between-stages hand-edit this layer is for
        redrawn = [dict(EPISODES[0], t_end=3.0), dict(EPISODES[1], t_start=3.0)]
        (work / "episodes.json").write_text(json.dumps(redrawn), encoding="utf-8")
        rc = interview.cmd_validate_flags(flag_args(work, "--codebook", str(MORAL_CODEBOOK)))
        assert rc == 1
        out = capsys.readouterr().out
        # m0002 holds t0002 (start 5.0): stamped e01, now contained by e02 —
        # the flag quoting it would have been filed under a DIFFERENT target
        assert "m0002" in out and "out of sync" in out, out
        assert "re-run validate-episodes" in out, out
        # and nothing was written against the divergent layer
        assert all("episode_id" not in f for f in read(work, "flags.json"))

    def test_display_turn_without_episode_id_is_still_caught(self, tmp_path, capsys):
        # two adjacent same-label units, only one annotated: merge_labeled_turns
        # DROPS the id rather than let one member speak for the other. A missing
        # stamp is drift too — the same invariant, not a separate check.
        turns = [unit("t0001", 0.0, 4.0, "It was my driveway.", episode_id="e01"),
                 unit("t0002", 5.0, 9.0, "Don't touch my property.")]
        work = make_work(tmp_path, turns=turns, episodes=EPISODES,
                         flags=NARRATIVE_FLAGS)
        assert interview.cmd_validate_flags(flag_args(work)) == 1
        out = capsys.readouterr().out
        assert "m0001" in out and "stamped None" in out
        assert "re-run validate-episodes" in out
        assert all("episode_id" not in f for f in read(work, "flags.json"))

    def test_episodes_present_but_no_labeled_turn_layer_is_an_error(self, tmp_path, capsys):
        # the clearest "the episode stage never ran" case: flags would be
        # stamped and persisted while the turn layer was never annotated at all.
        # With diarized.json missing outright the quote check now refuses one
        # step earlier and names the missing file — a strictly more specific
        # message for this fixture. The "no labeled turn layer" wording stays
        # pinned by test_unlabeled_turn_layer_is_the_same_error below, where a
        # turn layer exists but carries no labels.
        work = make_work(tmp_path, episodes=EPISODES, flags=NARRATIVE_FLAGS)
        assert interview.cmd_validate_flags(flag_args(work)) == 1
        assert "diarized.json is absent" in capsys.readouterr().out
        assert read(work, "flags.json") == NARRATIVE_FLAGS

    def test_unlabeled_turn_layer_is_the_same_error(self, tmp_path, capsys):
        bare = [{"id": "t0001", "start": 5.0, "end": 9.0,
                 "text": "Don't touch my property."}]
        work = make_work(tmp_path, turns=bare, episodes=EPISODES, flags=NARRATIVE_FLAGS)
        assert interview.cmd_validate_flags(flag_args(work)) == 1
        assert "no labeled turn layer" in capsys.readouterr().out
        assert read(work, "flags.json") == NARRATIVE_FLAGS

    def test_in_sync_layers_pass(self, tmp_path, capsys):
        # the guard must not fire on the healthy path it sits astride
        work = make_work(tmp_path, turns=TURNS, episodes=EPISODES, flags=NARRATIVE_FLAGS)
        assert interview.cmd_validate_episodes(args_for(work)) == 0
        capsys.readouterr()
        assert interview.cmd_validate_flags(flag_args(work)) == 0
        assert read(work, "flags.json")[0]["episode_id"] == "e01"


class TestQuoteCheckCannotBeSkipped:
    """A work dir with no turn layer used to skip the verbatim-quote check
    entirely and still print the OK line SKILL.md designates as quote
    provenance — a fabricated quote validated clean at exit 0. cmd_render
    already refuses on exactly this condition ("run concordance first"); this
    stage now agrees with it. Exit 1, like every other not-ready-yet refusal in
    this file: the invocation was fine, the pipeline was run out of order."""

    FABRICATED = [dict(NARRATIVE_FLAGS[0],
                       quote="I INVENTED THIS QUOTE, IT IS NOWHERE IN THE TRANSCRIPT")]

    def test_fabricated_quote_cannot_earn_the_ok_line(self, tmp_path, capsys):
        work = make_work(tmp_path, flags=self.FABRICATED)
        assert interview.cmd_validate_flags(flag_args(work)) == 1
        out = capsys.readouterr().out
        assert "OK:" not in out
        assert "diarized.json" in out            # the missing file
        assert "quote check cannot run" in out   # the consequence
        assert "concordance" in out              # the way out
        # NOT the findings header: SKILL.md defines `INVALID FLAGS:` as "your
        # judgment file is wrong", which would send the researcher back to
        # re-examine coding that is not the problem here
        assert "CANNOT VALIDATE:" in out
        assert "INVALID FLAGS:" not in out

    def test_a_real_finding_still_prints_the_findings_header(self, tmp_path, capsys):
        # the contrast that gives the header above its meaning: a flag the
        # researcher must actually fix keeps `INVALID FLAGS:`
        bad = [dict(NARRATIVE_FLAGS[0], marker_types=["nope"])]
        work = make_work(tmp_path, turns=TURNS, flags=bad)
        assert interview.cmd_validate_flags(flag_args(work)) == 1
        out = capsys.readouterr().out
        assert "INVALID FLAGS:" in out
        assert "CANNOT VALIDATE:" not in out

    def test_a_true_quote_is_refused_the_same_way(self, tmp_path, capsys):
        # the refusal is "could this have been checked", not "was it wrong":
        # an unverified quote is not evidence even when it happens to be exact
        work = make_work(tmp_path, flags=NARRATIVE_FLAGS)
        assert interview.cmd_validate_flags(flag_args(work)) == 1
        assert "diarized.json" in capsys.readouterr().out
        assert read(work, "flags.json") == NARRATIVE_FLAGS

    def test_the_same_flags_pass_once_the_turn_layer_is_there(self, tmp_path, capsys):
        work = make_work(tmp_path, turns=TURNS, flags=NARRATIVE_FLAGS)
        assert interview.cmd_validate_flags(flag_args(work)) == 0
        assert "OK: 1 flags" in capsys.readouterr().out

    def test_a_flag_set_with_no_quotes_needs_no_turn_layer(self, tmp_path, capsys):
        # the refusal is about quotes, not about the file's existence — an
        # empty flag list has nothing that could be checked
        work = make_work(tmp_path, flags=[])
        assert interview.cmd_validate_flags(flag_args(work)) == 0
        assert "OK: 0 flags" in capsys.readouterr().out

    def test_a_quoteless_flag_is_told_it_omitted_its_quote(self, tmp_path, capsys):
        # A NON-EMPTY flag set carrying no quotes. Nothing here could have been
        # checked against a transcript, so the refusal above must not fire and
        # steal the finding — this flag's real problem is the missing `quote`,
        # and being told the transcript is absent instead would send the
        # researcher to the wrong stage. (An empty list is empty whatever the
        # predicate, so it cannot pin this on its own.)
        bare = {k: v for k, v in NARRATIVE_FLAGS[0].items() if k != "quote"}
        work = make_work(tmp_path, flags=[bare])
        assert interview.cmd_validate_flags(flag_args(work)) == 1
        out = capsys.readouterr().out
        assert "missing required field 'quote'" in out
        assert "diarized.json" not in out

    def test_an_empty_turn_layer_is_the_substring_finding_not_this_one(
            self, tmp_path, capsys):
        # diarized.json present but empty: the check CAN run, and it fails.
        # Pins `transcript_text is None` against a `not transcript_text` slip,
        # which would trade a precise finding for a misleading one.
        work = make_work(tmp_path, turns=[], flags=NARRATIVE_FLAGS)
        assert interview.cmd_validate_flags(flag_args(work)) == 1
        out = capsys.readouterr().out
        assert "not a verbatim substring" in out
        assert "diarized.json" not in out

    def test_moral_codebook_without_a_turn_layer_is_a_finding_not_a_traceback(
            self, tmp_path, capsys):
        work = make_work(tmp_path, flags=MORAL_FLAGS)
        assert interview.cmd_validate_flags(
            flag_args(work, "--codebook", str(MORAL_CODEBOOK))) == 1
        assert "diarized.json" in capsys.readouterr().out

    def test_moral_codebook_with_no_flags_at_all_is_a_finding_too(
            self, tmp_path, capsys):
        # No quotes, so the quote refusal above does not fire — but the
        # codebook's own coding_scope/gate declaration still demands turns and
        # validate_flags raises for it. That raise is a precondition failure,
        # not a crash, and must reach the user as a finding rather than as a
        # bare traceback out of this stage.
        work = make_work(tmp_path, flags=[])
        assert interview.cmd_validate_flags(
            flag_args(work, "--codebook", str(MORAL_CODEBOOK))) == 1
        out = capsys.readouterr().out
        assert "turn-level validation cannot be skipped" in out
        assert "diarized.json" in out
        # a precondition, not a finding — same header as the quote refusal
        assert "CANNOT VALIDATE:" in out
        assert "INVALID FLAGS:" not in out

    # An unlabeled turn layer keeps raising ValueError with its own accurate
    # message — pinned by TestCmdValidateFlagsWiring
    # .test_unlabeled_turns_raise_naming_the_real_cause, which is what stops the
    # conversion above from swallowing every raise indiscriminately.


class TestCodebookProvenance:
    """Nothing in the work dir recorded which codebook validate-flags accepted
    the flags against, so omitting --codebook at render wrote
    `codebook_file: "codebook.json"` into a sidecar full of moral-identity
    markers — the research record claiming the wrong construct, at exit 0."""

    def test_validate_flags_records_the_codebook_it_used(self, tmp_path, capsys):
        work = make_work(tmp_path, turns=TURNS, flags=MORAL_FLAGS)
        assert interview.cmd_validate_flags(
            flag_args(work, "--codebook", str(MORAL_CODEBOOK))) == 0, \
            capsys.readouterr().out
        assert read(work, "codebook_ref.json") == {
            "codebook_file": "codebook_moral_identity.json",
            "codebook_version": "1.0.0"}

    def test_the_shipped_codebook_is_recorded_too(self, tmp_path):
        work = make_work(tmp_path, turns=TURNS, flags=NARRATIVE_FLAGS)
        assert interview.cmd_validate_flags(flag_args(work)) == 0
        assert read(work, "codebook_ref.json") == {
            "codebook_file": "codebook.json", "codebook_version": "1.0.0"}

    def test_a_failing_run_records_nothing(self, tmp_path, capsys):
        # provenance for an ACCEPTED flag set. Recording a rejected run would
        # have render cross-check against a codebook that validated nothing.
        work = make_work(tmp_path, turns=TURNS, flags=MORAL_FLAGS)
        assert interview.cmd_validate_flags(flag_args(work)) == 1  # shipped codebook
        assert "unknown marker" in capsys.readouterr().out
        assert not (work / "codebook_ref.json").exists()


class TestShippedCodebookEndToEnd:
    """The narrative pipeline predates episodes and must be byte-unaffected."""

    def test_no_codebook_flag_reads_the_shipped_file(self, tmp_path, capsys):
        work = make_work(tmp_path, turns=TURNS, flags=NARRATIVE_FLAGS)
        assert interview.cmd_validate_flags(flag_args(work)) == 0
        out = capsys.readouterr().out
        shipped = json.loads(SHIPPED_CODEBOOK.read_text(encoding="utf-8"))
        assert f"codebook {shipped['codebook_version']} (codebook.json)" in out

    def test_shipped_codebook_declares_no_turn_level_checks(self):
        shipped = json.loads(SHIPPED_CODEBOOK.read_text(encoding="utf-8"))
        # why the narrative path needs no turns=: nothing in it demands them
        assert "coding_scope" not in shipped
        assert not shipped.get("enforce_attribution_gate")
        assert "speaker_role" not in shipped["flag_schema"]["required"]

    @pytest.mark.parametrize("bad", [
        {"id": "g0001", "marker_types": ["nope"], "quote": "Don't touch my property.",
         "t_start": 5.0, "t_end": 9.0, "salience": 4},
        {"id": "g0001", "marker_types": ["emotional_display"], "emotion": "smug",
         "quote": "Don't touch my property.", "t_start": 5.0, "t_end": 9.0,
         "salience": 4},
    ])
    def test_shipped_codebook_still_rejects_what_it_always_rejected(
            self, tmp_path, capsys, bad):
        work = make_work(tmp_path, turns=TURNS, flags=[bad])
        assert interview.cmd_validate_flags(flag_args(work)) == 1
        assert "INVALID FLAGS" in capsys.readouterr().out


ARC_EPISODES = [
    dict(EPISODES[0], arc={"phases": ["threat", "defense"],
                           "outcome": "refuses", "turning_point": "t0002"}),
    dict(EPISODES[1], arc={"phases": ["exit"], "outcome": "n/a",
                           "turning_point": None}),
]


def make_render_dirs(tmp_path, *, turns=TURNS, flags=NARRATIVE_FLAGS, episodes=None):
    """A complete render input set. The media file exists but is empty — these
    tests stub framegrab.get_metadata rather than leaning on a missing file, so
    the probe branch under test is stated instead of implied."""
    media = tmp_path / "bei_017.mp4"
    media.write_bytes(b"")
    base = tmp_path / "out"
    work = base / "work"
    work.mkdir(parents=True, exist_ok=True)
    files = {
        "diarized.json": turns,
        "flags.json": flags,
        "final_transcript.json": [
            {"start": t["start"], "end": t["end"], "text": t["text"]} for t in turns],
        "audit_log.json": [],
        "diff.json": {"degradation": [], "partial_failures": [],
                      "engines": {"groq": "whisper-large-v3", "openai": "whisper-1"}},
    }
    if episodes is not None:
        files["episodes.json"] = episodes
    for name, data in files.items():
        (work / name).write_text(json.dumps(data), encoding="utf-8")
    return media, base


def render_args(media, base, *extra):
    """Through the real parser, like args_for — render takes a positional media
    and --out-dir rather than --work."""
    return interview.build_parser().parse_args(
        ["render", str(media), "--out-dir", str(base), *extra])


def sidecar_of(base):
    return json.loads((base / "sidecar.json").read_text(encoding="utf-8"))


class TestCmdRenderSidecar:
    """Schema 1.1: the sidecar records the episode layer, the persona, and which
    codebook produced it."""

    @pytest.fixture(autouse=True)
    def _unprobeable_media(self, monkeypatch):
        """cmd_render falls back to the last segment's end when the media
        cannot be probed. Stubbed rather than implied by a missing file: the
        missing-file trick passed for two different reasons (no file / no
        ffprobe installed) with neither of them asserted."""
        def unprobeable(path):
            raise SystemExit("ffprobe failed")
        monkeypatch.setattr(interview.framegrab, "get_metadata", unprobeable)

    @staticmethod
    def _stamp_episodes(base):
        """Run the real validate-episodes stage over the work dir. Hand-stamping
        episode_id would let the stage rename the key and leave render's guard
        passing against a fixture nobody produces."""
        assert interview.cmd_validate_episodes(args_for(base / "work")) == 0

    def test_persona_lands_in_the_interview_block(self, tmp_path):
        media, base = make_render_dirs(tmp_path)
        assert interview.cmd_render(
            render_args(media, base, "--persona", "Agent Greg Gorey")) == 0
        sc = sidecar_of(base)
        assert sc["interview"]["persona"] == "Agent Greg Gorey"
        # persona is per-video metadata, never a role: the turn labels stand
        assert {t["label"] for t in sc["turns"]} == {"INTERVIEWER", "INTERVIEWEE"}

    def test_empty_persona_is_refused(self, tmp_path, capsys):
        # `--persona "$PERSONA"` with the variable unset. Recording "" would
        # assert an empty-string character; dropping it would swallow the slip.
        media, base = make_render_dirs(tmp_path)
        assert interview.cmd_render(render_args(media, base, "--persona", "  ")) == 2
        assert "--persona was given an empty value" in capsys.readouterr().err
        assert not (base / "sidecar.json").exists()

    def test_codebook_flag_records_the_file_name(self, tmp_path):
        media, base = make_render_dirs(tmp_path, flags=MORAL_FLAGS)
        assert interview.cmd_render(
            render_args(media, base, "--codebook", str(MORAL_CODEBOOK))) == 0
        # both codebooks are version 1.0.0 — the FILE is what disambiguates them
        assert sidecar_of(base)["codebook_file"] == "codebook_moral_identity.json"

    def test_codebook_flag_selects_the_recorded_version(self, tmp_path):
        cb = tmp_path / "other.json"
        cb.write_text(json.dumps({"codebook_version": "9.9.9", "markers": {}}),
                      encoding="utf-8")
        media, base = make_render_dirs(tmp_path)
        assert interview.cmd_render(render_args(media, base, "--codebook", str(cb))) == 0
        sc = sidecar_of(base)
        assert sc["codebook_version"] == "9.9.9"      # top level
        assert sc["codebook_file"] == "other.json"
        assert sc["flags"][0]["codebook_version"] == "9.9.9"   # and per flag

    def test_codebook_path_typo_exits_2(self, tmp_path, capsys):
        # render loads the codebook through the checked loader, like the
        # validate stages: a mistyped path is an input error, not a traceback
        media, base = make_render_dirs(tmp_path)
        with pytest.raises(SystemExit) as exc:
            interview.cmd_render(render_args(media, base, "--codebook",
                                             str(tmp_path / "nope.json")))
        assert exc.value.code == 2
        assert "nope.json" in capsys.readouterr().err

    def test_codebook_pointed_at_a_prior_sidecar_exits_2(self, tmp_path, capsys):
        # the slip this whole hardening exists for: a 1.1 sidecar carries its
        # own top-level codebook_version, so it used to load clean here and
        # write a corrupted record at exit 0
        prior = TestHandAuthoredInputFailures._real_sidecar(tmp_path / "prior.json")
        media, base = make_render_dirs(tmp_path)
        with pytest.raises(SystemExit) as exc:
            interview.cmd_render(render_args(media, base, "--codebook", str(prior)))
        assert exc.value.code == 2
        assert "not a codebook" in capsys.readouterr().err
        assert not (base / "sidecar.json").exists()

    def test_episodes_json_reaches_the_sidecar_with_arcs(self, tmp_path):
        media, base = make_render_dirs(tmp_path, episodes=ARC_EPISODES)
        self._stamp_episodes(base)
        assert interview.cmd_render(render_args(media, base)) == 0
        sc = sidecar_of(base)
        assert [e["id"] for e in sc["episodes"]] == ["e01", "e02"]
        assert sc["episodes"][0]["arc"]["outcome"] == "refuses"
        assert sc["episodes"][0]["arc"]["phases"] == ["threat", "defense"]
        assert sc["episodes"][0]["target_descriptor"] == "woman in the garage"

    def test_unstamped_turns_with_an_episode_layer_are_refused(self, tmp_path, capsys):
        # render never ran validate-episodes' output through: recording an
        # episode layer the turns were never reconciled against writes a record
        # whose two halves disagree
        media, base = make_render_dirs(tmp_path, episodes=ARC_EPISODES)
        assert interview.cmd_render(render_args(media, base)) == 1
        assert "run validate-episodes first" in capsys.readouterr().err
        assert not (base / "sidecar.json").exists()

    def test_partially_stamped_turns_are_refused_too(self, tmp_path, capsys):
        # one hand-edited turn is the realistic drift, not a wholly unstamped
        # layer — the guard must not settle for "some turn somewhere is stamped"
        media, base = make_render_dirs(tmp_path, episodes=ARC_EPISODES)
        self._stamp_episodes(base)
        turns = read(base / "work", "diarized.json")
        del turns[1]["episode_id"]
        (base / "work" / "diarized.json").write_text(json.dumps(turns), encoding="utf-8")
        assert interview.cmd_render(render_args(media, base)) == 1
        assert "run validate-episodes first" in capsys.readouterr().err

    def test_malformed_episodes_json_at_render_exits_2(self, tmp_path, capsys):
        media, base = make_render_dirs(tmp_path)
        (base / "work" / "episodes.json").write_text("[oops]", encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            interview.cmd_render(render_args(media, base))
        assert exc.value.code == 2
        assert "episodes.json" in capsys.readouterr().err

    def test_default_path_key_set(self, tmp_path):
        # no --codebook, no --persona, no episodes.json: the shipped narrative
        # sidecar gains codebook_version + codebook_file and nothing else
        media, base = make_render_dirs(tmp_path)
        assert interview.cmd_render(render_args(media, base)) == 0
        sc = sidecar_of(base)
        assert sc["schema_version"] == "1.1"
        assert sc["codebook_version"] == "1.0.0"
        assert sc["codebook_file"] == "codebook.json"
        assert "episodes" not in sc
        assert "persona" not in sc["interview"]
        assert "speaker_names" not in sc
        # the probe failed, so duration came from the last segment's end
        assert sc["interview"]["duration_seconds"] == TURNS[-1]["end"]

    def test_probed_duration_reaches_the_sidecar(self, tmp_path, monkeypatch):
        # the other side of the try/except: a readable media file wins over the
        # last segment's end, and 1830.5 is nothing any fixture could supply
        media, base = make_render_dirs(tmp_path)
        monkeypatch.setattr(interview.framegrab, "get_metadata",
                            lambda path: {"duration_seconds": 1830.5})
        assert interview.cmd_render(render_args(media, base)) == 0
        assert sidecar_of(base)["interview"]["duration_seconds"] == 1830.5

    def test_main_dispatches_render_with_persona_and_codebook(
            self, tmp_path, monkeypatch):
        # pins the render subparser's two new arguments through the real CLI
        media, base = make_render_dirs(tmp_path, flags=MORAL_FLAGS,
                                       episodes=ARC_EPISODES)
        self._stamp_episodes(base)
        monkeypatch.setattr(sys, "argv", [
            "interview.py", "render", str(media), "--out-dir", str(base),
            "--codebook", str(MORAL_CODEBOOK), "--persona", "RoboNarc"])
        assert interview.main() == 0
        sc = sidecar_of(base)
        assert sc["interview"]["persona"] == "RoboNarc"
        assert sc["codebook_file"] == "codebook_moral_identity.json"
        assert sc["episodes"][1]["arc"]["phases"] == ["exit"]

    def test_speaker_names_still_recorded_alongside_persona(self, tmp_path):
        # the display-name layer must survive the new keyword arguments
        media, base = make_render_dirs(tmp_path)
        assert interview.cmd_render(render_args(
            media, base, "--interviewee", "Participant", "--persona", "Agent Sebastian")) == 0
        sc = sidecar_of(base)
        assert sc["speaker_names"] == {"INTERVIEWEE": "Participant"}
        assert sc["interview"]["persona"] == "Agent Sebastian"


# A codebook that accepts NARRATIVE_FLAGS, written to tmp_path so a test can
# edit it BETWEEN validate-flags and render — the drift the cross-check exists
# to catch, staged without touching a shipped file.
MINIMAL_CODEBOOK = {
    "codebook_version": "1.0.0",
    "markers": [{"id": "emotional_display", "requires_emotion": True}],
    "emotions": ["anger"],
    "flag_schema": {"required": ["id", "marker_types", "quote", "t_start",
                                 "t_end", "salience"]},
}


def record_codebook(base, *extra):
    """Produce work/codebook_ref.json the way the pipeline does — by running
    the real validate-flags stage. Hand-writing the file would let that stage
    rename a key and leave render's cross-check passing against a fixture
    nobody produces."""
    assert interview.cmd_validate_flags(flag_args(base / "work", *extra)) == 0


class TestRenderCodebookCrossCheck:
    """render resolves --codebook independently of validate-flags, so omitting
    it on a moral-identity run wrote the wrong construct into the sidecar at
    exit 0. It now refuses when the two disagree."""

    @pytest.fixture(autouse=True)
    def _unprobeable_media(self, monkeypatch):
        def unprobeable(path):
            raise SystemExit("ffprobe failed")
        monkeypatch.setattr(interview.framegrab, "get_metadata", unprobeable)

    def test_render_refuses_a_codebook_validate_flags_did_not_use(
            self, tmp_path, capsys):
        media, base = make_render_dirs(tmp_path, flags=MORAL_FLAGS)
        record_codebook(base, "--codebook", str(MORAL_CODEBOOK))
        capsys.readouterr()
        assert interview.cmd_render(render_args(media, base)) == 1
        err = capsys.readouterr().err
        assert "codebook_moral_identity.json" in err   # what validated the flags
        assert "codebook.json" in err                  # what render resolved
        assert "--codebook" in err                     # what to do about it
        # and where the record lives: this is new, otherwise-invisible pipeline
        # state, so a researcher who thinks the record is wrong can find it
        assert str(base / "work" / "codebook_ref.json") in err
        # nothing written: a refused render must leave no artifact behind
        assert not (base / "sidecar.json").exists()
        assert not (base / "transcript.docx").exists()

    def test_render_accepts_the_recorded_codebook(self, tmp_path, capsys):
        media, base = make_render_dirs(tmp_path, flags=MORAL_FLAGS)
        record_codebook(base, "--codebook", str(MORAL_CODEBOOK))
        capsys.readouterr()
        assert interview.cmd_render(
            render_args(media, base, "--codebook", str(MORAL_CODEBOOK))) == 0
        assert sidecar_of(base)["codebook_file"] == "codebook_moral_identity.json"

    def test_the_shipped_path_round_trips_with_no_flag_on_either_stage(
            self, tmp_path, capsys):
        media, base = make_render_dirs(tmp_path)
        record_codebook(base)
        capsys.readouterr()
        assert interview.cmd_render(render_args(media, base)) == 0
        assert sidecar_of(base)["codebook_file"] == "codebook.json"

    def test_an_older_work_dir_with_no_record_stays_permissive(self, tmp_path):
        # work dirs produced before this record existed must keep rendering
        media, base = make_render_dirs(tmp_path, flags=MORAL_FLAGS)
        assert not (base / "work" / "codebook_ref.json").exists()
        assert interview.cmd_render(
            render_args(media, base, "--codebook", str(MORAL_CODEBOOK))) == 0

    def test_a_codebook_edited_between_the_two_stages_is_caught(
            self, tmp_path, capsys):
        # same file NAME, different version: the marker set the flags were
        # validated against is not the one about to be recorded
        cb = tmp_path / "study.json"
        cb.write_text(json.dumps(MINIMAL_CODEBOOK), encoding="utf-8")
        media, base = make_render_dirs(tmp_path)
        record_codebook(base, "--codebook", str(cb))
        cb.write_text(json.dumps(dict(MINIMAL_CODEBOOK, codebook_version="9.9.9")),
                      encoding="utf-8")
        capsys.readouterr()
        assert interview.cmd_render(
            render_args(media, base, "--codebook", str(cb))) == 1
        err = capsys.readouterr().err
        assert "1.0.0" in err and "9.9.9" in err
        assert not (base / "sidecar.json").exists()

    def test_a_malformed_record_exits_2_naming_the_file(self, tmp_path, capsys):
        media, base = make_render_dirs(tmp_path)
        (base / "work" / "codebook_ref.json").write_text("{oops", encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            interview.cmd_render(render_args(media, base))
        assert exc.value.code == 2
        assert "codebook_ref.json" in capsys.readouterr().err

    @pytest.mark.parametrize("record", [
        {},                                                   # neither key
        {"codebook_version": "1.0.0"},                        # no file name
        {"codebook_file": "codebook.json"},                   # no version
        {"codebook_file": "", "codebook_version": "1.0.0"},   # empty file name
        {"codebook_file": "codebook.json", "codebook_version": ""},
        {"codebook_file": None, "codebook_version": "1.0.0"},
        {"codebook_file": 1, "codebook_version": "1.0.0"},    # not a string
    ], ids=["empty", "no-file", "no-version", "blank-file", "blank-version",
            "null-file", "non-string-file"])
    def test_an_incomplete_record_exits_2_rather_than_refusing_unfollowably(
            self, tmp_path, capsys, record):
        # Parseable JSON is not a usable record. Without both values the
        # comparison still refuses a legitimate render — while instructing the
        # user to point --codebook at `None`, which nobody can follow, and never
        # saying the record is what is broken.
        media, base = make_render_dirs(tmp_path)
        (base / "work" / "codebook_ref.json").write_text(
            json.dumps(record), encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            interview.cmd_render(render_args(media, base))
        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert "not a codebook record" in err
        assert "codebook_ref.json" in err        # names the file, and its path
        assert "codebook mismatch" not in err    # never the misleading message
        assert "None" not in err                 # never the unfollowable one
        assert not (base / "sidecar.json").exists()

    def test_main_dispatches_the_cross_check(self, tmp_path, monkeypatch, capsys):
        media, base = make_render_dirs(tmp_path, flags=MORAL_FLAGS)
        record_codebook(base, "--codebook", str(MORAL_CODEBOOK))
        capsys.readouterr()
        monkeypatch.setattr(sys, "argv", [
            "interview.py", "render", str(media), "--out-dir", str(base)])
        assert interview.main() == 1
        assert "codebook_moral_identity.json" in capsys.readouterr().err
