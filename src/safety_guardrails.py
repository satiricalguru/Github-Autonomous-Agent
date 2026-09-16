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
    """SQLite transactions are authoritative; JSON is a compatibility snapshot."""

    def __init__(self, state_file: Optional[Path] = None):
        import sqlite3
        self.state_file = state_file or config.state_file
        self.db_file = self.state_file.with_suffix(".sqlite3")
        self.db_file.parent.mkdir(parents=True, exist_ok=True)
        self.handled_notifications = set()
        self.handled_issues = set()
        self.submitted_prs = []
        with sqlite3.connect(self.db_file, timeout=15) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS handled (kind TEXT, value TEXT, PRIMARY KEY(kind,value))")
            db.execute("CREATE TABLE IF NOT EXISTS prs (url TEXT PRIMARY KEY, repo TEXT, issue TEXT, timestamp REAL)")
            db.execute("CREATE TABLE IF NOT EXISTS claims (issue TEXT PRIMARY KEY, expires REAL)")
            db.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)")
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM metadata WHERE key='migrated'").fetchone():
                if self.state_file.exists():
                    # A corrupt history must not silently reset submission limits.
                    data = json.loads(self.state_file.read_text())
                    simulated = {pr.get("issue_url") for pr in data.get("submitted_prs", []) if str(pr.get("pr_url", "")).endswith("mock-dry-run")}
                    real = {pr.get("issue_url") for pr in data.get("submitted_prs", []) if not str(pr.get("pr_url", "")).endswith("mock-dry-run")}
                    for kind, key in (("notification", "handled_notifications"), ("issue", "handled_issues")):
                        db.executemany("INSERT OR IGNORE INTO handled VALUES (?,?)", [(kind, str(v)) for v in data.get(key, []) if kind != "issue" or v not in simulated - real])
                    for pr in data.get("submitted_prs", []):
                        if not str(pr.get("pr_url", "")).endswith("mock-dry-run"):
                            db.execute("INSERT OR IGNORE INTO prs VALUES (?,?,?,?)", (pr.get("pr_url", ""), pr.get("repo", ""), pr.get("issue_url", ""), pr.get("timestamp", 0)))
                db.execute("INSERT INTO metadata VALUES ('migrated','1')")
        self._load()

    def _connect(self):
        import sqlite3
        return sqlite3.connect(self.db_file, timeout=15)

    def _load(self):
        with self._connect() as db:
            rows = db.execute("SELECT kind,value FROM handled").fetchall()
            self.handled_notifications = {v for k, v in rows if k == "notification"}
            self.handled_issues = {v for k, v in rows if k == "issue"}
            self.submitted_prs = [{"pr_url": u, "repo": r, "issue_url": i, "timestamp": t,
                "created_at": datetime.fromtimestamp(t, timezone.utc).isoformat()}
                for u,r,i,t in db.execute("SELECT url,repo,issue,timestamp FROM prs ORDER BY timestamp")]

    def save(self):
        self._load()
        atomic_write_json(self.state_file, {"handled_notifications": sorted(self.handled_notifications),
            "handled_issues": sorted(self.handled_issues), "submitted_prs": self.submitted_prs,
            "last_updated": datetime.now(timezone.utc).isoformat()})

    def is_notification_handled(self, thread_id):
        self._load()
        return str(thread_id) in self.handled_notifications

    def mark_notification_handled(self, thread_id):
        with self._connect() as db:
            db.execute("INSERT OR IGNORE INTO handled VALUES ('notification',?)", (str(thread_id),))
        self.save()

    def is_issue_handled(self, issue_url):
        self._load()
        return str(issue_url) in self.handled_issues

    def mark_issue_handled(self, issue_url):
        with self._connect() as db:
            db.execute("INSERT OR IGNORE INTO handled VALUES ('issue',?)", (str(issue_url),))
        self.save()

    def record_pr_submission(self, repo, issue_url, pr_url):
        if str(pr_url).endswith("mock-dry-run"):
            return
        with self._connect() as db:
            db.execute("INSERT OR IGNORE INTO prs VALUES (?,?,?,?)", (pr_url, repo, issue_url, time.time()))
            db.execute("DELETE FROM claims WHERE issue=?", (issue_url,))
        self.save()

    def get_recent_pr_count(self, hours=24):
        with self._connect() as db:
            return db.execute("SELECT count(*) FROM prs WHERE timestamp>=?", (time.time()-hours*3600,)).fetchone()[0]

    def claim_issue(self, issue_url, max_prs, reserve_slot=True):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM claims WHERE expires<?", (time.time(),))
            recent = db.execute("SELECT count(*) FROM prs WHERE timestamp>=?", (time.time()-86400,)).fetchone()[0]
            reserved = db.execute("SELECT count(*) FROM claims").fetchone()[0]
            if reserve_slot and recent + reserved >= max_prs:
                return False
            if db.execute("SELECT 1 FROM handled WHERE kind='issue' AND value=?", (issue_url,)).fetchone():
                return False
            if db.execute("SELECT 1 FROM claims WHERE issue=?", (issue_url,)).fetchone():
                return False
            # Bound exceeds four maximum test runs, two model calls, and git work.
            db.execute("INSERT INTO claims VALUES (?,?)", (issue_url, time.time()+4*3600))
            return True

    def release_issue(self, issue_url):
        with self._connect() as db:
            db.execute("DELETE FROM claims WHERE issue=?", (issue_url,))

    def clear_orphaned_claims(self):
        """Call only while holding the workspace execution lease, before new work."""
        with self._connect() as db:
            db.execute("DELETE FROM claims")


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

    def check_rate_limit(self, remaining: Optional[int]) -> tuple[bool, str]:
        """Verify API rate limit threshold."""
        if remaining is None:
            return False, "GitHub quota unavailable; execution blocked."
        if remaining < self.config.min_rate_limit_remaining:
            return (
                False,
                f"Rate limit critical ({remaining} remaining < {self.config.min_rate_limit_remaining}). Pausing actions.",
            )
        return True, "OK"
