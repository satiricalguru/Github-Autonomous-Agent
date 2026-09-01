"""Multi-task async orchestrator for concurrent GitHub Agent workflows."""

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
    from .pr_solver import PRSolver
    from .safety_guardrails import SafetyGuardrails
    from .status_tracker import status_tracker
    from .web_dashboard import start_web_server
except ImportError:
    from config import AgentConfig, config
    from github_client import GitHubClient
    from inbox_manager import InboxManager
    from issue_hunter import IssueHunter
    from pr_solver import PRSolver
    from safety_guardrails import SafetyGuardrails
    from status_tracker import status_tracker
    from web_dashboard import start_web_server

logger = logging.getLogger("github_agent.orchestrator")
console = Console()


class AutonomousOrchestrator:
    """Coordinates concurrent Inbox triage and Issue Hunter/Solver loops."""

    def __init__(self, agent_config: Optional[AgentConfig] = None):
        self.config = agent_config or config
        self.client = GitHubClient(self.config)
        self.safety = SafetyGuardrails(self.config)
        self.inbox = InboxManager(self.client, self.safety, agent_config=self.config)
        self.hunter = IssueHunter(self.client, self.safety, agent_config=self.config)
        self.solver = PRSolver(self.client, self.safety, agent_config=self.config)

        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._stop_event = asyncio.Event()

    async def _inbox_loop(self):
        """Continuous inbox polling loop."""
        logger.info(f"Started Inbox Worker (polling every {self.config.inbox_poll_interval}s)")
        while self._running and not self._stop_event.is_set():
            try:
                # Check rate limits
                rate = await self.client.get_rate_limit()
                remaining = rate.get("remaining", 5000)
                is_safe, msg = self.safety.check_rate_limit(remaining)
                if not is_safe:
                    logger.warning(f"Rate limit check: {msg}")
                    await asyncio.sleep(60)
                    continue

                results = await self.inbox.process_inbox()
                if results:
                    console.print(f"[bold green]✓ Handled {len(results)} notification(s)[/bold green]")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in inbox worker: {e}", exc_info=True)

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self.config.inbox_poll_interval
                )
            except asyncio.TimeoutError:
                pass

    async def _issue_solver_loop(self):
        """Continuous top-tier repo issue hunter & solver loop."""
        logger.info(
            f"Started Issue Hunter/Solver Worker (polling every {self.config.issue_hunt_interval}s)"
        )
        while self._running and not self._stop_event.is_set():
            try:
                # Check daily PR limit
                can_pr, reason = self.safety.can_submit_pr()
                if not can_pr:
                    logger.info(f"Issue solver paused: {reason}")
                    await asyncio.sleep(300)
                    continue

                candidates = await self.hunter.hunt_issues(limit=3)
                logger.info(f"Hunter discovered {len(candidates)} actionable candidate(s).")

                for candidate in candidates:
                    if self._stop_event.is_set():
                        break
                    console.print(
                        f"[cyan]Found Issue:[/cyan] {candidate['repo']}#{candidate['issue_number']} - {candidate['title']} (Score: {candidate['score']:.2f})"
                    )
                    res = await self.solver.solve_issue(candidate)
                    if res:
                        console.print(
                            f"[bold green]✓ Created PR:[/bold green] {res['pr_url']} (Dry Run: {res['dry_run']})"
                        )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in issue solver worker: {e}", exc_info=True)

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self.config.issue_hunt_interval
                )
            except asyncio.TimeoutError:
                pass

    async def start(self):
        """Start all concurrent workers."""
        self._running = True
        self._stop_event.clear()
        status_tracker.overall_status = "RUNNING"
        status_tracker.log_event("SYSTEM", f"Agent initialized with active model: {self.config.model_name}")

        console.print("[bold cyan]══════════════════════════════════════════════════[/bold cyan]")
        console.print("[bold green] 🚀 Autonomous GitHub Agent Initialized & Running [/bold green]")
        console.print(f" • Active AI Model: [bold magenta]{self.config.model_name.upper()}[/bold magenta]")
        console.print(f" • Live Web UI: [bold cyan]http://localhost:3000[/bold cyan]")
        console.print(f" • Mode: {'[yellow]DRY-RUN (Simulated)[/yellow]' if self.config.dry_run else '[bold green]LIVE[/bold green]'}")
        console.print(f" • Account: {self.config.github_username or 'Authenticated User'}")
        console.print(f" • Max Concurrent Tasks: {self.config.max_concurrent_tasks}")
        console.print(f" • Polling Intervals: Inbox={self.config.inbox_poll_interval}s, Issues={self.config.issue_hunt_interval}s")
        console.print("[bold cyan]══════════════════════════════════════════════════[/bold cyan]")

        # Launch live web UI server
        start_web_server(port=3000)

        # Launch concurrent async workers
        self._tasks = [
            asyncio.create_task(self._inbox_loop(), name="inbox_worker"),
            asyncio.create_task(self._issue_solver_loop(), name="issue_solver_worker"),
        ]

        try:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        finally:
            status_tracker.overall_status = "STOPPED"
            status_tracker.log_event("SYSTEM", "Agent stopped gracefully")
            await self.client.close()

    def stop(self):
        """Signal all workers to terminate gracefully."""
        logger.info("Stopping Autonomous GitHub Agent...")
        self._running = False
        self._stop_event.set()
        status_tracker.overall_status = "STOPPING"
        for task in self._tasks:
            task.cancel()
