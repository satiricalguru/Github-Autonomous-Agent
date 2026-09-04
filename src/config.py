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


def _safe_int(env_key: str, default: int, minimum: Optional[int] = None) -> int:
    """Parse an int env var defensively, falling back to default on bad input."""
    try:
        value = int(str(os.getenv(env_key, str(default))).strip())
    except (ValueError, TypeError, AttributeError):
        return default
    if minimum is not None and value < minimum:
        return default
    return value


def _gh_disabled() -> bool:
    """Allow skipping gh CLI subprocess calls (CI/tests) via env flag."""
    return os.getenv("GITHUB_AGENT_NO_GH", "").lower() in ("true", "1", "yes")


def get_gh_cli_token() -> Optional[str]:
    """Attempts to retrieve the current GitHub token from `gh auth token`."""
    if _gh_disabled() or not shutil.which("gh"):
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
    if _gh_disabled() or not shutil.which("gh"):
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


def detect_active_ai_model() -> str:
    """Detects active AI model from environment or Antigravity IDE session."""
    env_model = os.getenv("GEMINI_MODEL") or os.getenv("MODEL_NAME")
    if env_model:
        return env_model

    conv_id = os.getenv("ANTIGRAVITY_CONVERSATION_ID")
    if conv_id and len(conv_id) < 256 and "/" not in conv_id and "\\" not in conv_id:
        transcript = (
            Path.home()
            / ".gemini"
            / "antigravity-ide"
            / "brain"
            / conv_id
            / ".system_generated"
            / "logs"
            / "transcript.jsonl"
        )
        if transcript.exists():
            try:
                import re

                # Cap transcript scan to avoid pathological I/O on huge files.
                max_lines = 500
                with open(transcript, "r", encoding="utf-8") as f:
                    for idx, line in enumerate(f):
                        if idx >= max_lines or len(line) > 20000:
                            continue
                        m = re.search(
                            r"Model Selection\` from \S+ to (.+?)\.\s*No need", line
                        )
                        if m:
                            raw = m.group(1).strip()
                            if "3.8" in raw:
                                return "gemini-3.8-flash"
                            elif "3.7" in raw:
                                return "gemini-3.7-flash"
                            elif "3.6" in raw:
                                return "gemini-3.6-flash"
                            elif "3.1" in raw and "pro" in raw.lower():
                                return "gemini-3.1-pro"
                            elif "sonnet" in raw.lower():
                                return "claude-sonnet-4.6"
                            elif "opus" in raw.lower():
                                return "claude-opus-4.6"
                            elif "gpt-oss" in raw.lower() or "120b" in raw.lower():
                                return "gpt-oss-120b"
                            elif "2.5" in raw and "pro" in raw.lower():
                                return "gemini-2.5-pro"
                            elif "2.5" in raw:
                                return "gemini-2.5-flash"
                            return raw.lower().replace(" ", "-")
            except Exception:
                pass
    return "gemini-3.8-flash"


class AgentConfig(BaseModel):
    """Configuration settings for the GitHub Agent."""

    gemini_api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("GEMINI_API_KEY")
    )
    model_name: str = Field(default_factory=detect_active_ai_model)

    @property
    def model_display_name(self) -> str:
        name = self.model_name.lower()
        if "3.8" in name:
            return "Gemini 3.8 Flash (High Reasoning)"
        elif "3.7" in name:
            return "Gemini 3.7 Flash (High Reasoning)"
        elif "3.6" in name:
            return "Gemini 3.6 Flash"
        elif "3.1" in name and "pro" in name:
            return "Gemini 3.1 Pro"
        elif "sonnet" in name:
            return "Claude Sonnet 4.6 (Thinking)"
        elif "opus" in name:
            return "Claude Opus 4.6 (Thinking)"
        elif "gpt-oss" in name or "120b" in name:
            return "GPT-OSS 120B (Medium)"
        elif "2.5" in name and "pro" in name:
            return "Gemini 2.5 Pro"
        elif "2.5" in name:
            return "Gemini 2.5 Flash"
        return self.model_name.upper()

    def update(self, **kwargs):
        """Update runtime configuration fields safely with validation."""
        for key, value in kwargs.items():
            if not hasattr(self, key):
                continue
            # Coerce numeric interval/limit fields defensively.
            if key in (
                "inbox_poll_interval",
                "issue_hunt_interval",
                "max_concurrent_tasks",
                "min_repo_stars",
                "max_prs_per_day",
                "min_rate_limit_remaining",
            ):
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    continue
                if key in ("inbox_poll_interval", "issue_hunt_interval") and value < 5:
                    continue
                if key in ("max_concurrent_tasks", "max_prs_per_day") and value < 1:
                    continue
            setattr(self, key, value)
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
        default_factory=lambda: _safe_int("INBOX_POLL_INTERVAL", 60, minimum=5)
    )
    issue_hunt_interval: int = Field(
        default_factory=lambda: _safe_int("ISSUE_HUNT_INTERVAL", 300, minimum=5)
    )
    max_concurrent_tasks: int = Field(
        default_factory=lambda: _safe_int("MAX_CONCURRENT_TASKS", 3, minimum=1)
    )

    # Issue Hunter Search Criteria
    target_languages: List[str] = Field(
        default_factory=lambda: [
            lang.strip().lower()
            for lang in os.getenv(
                "TARGET_LANGUAGES", "python,typescript,javascript,go,rust"
            ).split(",")
            if lang.strip()
        ]
    )
    min_repo_stars: int = Field(
        default_factory=lambda: _safe_int("MIN_REPO_STARS", 1000, minimum=0)
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
        default_factory=lambda: _safe_int("MAX_PRS_PER_DAY", 5, minimum=1)
    )
    min_rate_limit_remaining: int = Field(
        default_factory=lambda: _safe_int("MIN_RATE_LIMIT_REMAINING", 100, minimum=0)
    )

    # Directories & State (overridable via BASE_DIR / SCRATCH_DIR env for tests)
    base_dir: Path = Field(
        default_factory=lambda: Path(os.getenv("BASE_DIR", str(Path.cwd())))
    )
    scratch_dir: Path = Field(
        default_factory=lambda: Path(
            os.getenv("SCRATCH_DIR", str(Path.cwd() / "scratch"))
        )
    )
    repos_dir: Path = Field(
        default_factory=lambda: Path(
            os.getenv("SCRATCH_DIR", str(Path.cwd() / "scratch"))
        )
        / "repos"
    )
    state_file: Path = Field(
        default_factory=lambda: Path(
            os.getenv("SCRATCH_DIR", str(Path.cwd() / "scratch"))
        )
        / "agent_state.json"
    )

    def model_post_init(self, __context):
        """Ensure directories exist (best-effort, never crash on read-only FS)."""
        try:
            self.scratch_dir.mkdir(parents=True, exist_ok=True)
            self.repos_dir.mkdir(parents=True, exist_ok=True)
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


# Global singleton configuration
config = AgentConfig()
