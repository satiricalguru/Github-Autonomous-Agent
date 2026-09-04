"""Task history and detailed execution logger for Autonomous GitHub Agent."""

import json
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
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        if not self.tasks_file.exists():
            return
        try:
            with open(self.tasks_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, list):
                    self.tasks = loaded
        except Exception as e:
            logger.debug(f"Transient read failure on {self.tasks_file}: {e}")

    def save(self):
        try:
            with self._lock:
                tasks_snapshot = list(self.tasks)
            atomic_write_json(self.tasks_file, tasks_snapshot)
        except Exception as e:
            logger.warning(f"Failed to save tasks history: {e}")

    def rebind(self, agent_config: Optional[AgentConfig] = None):
        """Re-point this tracker at a different config (tests/isolated runs)."""
        if agent_config is not None:
            self.config = agent_config
            self.tasks_file = self.config.scratch_dir / "tasks_history.json"
        self.tasks = []
        self._load()

    def create_task(
        self,
        category: str,
        title: str,
        target_repo: Optional[str] = None,
        target_url: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Register a new task in progress."""
        task_id = f"TASK-{int(time.time())}-{uuid.uuid4().hex[:4].upper()}"
        task_obj = {
            "id": task_id,
            "category": category,
            "title": title,
            "target_repo": target_repo or "N/A",
            "target_url": target_url or "",
            "status": "IN_PROGRESS",
            "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "completed_at": None,
            "outcome": "Executing...",
            "details": details or {},
        }
        self.tasks.insert(0, task_obj)
        self.tasks = self.tasks[:100]  # Keep last 100 tasks
        self.save()
        return task_id

    def complete_task(
        self,
        task_id: str,
        status: str = "COMPLETED",
        outcome: str = "Successfully completed",
        details_update: Optional[Dict[str, Any]] = None,
    ):
        """Mark an active task as finished."""
        for t in self.tasks:
            if t["id"] == task_id:
                t["status"] = status
                t["completed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                t["outcome"] = outcome
                if details_update:
                    t["details"].update(details_update)
                break
        self.save()

    def get_all_tasks(self) -> List[Dict[str, Any]]:
        return self.tasks

    def get_completed_tasks(self) -> List[Dict[str, Any]]:
        return [t for t in self.tasks if t["status"] in ("COMPLETED", "SKIPPED", "REJECTED", "FAILED")]

    def get_active_tasks(self) -> List[Dict[str, Any]]:
        return [t for t in self.tasks if t["status"] == "IN_PROGRESS"]

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
