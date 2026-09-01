"""Configuration manager for the Autonomous GitHub Agent."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load local .env if present
load_dotenv()


def get_gh_cli_token() -> Optional[str]:
    """Attempts to retrieve the current GitHub token from `gh auth token`."""
    if not shutil.which("gh"):
        return None
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        token = result.stdout.strip()
        return token if token else None
    except Exception:
        return None


def get_gh_cli_username() -> Optional[str]:
    """Attempts to retrieve the active GitHub username from `gh api user`."""
    if not shutil.which("gh"):
        return None
    try:
        result = subprocess.run(
            ["gh", "api", "user", "-q", ".login"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        username = result.stdout.strip()
        return username if username else None
    except Exception:
        return None


class AgentConfig(BaseModel):
    """Configuration settings for the GitHub Agent."""

    gemini_api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("GEMINI_API_KEY")
    )
    model_name: str = Field(
        default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.7-flash")
    )
    github_token: Optional[str] = Field(
        default_factory=lambda: os.getenv("GITHUB_TOKEN") or get_gh_cli_token()
    )
    github_username: Optional[str] = Field(
        default_factory=lambda: os.getenv("GITHUB_USERNAME") or get_gh_cli_username()
    )

    # Operational Modes
    dry_run: bool = Field(
        default_factory=lambda: os.getenv("DRY_RUN", "true").lower() in ("true", "1", "yes")
    )
    auto_test_verification: bool = Field(
        default_factory=lambda: os.getenv("AUTO_TEST_VERIFICATION", "true").lower()
        in ("true", "1", "yes")
    )

    # Concurrency & Intervals (seconds)
    inbox_poll_interval: int = Field(
        default_factory=lambda: int(os.getenv("INBOX_POLL_INTERVAL", "60"))
    )
    issue_hunt_interval: int = Field(
        default_factory=lambda: int(os.getenv("ISSUE_HUNT_INTERVAL", "300"))
    )
    max_concurrent_tasks: int = Field(
        default_factory=lambda: int(os.getenv("MAX_CONCURRENT_TASKS", "3"))
    )

    # Issue Hunter Search Criteria
    target_languages: List[str] = Field(
        default_factory=lambda: [
            lang.strip()
            for lang in os.getenv(
                "TARGET_LANGUAGES", "python,typescript,javascript,go,rust"
            ).split(",")
            if lang.strip()
        ]
    )
    min_repo_stars: int = Field(
        default_factory=lambda: int(os.getenv("MIN_REPO_STARS", "1000"))
    )
    target_labels: List[str] = Field(
        default_factory=lambda: [
            label.strip()
            for label in os.getenv(
                "TARGET_LABELS", "good first issue,help wanted,bug"
            ).split(",")
            if label.strip()
        ]
    )

    # Safety & Limits
    max_prs_per_day: int = Field(
        default_factory=lambda: int(os.getenv("MAX_PRS_PER_DAY", "5"))
    )
    min_rate_limit_remaining: int = Field(
        default_factory=lambda: int(os.getenv("MIN_RATE_LIMIT_REMAINING", "100"))
    )

    # Directories & State
    base_dir: Path = Field(default_factory=lambda: Path.cwd())
    scratch_dir: Path = Field(
        default_factory=lambda: Path.cwd() / "scratch"
    )
    repos_dir: Path = Field(
        default_factory=lambda: Path.cwd() / "scratch" / "repos"
    )
    state_file: Path = Field(
        default_factory=lambda: Path.cwd() / "scratch" / "agent_state.json"
    )

    def model_post_init(self, __context):
        """Ensure directories exist."""
        self.scratch_dir.mkdir(parents=True, exist_ok=True)
        self.repos_dir.mkdir(parents=True, exist_ok=True)


# Global singleton configuration
config = AgentConfig()
