"""Command-line interface for the Autonomous GitHub Agent."""

import argparse
import asyncio
import logging
import signal
import sys
from typing import Any, Dict, List, Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

try:
    from .config import AgentConfig, config
    from .github_client import GitHubClient
    from .inbox_manager import InboxManager
    from .issue_hunter import IssueHunter
    from .orchestrator import AutonomousOrchestrator
    from .pr_solver import PRSolver
    from .safety_guardrails import SafetyGuardrails
    from .status_tracker import status_tracker
    from .task_tracker import task_tracker
    from .web_dashboard import start_web_server
except ImportError:
    from config import AgentConfig, config
    from github_client import GitHubClient
    from inbox_manager import InboxManager
    from issue_hunter import IssueHunter
    from orchestrator import AutonomousOrchestrator
    from pr_solver import PRSolver
    from safety_guardrails import SafetyGuardrails
    from status_tracker import status_tracker
    from task_tracker import task_tracker
    from web_dashboard import start_web_server

console = Console()


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


async def cmd_status():
    """Print real-time agent dashboard, active model, worker states, and metrics."""
    console.print(status_tracker.render_dashboard())


def cmd_tasks():
    """Print detailed table of completed and in-progress tasks."""
    console.print(task_tracker.render_tasks_table())


def cmd_web(port: int = 3000):
    """Launch the live web dashboard interface."""
    import time
    server = start_web_server(port=port)
    if server:
        console.print(f"[bold green]✓ Live Web Dashboard running at:[/bold green] [bold cyan]http://localhost:{port}[/bold cyan]")
        console.print("[dim]Press Ctrl+C to stop the dashboard server.[/dim]")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            console.print("\n[yellow]Stopping web dashboard...[/yellow]")
            server.shutdown()


async def cmd_inbox(dry_run: Optional[bool] = None):
    """Run a single pass of inbox triage."""
    if dry_run is not None:
        config.dry_run = dry_run

    console.print(f"[bold cyan]Running Inbox Triage (Mode: {'DRY-RUN' if config.dry_run else 'LIVE'})...[/bold cyan]")
    async with GitHubClient(config) as client:
        inbox = InboxManager(client=client, agent_config=config)
        results = await inbox.process_inbox()

        if not results:
            console.print("[green]No unread notifications to process.[/green]")
            return

        table = Table(title="Inbox Triage Results", border_style="green")
        table.add_column("Thread ID", style="dim")
        table.add_column("Repository", style="bold")
        table.add_column("Subject", style="white")
        table.add_column("Reason", style="cyan")
        table.add_column("Action", style="green")

        for r in results:
            table.add_row(
                str(r["thread_id"]),
                r["repo"],
                r["title"][:50],
                r["reason"],
                r["action"],
            )

        console.print(table)


async def cmd_hunt(limit: int = 5):
    """Search for actionable bug issues in top-tier repositories."""
    console.print(f"[bold cyan]Hunting top-tier issues (limit={limit})...[/bold cyan]")
    async with GitHubClient(config) as client:
        hunter = IssueHunter(client=client, agent_config=config)
        issues = await hunter.hunt_issues(limit=limit)

        if not issues:
            console.print("[yellow]No open issues matching criteria found at this time.[/yellow]")
            return

        table = Table(title="Actionable Open-Source Issues", border_style="cyan")
        table.add_column("Repo", style="bold green")
        table.add_column("#", style="dim")
        table.add_column("Title", style="white")
        table.add_column("Language", style="magenta")
        table.add_column("Score", style="yellow")
        table.add_column("URL", style="blue")

        for iss in issues:
            table.add_row(
                iss["repo"],
                str(iss["issue_number"]),
                iss["title"][:50],
                iss["language"],
                f"{iss['score']:.2f}",
                iss["url"],
            )

        console.print(table)


async def cmd_start(dry_run: Optional[bool] = None):
    """Start continuous autonomous loop with graceful shutdown."""
    if dry_run is not None:
        config.dry_run = dry_run

    orchestrator = AutonomousOrchestrator(config)

    # Register OS signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: orchestrator.stop())
        except NotImplementedError:
            pass

    await orchestrator.start()


def main():
    parser = argparse.ArgumentParser(description="Autonomous GitHub Agent for Google Antigravity")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")

    subparsers = parser.add_subparsers(dest="command", help="Agent command to execute")

    # Start command
    start_parser = subparsers.add_parser("start", help="Start continuous autonomous agent loop")
    start_parser.add_argument("--dry-run", action="store_true", help="Run in dry-run mode (no live writes)")
    start_parser.add_argument("--live", action="store_true", help="Run in live mode (submits PRs and replies)")

    # Status command
    subparsers.add_parser("status", help="Check agent status, credentials, and rate limits")

    # Tasks command
    subparsers.add_parser("tasks", help="List all completed and in-progress agent tasks")

    # Web dashboard command
    web_parser = subparsers.add_parser("web", help="Launch live browser dashboard")
    web_parser.add_argument("--port", type=int, default=3000, help="Port to bind dashboard server (default: 3000)")

    # Inbox command
    inbox_parser = subparsers.add_parser("inbox", help="Run a single pass of inbox triage")
    inbox_parser.add_argument("--dry-run", action="store_true", help="Simulate replies only")

    # Hunt command
    hunt_parser = subparsers.add_parser("hunt", help="Search top-tier repos for open issues")
    hunt_parser.add_argument("--limit", type=int, default=5, help="Number of issues to return")

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.command == "status":
        asyncio.run(cmd_status())
    elif args.command == "tasks":
        cmd_tasks()
    elif args.command == "web":
        cmd_web(port=args.port)
    elif args.command == "inbox":
        asyncio.run(cmd_inbox(dry_run=args.dry_run if args.dry_run else None))
    elif args.command == "hunt":
        asyncio.run(cmd_hunt(limit=args.limit))
    elif args.command == "start" or args.command is None:
        dry_run = True if getattr(args, "dry_run", False) else (False if getattr(args, "live", False) else None)
        asyncio.run(cmd_start(dry_run=dry_run))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
