"""Safety guardrails, anti-spam policies, rate-limiting, and state management."""

import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

if TYPE_CHECKING:
    from .config import AgentConfig, config
else:
    try:
        from .config import AgentConfig, config
    except ImportError:
        from config import AgentConfig, config

logger = logging.getLogger("github_agent.safety")

# Blacklisted phrases that indicate low-quality AI generated spam
AI_SPAM_SIGNATURES = [
    r"as an ai (language )?model",
    r"i am an ai agent",
    r"i am a bot",
    r"as a large language model",
    r"i cannot fulfill this request",
    r"here is the fixed code:",
    r"let me know if you need anything else\.",
    r"i hope this helps!",
    r"as an automated system",
]


def atomic_write_json(file_path: Path, data: Any):
    """Atomically writes JSON data to disk using a temporary file and atomic replace."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = file_path.with_name(
        f"{file_path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}"
    )
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_file, file_path)
    except Exception:
        if temp_file.exists():
            try:
                temp_file.unlink()
            except Exception:
                pass
        raise


class StateStore:
    """Persistent state manager to avoid duplicates and track activity."""

    def __init__(self, state_file: Optional[Path] = None):
        self.state_file = state_file or config.state_file
        self.handled_notifications: Set[str] = set()
        self.handled_issues: Set[str] = set()
        self.submitted_prs: List[Dict[str, Any]] = []
        self._load()

    def _load(self):
        if not self.state_file.exists():
            return
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.handled_notifications = set(data.get("handled_notifications", []))
                self.handled_issues = set(data.get("handled_issues", []))
                self.submitted_prs = data.get("submitted_prs", [])
        except Exception as e:
            logger.warning(f"Failed to load state file {self.state_file}: {e}")
            # Preserve corrupt file for forensics instead of silently dropping it.
            try:
                backup = self.state_file.with_suffix(".corrupt.bak")
                if not backup.exists():
                    self.state_file.replace(backup)
            except Exception:
                pass

    def save(self):
        try:
            atomic_write_json(
                self.state_file,
                {
                    "handled_notifications": list(self.handled_notifications),
                    "handled_issues": list(self.handled_issues),
                    "submitted_prs": self.submitted_prs,
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception as e:
            logger.error(f"Failed to save state file {self.state_file}: {e}")

    def is_notification_handled(self, thread_id: str) -> bool:
        return str(thread_id) in self.handled_notifications

    def mark_notification_handled(self, thread_id: str):
        self.handled_notifications.add(str(thread_id))
        self.save()

    def is_issue_handled(self, issue_url: str) -> bool:
        return issue_url in self.handled_issues

    def mark_issue_handled(self, issue_url: str):
        self.handled_issues.add(issue_url)
        self.save()

    def record_pr_submission(self, repo: str, issue_url: str, pr_url: str):
        self.submitted_prs.append(
            {
                "repo": repo,
                "issue_url": issue_url,
                "pr_url": pr_url,
                "timestamp": time.time(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self.save()

    def get_recent_pr_count(self, hours: int = 24) -> int:
        cutoff = time.time() - (hours * 3600)
        return sum(1 for pr in self.submitted_prs if pr.get("timestamp", 0) >= cutoff)


class SafetyGuardrails:
    """Enforces GitHub community guidelines, anti-spam rules, and safety limits."""

    def __init__(self, agent_config: Optional[AgentConfig] = None):
        self.config = agent_config or config
        self.state = StateStore(self.config.state_file)

    def can_submit_pr(self) -> tuple[bool, str]:
        """Check if daily PR limit allows submitting another PR."""
        recent_count = self.state.get_recent_pr_count(24)
        if recent_count >= self.config.max_prs_per_day:
            return False, f"Daily PR limit reached ({recent_count}/{self.config.max_prs_per_day} in 24h)."
        return True, "OK"

    def sanitize_comment(self, text: str) -> str:
        """Strip conversational LLM artifacts and AI disclaimers."""
        cleaned = text.strip()
        for pattern in AI_SPAM_SIGNATURES:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()
        # Clean double newlines
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned

    def validate_content_safety(self, text: str) -> tuple[bool, str]:
        """Verify comment/PR text does not violate quality standards."""
        if not text or len(text.strip()) < 10:
            return False, "Content too short or empty."

        lower_text = text.lower()
        if "as an ai" in lower_text or "i am a bot" in lower_text:
            return False, "Content contains prohibited AI self-reference."

        return True, "OK"

    def check_rate_limit(self, remaining: int) -> tuple[bool, str]:
        """Verify API rate limit threshold."""
        if remaining < self.config.min_rate_limit_remaining:
            return (
                False,
                f"Rate limit critical ({remaining} remaining < {self.config.min_rate_limit_remaining}). Pausing actions.",
            )
        return True, "OK"
