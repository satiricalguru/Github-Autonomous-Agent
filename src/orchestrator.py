"""Multi-task async orchestrator for concurrent GitHub Agent workflows."""

import asyncio
import logging
from typing import TYPE_CHECKING, Optional
from rich.console import Console

if TYPE_CHECKING:
    from .config import AgentConfig, config
    from .github_client import GitHubClient
    from .inbox_manager import InboxManager
    from .issue_hunter import IssueHunter
    from .pr_solver import PRSolver
    from .safety_guardrails import SafetyGuardrails
    from .status_tracker import status_tracker
    from .web_dashboard import start_web_server
else:
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

    def __init__(self, agent_config: Optional[AgentConfig] = None, web_port: int = 3000):
        self.config = agent_config or config
        self.web_port = web_port
        self.client = GitHubClient(self.config)
        self.safety = SafetyGuardrails(self.config)
        self.inbox = InboxManager(self.client, self.safety, agent_config=self.config)
        self.hunter = IssueHunter(self.client, self.safety, agent_config=self.config)
        self.solver = PRSolver(self.client, self.safety, agent_config=self.config)

        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._stop_event = asyncio.Event()
        self._web_server = None

    async def _wait_or_stop(self, timeout: float):
        """Sleep interruptibly so shutdown is prompt even during long pauses."""
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass

    def _sync_dynamic_model(self):
        """Dynamically synchronize AI model name from Antigravity IDE."""
        try:
            try:
                from .config import detect_active_ai_model
            except ImportError:
                from config import detect_active_ai_model
            new_model = detect_active_ai_model()
            if new_model and new_model != self.config.model_name:
                self.config.model_name = new_model
                status_tracker.active_model = new_model
                status_tracker.model_display_name = self.config.model_display_name
                status_tracker.save()
                logger.info(f"Dynamically updated active AI model to: {new_model} ({self.config.model_display_name})")
        except Exception:
            pass

    async def _inbox_loop(self):
        """Continuous inbox polling loop."""
        logger.info(f"Started Inbox Worker (polling every {self.config.inbox_poll_interval}s)")
        while self._running and not self._stop_event.is_set():
            try:
                self._sync_dynamic_model()
                # Check rate limits
                rate = await self.client.get_rate_limit()
                remaining = rate.get("remaining", 5000)
                limit = rate.get("limit", 5000)
                try:
                    status_tracker.set_rate_limit(int(remaining), int(limit))
                except Exception:
                    pass
                is_safe, msg = self.safety.check_rate_limit(remaining)
                if not is_safe:
                    logger.warning(f"Rate limit check: {msg}")
                    await self._wait_or_stop(60)
                    continue

                results = await self.inbox.process_inbox()
                if results:
                    console.print(f"[bold green]✓ Handled {len(results)} notification(s)[/bold green]")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in inbox worker: {e}", exc_info=True)

            await self._wait_or_stop(self.config.inbox_poll_interval)

    async def _issue_solver_loop(self):
        """Continuous top-tier repo issue hunter & solver loop."""
        logger.info(
            f"Started Issue Hunter/Solver Worker (polling every {self.config.issue_hunt_interval}s)"
        )
        while self._running and not self._stop_event.is_set():
            try:
                self._sync_dynamic_model()
                # Check daily PR limit
                can_pr, reason = self.safety.can_submit_pr()
                if not can_pr:
                    logger.info(f"Issue solver paused: {reason}")
                    await self._wait_or_stop(300)
                    continue

                candidates = await self.hunter.hunt_issues(limit=3)
                logger.info(f"Hunter discovered {len(candidates)} actionable candidate(s).")

                for candidate in candidates:
                    if self._stop_event.is_set():
                        break
                    console.print(
                        f"[cyan]Found Issue:[/cyan] {candidate.get('repo', '?')}#{candidate.get('issue_number', '?')} - {candidate.get('title', '')[:80]} (Score: {candidate.get('score', 0.0):.2f})"
                    )
                    res = await self.solver.solve_issue(candidate)
                    if res:
                        console.print(
                            f"[bold green]✓ Created PR:[/bold green] {res.get('pr_url', '?')} (Dry Run: {res.get('dry_run', False)})"
                        )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in issue solver worker: {e}", exc_info=True)

            await self._wait_or_stop(self.config.issue_hunt_interval)

    async def start(self):
        """Start all concurrent workers."""
        self._running = True
        try:
            self._stop_event.clear()
        except Exception:
            self._stop_event = asyncio.Event()
        status_tracker.overall_status = "RUNNING"
        status_tracker.log_event("SYSTEM", f"Agent initialized with active model: {self.config.model_name}")

        console.print("[bold cyan]══════════════════════════════════════════════════[/bold cyan]")
        console.print("[bold green] 🚀 Autonomous GitHub Agent Initialized & Running [/bold green]")
        console.print(f" • Active AI Model: [bold magenta]{self.config.model_name.upper()}[/bold magenta]")
        console.print(f" • Live Web UI: [bold cyan]http://localhost:{self.web_port}[/bold cyan]")
        console.print(f" • Mode: {'[yellow]DRY-RUN (Simulated)[/yellow]' if self.config.dry_run else '[bold green]LIVE[/bold green]'}")
        console.print(f" • Account: {self.config.github_username or 'Authenticated User'}")
        console.print(f" • Max Concurrent Tasks: {self.config.max_concurrent_tasks}")
        console.print(f" • Polling Intervals: Inbox={self.config.inbox_poll_interval}s, Issues={self.config.issue_hunt_interval}s")
        console.print("[bold cyan]══════════════════════════════════════════════════[/bold cyan]")

        # Launch live web UI server
        try:
            self._web_server = start_web_server(port=self.web_port)
        except Exception as e:
            logger.warning(f"Web dashboard failed to start: {e}")
            self._web_server = None

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
            if self._web_server is not None:
                try:
                    self._web_server.shutdown()
                    self._web_server.server_close()
                except Exception:
                    pass
                self._web_server = None
            await self.client.close()

    def stop(self):
        """Signal all workers to terminate gracefully."""
        logger.info("Stopping Autonomous GitHub Agent...")
        self._running = False
        try:
            self._stop_event.set()
        except Exception:
            pass
        status_tracker.overall_status = "STOPPING"
        for task in self._tasks:
            task.cancel()
