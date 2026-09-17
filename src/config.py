"""Configuration manager for the Autonomous GitHub Agent."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Literal
from pydantic import ConfigDict
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


def detect_active_ai_model(prefer_ide=False) -> str:
    """Environment selection is stable; IDE sync is opt-in and conversation-bound."""
    import json
    import re
    env_model = os.getenv("GEMINI_MODEL") or os.getenv("MODEL_NAME")
    if env_model and not prefer_ide:
        return env_model
    conv_id = os.getenv("ANTIGRAVITY_CONVERSATION_ID", "")
    if conv_id and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", conv_id):
        path = Path.home() / ".gemini/antigravity-ide/brain" / conv_id / ".system_generated/logs/transcript.jsonl"
        try:
            with path.open("rb") as file:
                file.seek(max(0, path.stat().st_size - 1024 * 1024))
                lines = file.read().decode(errors="replace").splitlines()
            for line in reversed(lines):
                try:
                    text = json.dumps(json.loads(line), ensure_ascii=False).replace("\\", "")
                except ValueError:
                    text = line
                match = re.search(r"Model Selection[`]? from .*? to (.+?)\.\s*No need", text)
                if match:
                    raw = match[1].lower()
                    for family in ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.1-pro"):
                        if family.split("-")[1] in raw:
                            return family + ("-low" if "low" in raw else "-medium" if "medium" in raw else "-high")
                    if "sonnet" in raw:
                        return "claude-sonnet-4-6"
                    if "opus" in raw:
                        return "claude-opus-4-6-thinking"
                    if "gpt-oss" in raw:
                        return "gpt-oss-120b-medium"
        except OSError:
            pass
    return env_model or "gemini-3.8-flash"


class AgentConfig(BaseModel):
    """Configuration settings for the GitHub Agent."""

    model_config = ConfigDict(validate_assignment=True, validate_default=True, extra="forbid")
    ai_provider: Literal["auto", "antigravity", "gemini", "anthropic", "openai"] = Field(default_factory=lambda: os.getenv("AI_PROVIDER", "auto"))
    anthropic_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY"))
    openai_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    openai_base_url: str = Field(default_factory=lambda: os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    antigravity_cli: str = Field(default_factory=lambda: os.getenv("ANTIGRAVITY_CLI", "agy"))
    sync_ide_model: bool = Field(default_factory=lambda: os.getenv("SYNC_IDE_MODEL", "false").lower() == "true")
    sandbox_image: Optional[str] = Field(default_factory=lambda: os.getenv("SANDBOX_IMAGE"))
    allow_host_tests: bool = Field(default_factory=lambda: os.getenv("ALLOW_HOST_TESTS", "false").lower() == "true")
    test_timeout: int = Field(default=180, ge=10, le=1800)
    provider_timeout: int = Field(default=300, ge=10, le=1800)
    accepted_cla_repos: List[str] = Field(default_factory=lambda: [v.strip() for v in os.getenv("ACCEPTED_CLA_REPOS", "").split(",") if v.strip()])

    @property
    def settings_file(self) -> Path:
        return self.scratch_dir / "settings.json"

    def public_settings(self) -> dict:
        keys = ("model_name", "ai_provider", "sync_ide_model", "dry_run", "inbox_poll_interval",
                "issue_hunt_interval", "max_concurrent_tasks", "target_languages", "target_labels", "min_repo_stars",
                "allowed_repos", "denied_repos", "max_repo_size_kb")
        return {key: getattr(self, key) for key in keys}

    def save_settings(self):
        from .safety_guardrails import atomic_write_json
        atomic_write_json(self.settings_file, self.public_settings())

    def load_settings(self):
        import json
        if self.settings_file.exists():
            data = json.loads(self.settings_file.read_text())
            checked = type(self).model_validate({**self.model_dump(), **data})
            for key in self.public_settings():
                setattr(self, key, getattr(checked, key))


    gemini_api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("GEMINI_API_KEY")
    )
    model_name: str = Field(default_factory=detect_active_ai_model)

    @property
    def model_display_name(self) -> str:
        name = self.model_name.lower()
        for version in ("3.8", "3.7", "3.6", "3.1"):
            if version in name and "gemini" in name:
                family = "Pro" if "pro" in name else "Flash"
                level = next((v.title() for v in ("high", "medium", "low") if name.endswith("-" + v)), None)
                return f"Gemini {version} {family}" + (f" ({level} Reasoning)" if level else "")
        if "sonnet" in name:
            return "Claude Sonnet 4.6"
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
        checked = type(self).model_validate({**self.model_dump(), **kwargs})
        for key in kwargs:
            setattr(self, key, getattr(checked, key))
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
    check_read_discussions: bool = Field(
        default_factory=lambda: os.getenv("CHECK_READ_DISCUSSIONS", "true").lower()
        in ("true", "1", "yes")
    )
    engage_discussions: bool = Field(
        default_factory=lambda: os.getenv("ENGAGE_DISCUSSIONS", "true").lower()
        in ("true", "1", "yes")
    )

    # Concurrency & Intervals (seconds)
    inbox_poll_interval: int = Field(
        default_factory=lambda: _safe_int("INBOX_POLL_INTERVAL", 60, minimum=5), ge=5, le=3600
    )
    issue_hunt_interval: int = Field(
        default_factory=lambda: _safe_int("ISSUE_HUNT_INTERVAL", 300, minimum=5), ge=5, le=7200
    )
    max_concurrent_tasks: int = Field(
        default_factory=lambda: _safe_int("MAX_CONCURRENT_TASKS", 3, minimum=1), ge=1, le=10
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
    allowed_repos: List[str] = Field(
        default_factory=lambda: [
            repo.strip()
            for repo in os.getenv("ALLOWED_REPOS", "").split(",")
            if repo.strip()
        ]
    )
    denied_repos: List[str] = Field(
        default_factory=lambda: [
            repo.strip()
            for repo in os.getenv(
                "DENIED_REPOS", "GTNewHorizons/GT-New-Horizons-Modpack"
            ).split(",")
            if repo.strip()
        ]
    )
    max_repo_size_kb: int = Field(
        default_factory=lambda: _safe_int("MAX_REPO_SIZE_KB", 250000, minimum=1000)
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
        if "scratch_dir" in self.model_fields_set:
            if "repos_dir" not in self.model_fields_set:
                self.repos_dir = self.scratch_dir / "repos"
            if "state_file" not in self.model_fields_set:
                self.state_file = self.scratch_dir / "agent_state.json"
        try:
            self.scratch_dir.mkdir(parents=True, exist_ok=True)
            self.repos_dir.mkdir(parents=True, exist_ok=True)
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


# Global singleton configuration
config = AgentConfig()
