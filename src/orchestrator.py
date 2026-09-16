"""Continuous workers controlled by their owning asyncio process."""
import asyncio
import logging
import time
from typing import Optional

from .ai_engine import AIEngine
from .config import AgentConfig, config, detect_active_ai_model
from .github_client import GitHubClient
from .inbox_manager import InboxManager
from .issue_hunter import IssueHunter
from .pr_solver import PRSolver
from .safety_guardrails import SafetyGuardrails
from .status_tracker import status_tracker
from .task_tracker import task_tracker
from .web_dashboard import start_web_server
from .runtime import RunLease, write_runtime

logger = logging.getLogger("github_agent.orchestrator")


class AutonomousOrchestrator:
    def __init__(self, agent_config: Optional[AgentConfig] = None, web_port=3000):
        self.config = agent_config or config
        self.web_port = web_port
        self.client = GitHubClient(self.config)
        self.safety = SafetyGuardrails(self.config)
        self.ai = AIEngine(self.config)
        self.inbox = InboxManager(self.client, self.safety, self.ai, self.config)
        self.hunter = IssueHunter(self.client, self.safety, self.ai, self.config)
        self.solver = PRSolver(self.client, self.safety, self.ai, self.config)
        self._running = False
        self._tasks = []
        self._cycles = set()
        self._stop_event = asyncio.Event()
        self._resume_event = asyncio.Event()
        self._resume_event.set()
        self._wake = {"inbox": asyncio.Event(), "hunt": asyncio.Event()}
        self._hunt_only = False
        self._web_server = None
        self._lease = RunLease(self.config.scratch_dir)
        self._control_lock = asyncio.Lock()

    @property
    def paused(self):
        return not self._resume_event.is_set()

    async def _wait_or_stop(self, timeout, worker=None):
        waits = [asyncio.create_task(self._stop_event.wait())]
        if worker:
            waits.append(asyncio.create_task(self._wake[worker].wait()))
        try:
            await asyncio.wait(waits, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in waits:
                task.cancel()
            await asyncio.gather(*waits, return_exceptions=True)

    def _sync_dynamic_model(self):
        if self.config.sync_ide_model:
            self.config.model_name = detect_active_ai_model(prefer_ide=True)

    async def _quota_ready(self, search=False):
        try:
            rate = await self.client.get_rate_limit()
            status_tracker.set_rate_limit(rate["remaining"], rate["limit"])
            safe, reason = self.safety.check_rate_limit(rate["remaining"])
            resources = rate.get("resources", {})
            if search and resources:
                bucket = resources.get("search", {})
                safe = safe and bucket.get("remaining", 0) > 0
            if not safe:
                raise RuntimeError(reason if not search else "GitHub quota is below reserve")
            return True
        except Exception as error:
            status_tracker.set_rate_limit(None, None)
            status_tracker.log_event("ERROR", str(error))
            return False

    async def _run_cycle(self, operation):
        # Quota reads can finish after pause was acknowledged. Do not admit work.
        if not self._running or self.paused or self._stop_event.is_set():
            return None
        task = asyncio.create_task(operation())
        self._cycles.add(task)
        try:
            return await task
        except asyncio.CancelledError:
            if self._stop_event.is_set():
                raise
            return None
        finally:
            self._cycles.discard(task)

    async def _inbox_loop(self):
        while self._running:
            await self._resume_event.wait()
            if self._stop_event.is_set():
                return
            self._wake["inbox"].clear()
            try:
                self._sync_dynamic_model()
                if await self._quota_ready():
                    status_tracker.iterations["inbox"] += 1
                    await self._run_cycle(self.inbox.process_inbox)
                else:
                    status_tracker.update_inbox("ERROR", "GitHub authentication or quota unavailable")
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.exception("Inbox cycle failed")
                status_tracker.update_inbox("ERROR", str(error))
            await self._wait_or_stop(self.config.inbox_poll_interval, "inbox")

    async def _hunt_cycle(self, hunt_only=False):
        candidates = await self.hunter.hunt_issues(limit=self.config.max_concurrent_tasks)
        if hunt_only:
            status_tracker.log_event("HUNT", f"Discovered {len(candidates)} eligible issues")
            return
        semaphore = asyncio.Semaphore(self.config.max_concurrent_tasks)
        async def solve(candidate):
            async with semaphore:
                return await self.solver.solve_issue(candidate)
        jobs = [asyncio.create_task(solve(candidate)) for candidate in candidates]
        try:
            await asyncio.gather(*jobs)
        finally:
            for job in jobs:
                if not job.done():
                    job.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)
        status_tracker.update_hunter("IDLE", "Issue cycle completed")

    async def _issue_solver_loop(self):
        while self._running:
            await self._resume_event.wait()
            if self._stop_event.is_set():
                return
            self._wake["hunt"].clear()
            hunt_only = self._hunt_only
            self._hunt_only = False
            try:
                self._sync_dynamic_model()
                allowed, _ = self.safety.can_submit_pr()
                if (self.config.dry_run or allowed) and await self._quota_ready(search=True):
                    status_tracker.iterations["hunter"] += 1
                    await self._run_cycle(lambda: self._hunt_cycle(hunt_only))
                else:
                    status_tracker.update_hunter("BLOCKED", "Submission cap or GitHub quota unavailable")
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.exception("Issue cycle failed")
                status_tracker.update_hunter("ERROR", str(error))
            await self._wait_or_stop(self.config.issue_hunt_interval, "hunt")

    async def _heartbeat(self):
        while self._running:
            status_tracker.heartbeat_at = time.time()
            status_tracker.ai_health = self.ai.get_health()
            status_tracker.save()
            await self._wait_or_stop(2)

    async def control(self, action, updates=None):
        async with self._control_lock:
            if not self._running:
                raise RuntimeError("Agent is stopped")
            if action == "stop":
                self.stop()
                return {"status": "ok", "overall_status": "STOPPING"}
            if action == "pause-resume":
                if self.paused:
                    self._resume_event.set()
                    for event in self._wake.values():
                        event.set()
                    status_tracker.overall_status = "RUNNING"
                else:
                    await self.pause()
                status_tracker.save()
                return {"status": "ok", "overall_status": status_tracker.overall_status}
            if action.startswith("trigger-"):
                if self.paused:
                    raise RuntimeError("Resume the agent before triggering work")
                kind = action.removeprefix("trigger-")
                if kind == "inbox":
                    self._wake["inbox"].set()
                elif kind in ("hunt", "solve"):
                    if self._wake["hunt"].is_set():
                        raise RuntimeError("An issue trigger is already queued")
                    self._hunt_only = kind == "hunt"
                    self._wake["hunt"].set()
                else:
                    raise ValueError("Unknown worker")
                return {"status": "ok", "message": "Work queued"}
            if action == "settings":
                was_paused = self.paused
                await self.pause()
                previous = self.config.public_settings()
                try:
                    self.config.update(**updates)
                    self.config.save_settings()
                except Exception:
                    self.config.update(**previous)
                    raise
                finally:
                    if not was_paused:
                        self._resume_event.set()
                        for event in self._wake.values():
                            event.set()
                        status_tracker.overall_status = "RUNNING"
                status_tracker.save()
                return {"status": "ok", "message": "Settings applied"}
            raise ValueError("Unknown control action")

    async def pause(self):
        self._resume_event.clear()
        cycles = list(self._cycles)
        for task in cycles:
            task.cancel()
        if cycles:
            await asyncio.gather(*cycles, return_exceptions=True)
        status_tracker.overall_status = "PAUSED"
        status_tracker.log_event("SYSTEM", "Execution paused; active work cancelled")

    async def start(self):
        self._lease.acquire()
        try:
            status_tracker.rebind(self.config)
            task_tracker.rebind(self.config)
            task_tracker.cancel_orphaned_tasks()
            self.safety.state.clear_orphaned_claims()
            self._running = True
            self._stop_event.clear()
            status_tracker.overall_status = "RUNNING"
            status_tracker.started_at = time.time()
            status_tracker.iterations = {"inbox": 0, "hunter": 0}
            status_tracker.heartbeat_at = time.time()
            self.loop = asyncio.get_running_loop()
            self._web_server = start_web_server(self.web_port, agent_config=self.config, controller=self)
            if self._web_server is None:
                raise RuntimeError("Control dashboard failed to bind; agent not started")
            write_runtime(self.config.scratch_dir, self._web_server.server_address[1], self._web_server.control_token)
            status_tracker.log_event("SYSTEM", "Continuous agent started")
            self._tasks = [asyncio.create_task(self._inbox_loop()), asyncio.create_task(self._issue_solver_loop()), asyncio.create_task(self._heartbeat())]
            # A worker exiting unexpectedly must stop the remaining workers.
            done, _ = await asyncio.wait(self._tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if not task.cancelled() and task.exception():
                    raise task.exception()
        finally:
            self.stop()
            await asyncio.gather(*self._tasks, return_exceptions=True)
            await asyncio.gather(*self._cycles, return_exceptions=True)
            await self.client.close()
            status_tracker.overall_status = "STOPPED"
            status_tracker.heartbeat_at = None
            status_tracker.update_inbox("STOPPED", "Agent stopped")
            status_tracker.update_hunter("STOPPED", "Agent stopped")
            status_tracker.log_event("SYSTEM", "Agent stopped; owned work terminated")
            if self._web_server:
                await asyncio.to_thread(self._web_server.shutdown)
                self._web_server.server_close()
            (self.config.scratch_dir / "runtime.json").unlink(missing_ok=True)
            self._lease.close()

    def stop(self):
        if self._stop_event.is_set():
            return
        self._running = False
        self._stop_event.set()
        self._resume_event.set()
        status_tracker.overall_status = "STOPPING"
        # Cancelling the awaiting worker propagates once to its active cycle.
        # Avoid a second cancellation interrupting child-process cleanup.
        for task in self._tasks or list(self._cycles):
            if task is not asyncio.current_task() and not task.done():
                task.cancel()
