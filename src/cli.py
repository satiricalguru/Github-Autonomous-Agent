"""Command-line interface for the Autonomous GitHub Agent."""

import argparse
import asyncio
import logging
import signal
from typing import Optional
from rich.console import Console
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
    try:
        server = start_web_server(port=port)
    except OSError as e:
        console.print(f"[bold red]Failed to bind web dashboard on port {port}: {e}[/bold red]")
        return
    if server:
        console.print(f"[bold green]✓ Live Web Dashboard running at:[/bold green] [bold cyan]http://localhost:{port}[/bold cyan]")
        console.print("[dim]Press Ctrl+C to stop the dashboard server.[/dim]")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            console.print("\n[yellow]Stopping web dashboard...[/yellow]")
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass
    else:
        console.print(f"[bold red]Could not start web dashboard on port {port} (already in use?).[/bold red]")


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
                str(r.get("thread_id", "--")),
                str(r.get("repo", "?")),
                str(r.get("title", ""))[:50],
                str(r.get("reason", "")),
                str(r.get("action", "")),
            )

        console.print(table)


async def cmd_hunt(limit: int = 5):
    """Search for actionable bug issues in top-tier repositories."""
    limit = max(1, min(int(limit or 5), 50))
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
            try:
                score_val = float(iss.get("score", 0.0))
            except (ValueError, TypeError):
                score_val = 0.0
            table.add_row(
                str(iss.get("repo", "?")),
                str(iss.get("issue_number", "?")),
                str(iss.get("title", ""))[:50],
                str(iss.get("language", "N/A")),
                f"{score_val:.2f}",
                str(iss.get("url", "")),
            )

        console.print(table)


async def cmd_solve(auto: bool = True, limit: int = 1, dry_run: Optional[bool] = None):
    """Find actionable top-tier issues and attempt verified solution."""
    if dry_run is not None:
        config.dry_run = dry_run
    limit = max(1, min(int(limit or 1), 10))
    console.print(f"[bold cyan]Hunting and solving top-tier issues (auto={auto}, limit={limit}, mode={'DRY-RUN' if config.dry_run else 'LIVE'})...[/bold cyan]")
    async with GitHubClient(config) as client:
        hunter = IssueHunter(client=client, agent_config=config)
        solver = PRSolver(client=client, agent_config=config)
        candidates = await hunter.hunt_issues(limit=limit)
        if not candidates:
            console.print("[yellow]No actionable issues discovered matching search criteria.[/yellow]")
            return
        for c in candidates:
            console.print(f"[cyan]Attempting fix for {c.get('repo', '?')}#{c.get('issue_number', '?')}: {c.get('title', '')[:80]}[/cyan]")
            res = await solver.solve_issue(c)
            if res:
                console.print(f"[bold green]✓ PR Processed:[/bold green] {res.get('pr_url', '?')} (Dry Run: {res.get('dry_run', False)})")
            else:
                console.print(f"[yellow]Could not complete fix for {c.get('repo', '?')}#{c.get('issue_number', '?')}[/yellow]")


def cmd_stop():
    """Stop background agent execution."""
    status_tracker.overall_status = "STOPPED"
    status_tracker.log_event("SYSTEM", "Agent stopped via CLI command")
    status_tracker.save()
    console.print("[bold yellow]✓ Signaled Autonomous GitHub Agent to stop.[/bold yellow]")


async def cmd_start(dry_run: Optional[bool] = None, web_port: int = 3000):
    """Start continuous autonomous loop with graceful shutdown."""
    if dry_run is not None:
        config.dry_run = dry_run

    orchestrator = AutonomousOrchestrator(config, web_port=web_port)

    # Register OS signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, orchestrator.stop)
        except NotImplementedError:
            pass

    await orchestrator.start()


def _resolve_dry_run(args) -> Optional[bool]:
    """Resolve --dry-run/--live flags (live wins if both are passed)."""
    if getattr(args, "live", False):
        return False
    if getattr(args, "dry_run", False):
        return True
    return None


def main():
    parser = argparse.ArgumentParser(description="Autonomous GitHub Agent for Google Antigravity")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")

    subparsers = parser.add_subparsers(dest="command", help="Agent command to execute")

    # Start command
    start_parser = subparsers.add_parser("start", help="Start continuous autonomous agent loop")
    start_parser.add_argument("--dry-run", action="store_true", help="Run in dry-run mode (no live writes)")
    start_parser.add_argument("--live", action="store_true", help="Run in live mode (submits PRs and replies)")
    start_parser.add_argument("--port", type=int, default=3000, help="Port for live web dashboard (default: 3000)")

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
    inbox_parser.add_argument("--live", action="store_true", help="Submit real replies")

    # Hunt command
    hunt_parser = subparsers.add_parser("hunt", help="Search top-tier repos for open issues")
    hunt_parser.add_argument("--limit", type=int, default=5, help="Number of issues to return")

    # Solve command
    solve_parser = subparsers.add_parser("solve", help="Hunt and autonomously solve issues")
    solve_parser.add_argument("--auto", dest="auto", action=argparse.BooleanOptionalAction, default=True, help="Autonomously solve issues without prompting (--no-auto to disable)")
    solve_parser.add_argument("--limit", type=int, default=1, help="Number of issues to solve")
    solve_parser.add_argument("--dry-run", action="store_true", help="Simulate PR creation only")
    solve_parser.add_argument("--live", action="store_true", help="Submit real PRs")

    # Stop command
    subparsers.add_parser("stop", help="Signal autonomous agent to stop")

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.command == "status":
        asyncio.run(cmd_status())
    elif args.command == "tasks":
        cmd_tasks()
    elif args.command == "web":
        cmd_web(port=args.port)
    elif args.command == "inbox":
        asyncio.run(cmd_inbox(dry_run=_resolve_dry_run(args)))
    elif args.command == "hunt":
        asyncio.run(cmd_hunt(limit=max(1, min(args.limit, 50))))
    elif args.command == "solve":
        asyncio.run(cmd_solve(auto=args.auto, limit=max(1, min(args.limit, 10)), dry_run=_resolve_dry_run(args)))
    elif args.command == "stop":
        cmd_stop()
    elif args.command == "start" or args.command is None:
        asyncio.run(cmd_start(dry_run=_resolve_dry_run(args), web_port=getattr(args, "port", 3000)))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
