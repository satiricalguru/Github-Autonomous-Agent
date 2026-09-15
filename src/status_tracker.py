"""Real-time Status and Activity Tracker for Autonomous GitHub Agent."""

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

try:
    from .config import AgentConfig, config
    from .safety_guardrails import atomic_write_json
except ImportError:
    from config import AgentConfig, config
    from safety_guardrails import atomic_write_json

logger = logging.getLogger("github_agent.status")


class StatusTracker:
    """Tracks real-time worker actions, active AI model, rate limits, and event logs."""

    def __init__(self, agent_config: Optional[AgentConfig] = None):
        self.config = agent_config or config
        self.status_file = self.config.scratch_dir / "agent_status.json"
        self._lock = threading.Lock()

        self.active_model = self.config.model_name
        self.model_display_name = self.config.model_display_name
        self.ai_mode = "Gemini API (Online)" if (self.config.gemini_api_key) else "Antigravity Heuristic Engine"
        self.rate_limit_remaining = 5000
        self.rate_limit_limit = 5000
        
        self.overall_status = "INITIALIZING"
        self.inbox_status: Dict[str, Any] = {
            "state": "IDLE",
            "current_action": "Waiting for worker start",
            "last_check": None,
            "next_check": None,
            "handled_count": 0,
        }
        self.hunter_status: Dict[str, Any] = {
            "state": "IDLE",
            "current_action": "Waiting for worker start",
            "current_query": None,
            "active_repo": None,
            "active_step": None,
            "last_check": None,
            "next_check": None,
        }
        self.recent_events: List[Dict[str, Any]] = []
        self._load()

    def _load(self):
        if not self.status_file.exists():
            return
        try:
            with open(self.status_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.overall_status = data.get("overall_status", self.overall_status)
                self.inbox_status = data.get("inbox_status", self.inbox_status)
                self.hunter_status = data.get("hunter_status", self.hunter_status)
                self.recent_events = data.get("recent_events", [])
                if isinstance(data.get("rate_limit_remaining"), int):
                    self.rate_limit_remaining = data["rate_limit_remaining"]
                if isinstance(data.get("rate_limit_limit"), int):
                    self.rate_limit_limit = data["rate_limit_limit"]
                if "dry_run" in data:
                    self.config.dry_run = bool(data["dry_run"])
        except Exception:
            pass

    def save(self):
        """Persist status snapshot to disk (thread-safe)."""
        try:
            with self._lock:
                snapshot = self.get_snapshot()
                atomic_write_json(self.status_file, snapshot)
        except Exception as e:
            logger.warning(f"Failed to persist agent status: {e}")

    def rebind(self, agent_config: Optional[AgentConfig] = None):
        """Re-point this tracker at a different config (tests/isolated runs)."""
        if agent_config is not None:
            self.config = agent_config
            self.status_file = self.config.scratch_dir / "agent_status.json"
        with self._lock:
            self.overall_status = "INITIALIZING"
            self.inbox_status = {
                "state": "IDLE",
                "current_action": "Waiting for worker start",
                "last_check": None,
                "next_check": None,
                "handled_count": 0,
            }
            self.hunter_status = {
                "state": "IDLE",
                "current_action": "Waiting for worker start",
                "current_query": None,
                "active_repo": None,
                "active_step": None,
                "last_check": None,
                "next_check": None,
            }
            self.recent_events = []
        self._load()

    def set_rate_limit(self, remaining: int, limit: int):
        """Record the last observed GitHub API quota."""
        try:
            self.rate_limit_remaining = int(remaining)
            self.rate_limit_limit = int(limit)
        except (ValueError, TypeError):
            return

    def update_inbox(
        self,
        state: str,
        current_action: str,
        handled_count: Optional[int] = None,
        next_check_in: Optional[int] = None,
    ):
        """Update inbox worker status."""
        self.inbox_status["state"] = state
        self.inbox_status["current_action"] = current_action
        self.inbox_status["last_check"] = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        if handled_count is not None:
            self.inbox_status["handled_count"] = handled_count
        if next_check_in is not None:
            self.inbox_status["next_check"] = f"in {next_check_in}s"
        self.save()

    def update_hunter(
        self,
        state: str,
        current_action: str,
        current_query: Optional[str] = None,
        active_repo: Optional[str] = None,
        active_step: Optional[str] = None,
        next_check_in: Optional[int] = None,
    ):
        """Update issue hunter worker status."""
        self.hunter_status["state"] = state
        self.hunter_status["current_action"] = current_action
        self.hunter_status["current_query"] = current_query
        self.hunter_status["active_repo"] = active_repo
        self.hunter_status["active_step"] = active_step
        self.hunter_status["last_check"] = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        if next_check_in is not None:
            self.hunter_status["next_check"] = f"in {next_check_in}s"
        self.save()

    def log_event(self, event_type: str, description: str, details: Optional[Dict[str, Any]] = None):
        """Log a new activity event."""
        event = {
            "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "type": event_type,
            "description": description,
            "details": details or {},
        }
        self.recent_events.insert(0, event)
        self.recent_events = self.recent_events[:20]  # Keep last 20
        self.save()

    def get_snapshot(self) -> Dict[str, Any]:
        """Return structured status snapshot."""
        # Sync cached model label with live config (web UI may change it).
        try:
            self.active_model = self.config.model_name
        except Exception:
            pass
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "active_model": self.config.model_name,
            "model_display_name": self.config.model_display_name,
            "ai_mode": self.ai_mode,
            "overall_status": self.overall_status,
            "operating_mode": "DRY-RUN (Safe Simulation)" if self.config.dry_run else "LIVE (Real Submissions)",
            "dry_run": self.config.dry_run,
            "inbox_poll_interval": self.config.inbox_poll_interval,
            "issue_hunt_interval": self.config.issue_hunt_interval,
            "target_languages": self.config.target_languages,
            "target_labels": self.config.target_labels,
            "max_prs_per_day": self.config.max_prs_per_day,
            "github_user": self.config.github_username or "Authenticated User",
            "inbox_worker": self.inbox_status,
            "hunter_worker": self.hunter_status,
            "recent_events": self.recent_events[:10],
            "rate_limit_remaining": self.rate_limit_remaining,
            "rate_limit_limit": self.rate_limit_limit,
        }

    def render_dashboard(self) -> Panel:
        """Create a rich formatted dashboard panel."""
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(ratio=1)
        table.add_column(ratio=1)

        # Left Column: AI Model & Overview
        overview_table = Table(title="🤖 Active AI Model & Core State", border_style="cyan", expand=True)
        overview_table.add_column("Property", style="bold yellow")
        overview_table.add_column("Value", style="green")

        overview_table.add_row("Active AI Model", f"[bold magenta]{self.config.model_name.upper()}[/bold magenta] ({self.config.model_display_name})")
        overview_table.add_row("AI Provider", self.ai_mode)
        overview_table.add_row("Agent State", f"[bold green]{self.overall_status}[/bold green]")
        overview_table.add_row("Execution Mode", "[yellow]DRY-RUN (Simulated)[/yellow]" if self.config.dry_run else "[bold green]LIVE[/bold green]")
        overview_table.add_row("GitHub Account", f"@{self.config.github_username or 'User'}")
        overview_table.add_row("Target Languages", ", ".join(self.config.target_languages))

        # Right Column: Workers & Live Tasks
        workers_table = Table(title="⚡ Real-Time Worker Status", border_style="green", expand=True)
        workers_table.add_column("Worker", style="bold cyan")
        workers_table.add_column("Current Activity", style="white")

        inbox_color = "green" if self.inbox_status["state"] == "POLLING" else "yellow"
        workers_table.add_row(
            f"[{inbox_color}]Inbox Manager[/{inbox_color}]",
            f"State: {self.inbox_status['state']}\n"
            f"Action: {self.inbox_status['current_action']}\n"
            f"Processed: {self.inbox_status['handled_count']} threads | Next: {self.inbox_status.get('next_check', 'soon')}",
        )

        hunter_color = "green" if self.hunter_status["state"] in ("HUNTING", "SOLVING") else "yellow"
        repo_info = f" (Repo: {self.hunter_status['active_repo']})" if self.hunter_status.get('active_repo') else ""
        workers_table.add_row(
            f"[{hunter_color}]Issue Hunter & Solver[/{hunter_color}]",
            f"State: {self.hunter_status['state']}{repo_info}\n"
            f"Action: {self.hunter_status['current_action']}\n"
            f"Step: {self.hunter_status.get('active_step') or 'Scanning criteria'} | Next: {self.hunter_status.get('next_check', 'soon')}",
        )

        table.add_row(overview_table, workers_table)

        # Recent events table
        events_table = Table(title="📋 Recent Activity Stream", border_style="dim", expand=True)
        events_table.add_column("Time", style="dim", width=12)
        events_table.add_column("Type", style="bold cyan", width=15)
        events_table.add_column("Activity Description", style="white")

        if not self.recent_events:
            events_table.add_row("--:--:--", "INFO", "Agent monitoring active queues...")
        else:
            for ev in self.recent_events[:6]:
                events_table.add_row(ev["timestamp"], ev["type"], ev["description"])

        layout_grid = Table.grid(expand=True)
        layout_grid.add_row(table)
        layout_grid.add_row(Text(""))  # Spacer
        layout_grid.add_row(events_table)

        main_panel = Panel(
            layout_grid,
            title="[bold green]🚀 Autonomous GitHub Agent Live Dashboard[/bold green]",
            border_style="bold blue",
            padding=(1, 1),
        )
        return main_panel


# Global tracker instance
status_tracker = StatusTracker()
