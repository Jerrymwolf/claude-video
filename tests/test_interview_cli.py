"""CLI stage wiring: validate-episodes, validate-flags' --codebook /
turn-passing / flag-episode stamping / turn-flag drift detection, and render's
--codebook / --persona / episodes.json → sidecar recording."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import interview

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
        cb.write_text(json.dumps({"codebook_version": "9.9.9",
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
        cb.write_text(json.dumps({"codebook_version": "9.9.9",
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

    def test_codebook_pointed_at_some_other_object(self, tmp_path, capsys):
        other = tmp_path / "sidecar.json"
        other.write_text(json.dumps({"schema_version": "1.0"}), encoding="utf-8")
        work = make_work(tmp_path, turns=TURNS, flags=NARRATIVE_FLAGS)
        self._exits_2(interview.cmd_validate_flags,
                      flag_args(work, "--codebook", str(other)))
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
        # shipped path, no diarized.json at all: no turns needed, no episodes,
        # flags left exactly as authored
        work = make_work(tmp_path, flags=NARRATIVE_FLAGS)
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
        # stamped and persisted while the turn layer was never annotated at all
        work = make_work(tmp_path, episodes=EPISODES, flags=NARRATIVE_FLAGS)
        assert interview.cmd_validate_flags(flag_args(work)) == 1
        assert "no labeled turn layer" in capsys.readouterr().out
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
    dict(EPISODES[0], arc={"phases": ["approach", "threat", "defense"],
                           "outcome": "refuses", "turning_point": "t0002"}),
    dict(EPISODES[1], arc={"phases": ["monologue"], "outcome": "none",
                           "turning_point": None}),
]


def make_render_dirs(tmp_path, *, turns=TURNS, flags=NARRATIVE_FLAGS, episodes=None):
    """A complete render input set. The media file is deliberately NOT created:
    ffprobe fails on it, cmd_render catches that and derives duration from the
    last segment — so these stay pure-stdlib, ffmpeg-free CLI tests."""
    media = tmp_path / "bei_017.mp4"
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

    def test_persona_lands_in_the_interview_block(self, tmp_path):
        media, base = make_render_dirs(tmp_path)
        assert interview.cmd_render(
            render_args(media, base, "--persona", "Agent Greg Gorey")) == 0
        sc = sidecar_of(base)
        assert sc["interview"]["persona"] == "Agent Greg Gorey"
        # persona is per-video metadata, never a role: the turn labels stand
        assert {t["label"] for t in sc["turns"]} == {"INTERVIEWER", "INTERVIEWEE"}

    def test_codebook_flag_records_the_file_name(self, tmp_path):
        media, base = make_render_dirs(tmp_path, flags=MORAL_FLAGS)
        assert interview.cmd_render(
            render_args(media, base, "--codebook", str(MORAL_CODEBOOK))) == 0
        # both codebooks are version 1.0.0 — the FILE is what disambiguates them
        assert sidecar_of(base)["codebook_file"] == "codebook_moral_identity.json"

    def test_codebook_flag_selects_the_recorded_version(self, tmp_path):
        cb = tmp_path / "other.json"
        cb.write_text(json.dumps({"codebook_version": "9.9.9"}), encoding="utf-8")
        media, base = make_render_dirs(tmp_path)
        assert interview.cmd_render(render_args(media, base, "--codebook", str(cb))) == 0
        sc = sidecar_of(base)
        assert sc["codebook_version"] == "9.9.9"      # top level
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

    def test_episodes_json_reaches_the_sidecar_with_arcs(self, tmp_path):
        media, base = make_render_dirs(tmp_path, episodes=ARC_EPISODES)
        assert interview.cmd_render(render_args(media, base)) == 0
        sc = sidecar_of(base)
        assert [e["id"] for e in sc["episodes"]] == ["e01", "e02"]
        assert sc["episodes"][0]["arc"]["outcome"] == "refuses"
        assert sc["episodes"][0]["arc"]["phases"] == ["approach", "threat", "defense"]
        assert sc["episodes"][0]["target_descriptor"] == "woman in the garage"

    def test_empty_episodes_json_is_recorded_not_dropped(self, tmp_path):
        # "the episode pass ran and drew nothing" is a different research claim
        # from "no episode pass ran" — absence of the key means the latter
        media, base = make_render_dirs(tmp_path, episodes=[])
        assert interview.cmd_render(render_args(media, base)) == 0
        assert sidecar_of(base)["episodes"] == []

    def test_malformed_episodes_json_at_render_exits_2(self, tmp_path, capsys):
        media, base = make_render_dirs(tmp_path)
        (base / "work" / "episodes.json").write_text("[oops]", encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            interview.cmd_render(render_args(media, base))
        assert exc.value.code == 2
        assert "episodes.json" in capsys.readouterr().err

    def test_default_path_carries_only_the_version_bump(self, tmp_path):
        # no --codebook, no --persona, no episodes.json: the shipped narrative
        # sidecar gains codebook_version and nothing else
        media, base = make_render_dirs(tmp_path)
        assert interview.cmd_render(render_args(media, base)) == 0
        sc = sidecar_of(base)
        assert sc["schema_version"] == "1.1"
        assert sc["codebook_version"] == "1.0.0"
        assert "episodes" not in sc
        assert "codebook_file" not in sc
        assert "persona" not in sc["interview"]
        assert "speaker_names" not in sc

    def test_main_dispatches_render_with_persona_and_codebook(
            self, tmp_path, monkeypatch):
        # pins the render subparser's two new arguments through the real CLI
        media, base = make_render_dirs(tmp_path, flags=MORAL_FLAGS,
                                       episodes=ARC_EPISODES)
        monkeypatch.setattr(sys, "argv", [
            "interview.py", "render", str(media), "--out-dir", str(base),
            "--codebook", str(MORAL_CODEBOOK), "--persona", "RoboNarc"])
        assert interview.main() == 0
        sc = sidecar_of(base)
        assert sc["interview"]["persona"] == "RoboNarc"
        assert sc["codebook_file"] == "codebook_moral_identity.json"
        assert sc["episodes"][1]["arc"]["phases"] == ["monologue"]

    def test_speaker_names_still_recorded_alongside_persona(self, tmp_path):
        # the display-name layer must survive the new keyword arguments
        media, base = make_render_dirs(tmp_path)
        assert interview.cmd_render(render_args(
            media, base, "--interviewee", "Participant", "--persona", "Agent Sebastian")) == 0
        sc = sidecar_of(base)
        assert sc["speaker_names"] == {"INTERVIEWEE": "Participant"}
        assert sc["interview"]["persona"] == "Agent Sebastian"
