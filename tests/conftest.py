"""Tests never use the user's live model or GitHub credentials."""
import os
import tempfile
from pathlib import Path
import pytest

_state = tempfile.TemporaryDirectory(prefix="github-agent-tests-")
os.environ.update(GITHUB_AGENT_NO_GH="true", AI_PROVIDER="gemini", GEMINI_API_KEY="",
                  GITHUB_TOKEN="", GITHUB_USERNAME="fixture-user", SCRATCH_DIR=_state.name,
                  ANTHROPIC_API_KEY="", OPENAI_API_KEY="",
                  SYNC_IDE_MODEL="false")

@pytest.fixture
def cfg(tmp_path):
    from src.config import AgentConfig
    return AgentConfig(scratch_dir=tmp_path, repos_dir=tmp_path / "repos",
                       state_file=tmp_path / "state.json", github_token=None,
                       github_username="fixture-user", gemini_api_key=None,
                       ai_provider="gemini", dry_run=True)
