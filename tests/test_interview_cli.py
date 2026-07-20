"""CLI stage wiring: validate-episodes, and validate-flags' --codebook /
turn-passing / flag-episode stamping."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

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


def args_for(work, **over):
    base = {"work": str(work), "duration": None, "codebook": None}
    base.update(over)
    return SimpleNamespace(**base)


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
        cb.write_text(json.dumps({"episode_schema": {"types": ["confrontation"]}}),
                      encoding="utf-8")
        work = make_work(tmp_path, turns=TURNS, episodes=EPISODES)
        # the default (shipped codebook.json, no episode_schema) accepts to-camera
        assert interview.cmd_validate_episodes(args_for(work)) == 0
        capsys.readouterr()
        assert interview.cmd_validate_episodes(args_for(work, codebook=str(cb))) == 1
        assert "unknown type 'to-camera'" in capsys.readouterr().out

    def test_moral_codebook_episode_schema_accepts_the_pilot_shape(self, tmp_path):
        work = make_work(tmp_path, turns=TURNS, episodes=EPISODES)
        assert interview.cmd_validate_episodes(
            args_for(work, codebook=str(MORAL_CODEBOOK))) == 0

    def test_main_dispatches_validate_episodes_with_codebook(self, tmp_path, monkeypatch):
        # pins both the dispatch-dict entry and the --codebook parser argument
        work = make_work(tmp_path, turns=TURNS, episodes=EPISODES)
        monkeypatch.setattr(sys, "argv", [
            "interview.py", "validate-episodes", "--work", str(work),
            "--codebook", str(MORAL_CODEBOOK)])
        assert interview.main() == 0
        assert read(work, "diarized.json")[2]["episode_id"] == "e02"


class TestCmdValidateFlagsWiring:
    def test_moral_codebook_flags_pass_and_get_episode_ids(self, tmp_path, capsys):
        work = make_work(tmp_path, turns=TURNS, episodes=EPISODES, flags=MORAL_FLAGS)
        assert interview.cmd_validate_episodes(args_for(work)) == 0
        capsys.readouterr()
        rc = interview.cmd_validate_flags(
            args_for(work, duration="200", codebook=str(MORAL_CODEBOOK)))
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
        assert interview.cmd_validate_flags(args_for(work, duration="200")) == 1
        assert "unknown marker 'attribution_of_blame'" in capsys.readouterr().out

    def test_default_codebook_unchanged(self, tmp_path, capsys):
        # shipped path, no diarized.json at all: no turns needed, no episodes,
        # flags left exactly as authored
        work = make_work(tmp_path, flags=NARRATIVE_FLAGS)
        assert interview.cmd_validate_flags(args_for(work, duration="200")) == 0
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
        assert interview.cmd_validate_flags(args_for(work, duration="10")) == 0

    def test_turns_are_passed_so_gate_codebook_does_not_raise(self, tmp_path, capsys):
        # codebook_moral_identity declares coding_scope AND
        # enforce_attribution_gate, so validate_flags RAISES when `turns` is
        # omitted. No episodes.json here: this isolates the turns= wiring.
        work = make_work(tmp_path, turns=TURNS, flags=MORAL_FLAGS)
        rc = interview.cmd_validate_flags(
            args_for(work, duration="200", codebook=str(MORAL_CODEBOOK)))
        assert rc == 0, capsys.readouterr().out
        # no episodes.json → flags stay unstamped
        assert all("episode_id" not in f for f in read(work, "flags.json"))

    def test_gate_still_fires_through_the_cli(self, tmp_path, capsys):
        # the turns handed to validate_flags must be the real labeled ones, not
        # a stub that would satisfy the raise and then gate nothing
        turns = [dict(t) for t in TURNS]
        turns[1]["concordance"] = 0.6667
        work = make_work(tmp_path, turns=turns, flags=MORAL_FLAGS)
        rc = interview.cmd_validate_flags(
            args_for(work, duration="200", codebook=str(MORAL_CODEBOOK)))
        assert rc == 1
        assert "attribution_uncertain" in capsys.readouterr().out

    def test_display_turn_without_episode_id_is_an_error(self, tmp_path, capsys):
        # two adjacent same-label units, only one annotated: merge_labeled_turns
        # DROPS the id rather than let one member speak for the other, so the
        # display turn arrives unannotated. That means the episode stage did not
        # run — coding flags against it must fail, not silently skip.
        turns = [unit("t0001", 0.0, 4.0, "It was my driveway.", episode_id="e01"),
                 unit("t0002", 5.0, 9.0, "Don't touch my property.")]
        work = make_work(tmp_path, turns=turns, episodes=EPISODES,
                         flags=NARRATIVE_FLAGS)
        assert interview.cmd_validate_flags(args_for(work, duration="200")) == 1
        out = capsys.readouterr().out
        assert "m0001" in out and "episode_id" in out
        assert "validate-episodes" in out
        assert all("episode_id" not in f for f in read(work, "flags.json"))

    def test_flag_outside_every_episode_errors_and_flags_are_not_saved(self, tmp_path, capsys):
        episodes = [{"id": "e01", "type": "to-camera", "t_start": 0.0, "t_end": 4.0}]
        turns = [unit("t0001", 0.0, 4.0, "Don't touch my property.", episode_id="e01")]
        work = make_work(tmp_path, turns=turns, episodes=episodes, flags=NARRATIVE_FLAGS)
        assert interview.cmd_validate_flags(args_for(work, duration="200")) == 1
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


class TestShippedCodebookEndToEnd:
    """The narrative pipeline predates episodes and must be byte-unaffected."""

    def test_no_codebook_flag_reads_the_shipped_file(self, tmp_path, capsys):
        work = make_work(tmp_path, turns=TURNS, flags=NARRATIVE_FLAGS)
        assert interview.cmd_validate_flags(args_for(work, duration="200")) == 0
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
        assert interview.cmd_validate_flags(args_for(work, duration="200")) == 1
        assert "INVALID FLAGS" in capsys.readouterr().out
