"""Guided key setup: scaffold the .env without ever clobbering real keys."""
from __future__ import annotations

import stat

from interview import ENV_TEMPLATE, GROQ_KEYS_URL, OPENAI_KEYS_URL, scaffold_env_file


class TestScaffoldEnvFile:
    def test_creates_file_with_template_when_absent(self, tmp_path):
        target = tmp_path / "cfg" / ".env"
        created = scaffold_env_file(target, ENV_TEMPLATE)
        assert created is True
        assert target.exists()
        body = target.read_text()
        assert "GROQ_API_KEY=" in body
        assert "OPENAI_API_KEY=" in body
        # the signup URLs must be in the scaffolded file so a user finds them
        assert GROQ_KEYS_URL in body
        assert OPENAI_KEYS_URL in body

    def test_scaffolded_file_is_owner_only(self, tmp_path):
        target = tmp_path / ".env"
        scaffold_env_file(target, ENV_TEMPLATE)
        mode = stat.S_IMODE(target.stat().st_mode)
        assert mode == 0o600

    def test_never_clobbers_an_existing_file(self, tmp_path):
        target = tmp_path / ".env"
        target.write_text("GROQ_API_KEY=sk-real-key-do-not-touch\n")
        created = scaffold_env_file(target, ENV_TEMPLATE)
        assert created is False
        # the real key survives untouched
        assert target.read_text() == "GROQ_API_KEY=sk-real-key-do-not-touch\n"

    def test_template_names_both_engines_and_the_honest_claim(self):
        assert "whisper-large-v3" in ENV_TEMPLATE
        assert "whisper-1" in ENV_TEMPLATE
        assert "single-engine UNVERIFIED" in ENV_TEMPLATE
