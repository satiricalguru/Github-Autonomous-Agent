"""Time-based continuous-loop check with transient failures and a separate-process stop."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import AgentConfig
from src.orchestrator import AutonomousOrchestrator
from src.process import run_process
from src.status_tracker import status_tracker


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=30)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.duration < 11:
        parser.error("Use at least 11 seconds for three scheduled cycles")
    with tempfile.TemporaryDirectory(prefix="github-agent-soak-") as directory:
        root = Path(directory)
        cfg = AgentConfig(scratch_dir=root, github_token=None, github_username="fixture-user",
                          ai_provider="gemini", gemini_api_key=None, inbox_poll_interval=5, issue_hunt_interval=5)
        agent = AutonomousOrchestrator(cfg, web_port=0)
        agent.client.get_rate_limit = AsyncMock(return_value={"remaining": 5000, "limit": 5000})
        counts = {"inbox": 0, "hunter": 0}
        async def work(kind):
            counts[kind] += 1
            if counts[kind] == 2:
                raise RuntimeError("Injected transient fixture failure")
            return []
        agent.inbox.process_inbox = AsyncMock(side_effect=lambda: work("inbox"))
        agent.hunter.hunt_issues = AsyncMock(side_effect=lambda **kw: work("hunter"))
        # AsyncMock does not automatically await a coroutine returned by a sync side effect.
        async def inbox(): return await work("inbox")
        async def hunt(**kw): return await work("hunter")
        agent.inbox.process_inbox.side_effect = inbox
        agent.hunter.hunt_issues.side_effect = hunt
        task = asyncio.create_task(agent.start())
        start = time.monotonic()
        try:
            await asyncio.sleep(args.duration)
            await agent.control("pause-resume")
            frozen = dict(counts)
            await asyncio.sleep(.1)
            assert counts == frozen and agent.paused
            await agent.control("pause-resume")
            env = dict(os.environ, SCRATCH_DIR=str(root), GITHUB_AGENT_NO_GH="true", GITHUB_TOKEN="", AI_PROVIDER="gemini", GEMINI_API_KEY="")
            stop = await run_process([sys.executable, "-m", "src.cli", "stop"], env=env, timeout=15)
            assert stop.returncode == 0 and "STOPPING" in stop.stdout
            await asyncio.wait_for(task, 5)
            result = {"duration_seconds": round(time.monotonic() - start, 2), "iterations": counts,
                      "transient_failure_recovered": all(count >= 3 for count in counts.values()),
                      "pause_prevented_new_work": True, "separate_process_stop": True,
                      "final_status": status_tracker.overall_status, "owned_cycles_remaining": len(agent._cycles)}
            assert result["transient_failure_recovered"] and result["final_status"] == "STOPPED"
            if args.output: args.output.write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result, indent=2))
        finally:
            if not task.done(): agent.stop()
            await asyncio.gather(task, return_exceptions=True)

asyncio.run(main())
