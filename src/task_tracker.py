"""Task history and detailed execution logger for Autonomous GitHub Agent."""

import json
import sqlite3
import copy
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

try:
    from .config import AgentConfig, config
    from .safety_guardrails import atomic_write_json
except ImportError:
    from config import AgentConfig, config
    from safety_guardrails import atomic_write_json

logger = logging.getLogger("github_agent.tasks")
console = Console()


class TaskTracker:
    """Manages detailed records of in-progress and completed agent tasks."""

    def __init__(self, agent_config: Optional[AgentConfig] = None):
        self.config = agent_config or config
        self.tasks_file = self.config.scratch_dir / "tasks_history.json"
        self.tasks: List[Dict[str, Any]] = []
        self._lock = threading.RLock()
        self._initialize()
        self._load()

    def _db(self):
        return sqlite3.connect(self.tasks_file.with_suffix(".sqlite3"), timeout=15)

    def _initialize(self):
        self.tasks_file.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, payload TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY)")
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM metadata WHERE key='migrated'").fetchone():
                if self.tasks_file.exists():
                    records = json.loads(self.tasks_file.read_text())
                    for task in records:
                        db.execute("INSERT OR IGNORE INTO tasks VALUES (?,?)", (task["id"], json.dumps(task)))
                db.execute("INSERT INTO metadata VALUES ('migrated')")

    def _load(self):
        with self._lock, self._db() as db:
            self.tasks = [json.loads(row[0]) for row in db.execute("SELECT payload FROM tasks ORDER BY rowid DESC LIMIT 100")]

    def save(self):
        self._load()
        atomic_write_json(self.tasks_file, self.tasks)

    def rebind(self, agent_config=None):
        if agent_config is not None:
            self.config = agent_config
            self.tasks_file = self.config.scratch_dir / "tasks_history.json"
        self._initialize()
        self._load()

    def create_task(self, category, title, target_repo=None, target_url=None, details=None):
        task_id = f"TASK-{int(time.time())}-{uuid.uuid4().hex[:8].upper()}"
        record = {"id": task_id, "category": category, "title": title,
            "target_repo": target_repo or "N/A", "target_url": target_url or "", "status": "IN_PROGRESS",
            "started_at": datetime.now(timezone.utc).isoformat(), "completed_at": None,
            "outcome": "Executing...", "details": details or {}}
        with self._lock, self._db() as db:
            db.execute("INSERT INTO tasks VALUES (?,?)", (task_id, json.dumps(record)))
        self.save()
        return task_id

    def complete_task(self, task_id, status="COMPLETED", outcome="Successfully completed", details_update=None):
        with self._lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise ValueError("Unknown task ID")
            task = json.loads(row[0])
            task.update(status=status, outcome=outcome, completed_at=datetime.now(timezone.utc).isoformat())
            task["details"].update(details_update or {})
            db.execute("UPDATE tasks SET payload=? WHERE id=?", (json.dumps(task), task_id))
        self.save()

    def get_all_tasks(self):
        self._load()
        return copy.deepcopy(self.tasks)

    def get_api_tasks(self):
        records = []
        for task in self.get_all_tasks():
            status = {"IN_PROGRESS": "running", "COMPLETED": "completed", "FAILED": "failed",
                      "CANCELLED": "cancelled", "SKIPPED": "skipped", "REJECTED": "rejected"}.get(task["status"], "pending")
            records.append({**task, "status": status,
                "type": "pr_solve" if task["category"] == "SOLVER" else "inbox_notification",
                "target": task["target_repo"], "created_at": task["started_at"],
                "pr_url": task["details"].get("pr_url"), "diff_preview": task["details"].get("diff_preview"),
                "error": task["outcome"] if status in ("failed", "rejected") else None})
        return records

    def get_completed_tasks(self):
        return [t for t in self.get_all_tasks() if t["status"] != "IN_PROGRESS"]

    def get_active_tasks(self):
        return [t for t in self.get_all_tasks() if t["status"] == "IN_PROGRESS"]

    def cancel_orphaned_tasks(self):
        for task in self.get_active_tasks():
            self.complete_task(task["id"], "CANCELLED", "Interrupted by previous process shutdown")

    def render_tasks_table(self) -> Table:
        """Render rich CLI table of all recent tasks."""
        table = Table(title="📋 Autonomous GitHub Agent - Tasks & Execution History", border_style="cyan")
        table.add_column("Task ID", style="dim", width=12)
        table.add_column("Category", style="bold cyan", width=12)
        table.add_column("Task Title & Target", style="white")
        table.add_column("Status", width=14)
        table.add_column("Completed At", style="dim", width=16)
        table.add_column("Outcome / Result", style="green")

        if not self.tasks:
            table.add_row("--", "NONE", "No tasks recorded yet.", "IDLE", "--", "Waiting for events")
            return table

        for t in self.tasks[:15]:
            status_style = {
                "IN_PROGRESS": "[bold yellow]⏳ RUNNING[/bold yellow]",
                "COMPLETED": "[bold green]✓ COMPLETED[/bold green]",
                "FAILED": "[bold red]✗ FAILED[/bold red]",
                "SKIPPED": "[dim]↷ SKIPPED[/dim]",
                "REJECTED": "[bold red]✗ REJECTED[/bold red]",
            }.get(t["status"], t["status"])

            completed_at = t.get("completed_at") or ""
            started_at = t.get("started_at") or ""
            time_src = completed_at or started_at
            try:
                time_str = time_src.split(" ")[1] if " " in time_src else time_src
            except Exception:
                time_str = "--:--:--"
            repo_prefix = f"[{t.get('target_repo', 'N/A')}] " if t.get('target_repo') not in (None, "N/A", "") else ""
            table.add_row(
                t.get("id", "--"),
                t.get("category", "?"),
                f"{repo_prefix}{str(t.get('title', ''))[:45]}",
                status_style,
                time_str or "--:--:--",
                str(t.get("outcome", ""))[:40],
            )

        return table


# Global singleton
task_tracker = TaskTracker()
