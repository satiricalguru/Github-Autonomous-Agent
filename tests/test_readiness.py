"""Regression coverage for production-readiness audit findings."""
import asyncio
import json
import os
import signal
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.ai_engine import AIEngine
from src.config import AgentConfig
from src.github_client import GitHubClient
from src.pr_solver import PRSolver
from src.safety_guardrails import StateStore
from src.status_tracker import StatusTracker
from src.task_tracker import TaskTracker
from src.web_dashboard import start_web_server


@pytest.fixture
def cfg(tmp_path):
    return AgentConfig(scratch_dir=tmp_path, repos_dir=tmp_path / "repos",
                       state_file=tmp_path / "state.json", github_token=None,
                       github_username="fixture-user", gemini_api_key=None,
                       ai_provider="gemini", dry_run=True)


def test_independent_state_writers_preserve_history(tmp_path):
    path = tmp_path / "state.json"
    a, b = StateStore(path), StateStore(path)
    a.record_pr_submission("fixture/repo", "issue", "pr")
    b.mark_notification_handled("thread")
    loaded = StateStore(path)
    assert len(loaded.submitted_prs) == 1
    assert "thread" in loaded.handled_notifications


def test_worker_status_roundtrip(cfg):
    status = StatusTracker(cfg)
    status.update_inbox("PROCESSING", "fixture")
    assert StatusTracker(cfg).inbox_status["state"] == "PROCESSING"


@pytest.mark.asyncio
async def test_no_test_runner_blocks_submission(cfg, tmp_path):
    success, _ = await PRSolver(agent_config=cfg)._run_repo_tests(tmp_path)
    assert success is False


@pytest.mark.asyncio
async def test_cli_timeout_terminates_child(cfg, tmp_path):
    pidfile = tmp_path / "pid"
    code = f"import os,time,pathlib; pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid())); time.sleep(10)"
    client = GitHubClient(cfg)
    await client._run_command([sys.executable, "-c", code], timeout=0.15)
    pid = int(pidfile.read_text())
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return
    os.kill(pid, signal.SIGTERM)
    pytest.fail("timed-out process is still alive")


@pytest.mark.asyncio
async def test_provider_does_not_route_claude_to_gemini(cfg):
    cfg.model_name = "claude-sonnet-4.6"
    cfg.gemini_api_key = "fixture"
    engine = AIEngine(cfg)
    with patch("src.ai_engine.httpx.AsyncClient") as client:
        client.return_value.__aenter__.return_value.post = AsyncMock(return_value=httpx.Response(404))
        await engine._call_gemini("fixture")
        assert client.return_value.__aenter__.return_value.post.await_count == 0


def test_patch_rejects_symlink(cfg, tmp_path):
    repo = tmp_path / "fixture"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("original")
    (repo / "linked").symlink_to(outside)
    with pytest.raises(ValueError):
        PRSolver(agent_config=cfg)._apply_patch(repo, {"target_file": "linked", "file_content": "bad"})
    assert outside.read_text() == "original"


@pytest.mark.asyncio
async def test_control_rejects_cross_origin_and_unauthenticated(cfg):
    server = start_web_server(0, agent_config=cfg)
    assert server
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{server.server_address[1]}") as client:
            r = await client.post("/api/settings", content=json.dumps({"dry_run": False}),
                                  headers={"Content-Type": "text/plain", "Origin": "https://untrusted.example"})
            assert r.status_code == 403
            assert cfg.dry_run is True
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()


def test_task_api_contract(cfg):
    tasks = TaskTracker(cfg)
    tid = tasks.create_task("SOLVER", "fixture", "fixture/repo")
    tasks.complete_task(tid, details_update={"pr_url": "https://github.com/fixture/repo/pull/1"})
    record = tasks.get_api_tasks()[0]
    assert record["type"] == "pr_solve"
    assert record["target"] == "fixture/repo"
    assert record["status"] == "completed"
    assert record["pr_url"].endswith("/1")
