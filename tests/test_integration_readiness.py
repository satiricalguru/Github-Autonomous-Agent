"""Exercise owned execution, authenticated controls, isolation, and real repair evidence."""
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.ai_engine import AIEngine
from src.orchestrator import AutonomousOrchestrator
from src.process import run_process, ProcessOutputLimit
from src.pr_solver import PRSolver
from src.runtime import RunLease, send_control
from src.safety_guardrails import StateStore
from src.sandbox import RepositorySandbox
from src.status_tracker import StatusTracker
from src.task_tracker import TaskTracker
from src.web_dashboard import start_web_server


async def until(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(0.01)
    await asyncio.wait_for(wait(), 5)


@pytest.mark.asyncio
async def test_controller_repeats_triggers_pauses_and_cross_process_stops(cfg):
    agent = AutonomousOrchestrator(cfg, web_port=0)
    agent.client.get_rate_limit = AsyncMock(return_value={"remaining": 5000, "limit": 5000})
    agent.inbox.process_inbox = AsyncMock(return_value=[])
    agent.hunter.hunt_issues = AsyncMock(return_value=[])
    running = asyncio.create_task(agent.start())
    try:
        await until(lambda: agent.inbox.process_inbox.await_count == 1)
        with pytest.raises(RuntimeError):
            RunLease(cfg.scratch_dir).acquire()
        for count in (2, 3):
            await agent.control("trigger-inbox")
            await until(lambda: agent.inbox.process_inbox.await_count == count)
        await agent.control("pause-resume")
        assert agent.paused
        with pytest.raises(RuntimeError):
            await agent.control("trigger-inbox")
        # Work admission also remains closed when an earlier quota read finishes.
        await agent._run_cycle(agent.inbox.process_inbox)
        assert agent.inbox.process_inbox.await_count == 3
        await agent.control("pause-resume")
        await agent.control("trigger-inbox")
        await until(lambda: agent.inbox.process_inbox.await_count == 4)
        result = await asyncio.to_thread(send_control, cfg.scratch_dir, "stop")
        assert result["overall_status"] == "STOPPING"
        await asyncio.wait_for(running, 5)
        assert not agent._running and not agent._cycles
        assert not (cfg.scratch_dir / "runtime.json").exists()
        with RunLease(cfg.scratch_dir):
            pass
    finally:
        if not running.done():
            agent.stop()
        await asyncio.gather(running, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancel_reaps_owned_child(tmp_path):
    pidfile = tmp_path / "pid"
    script = f"import os,time,pathlib;pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid()));time.sleep(60)"
    running = asyncio.create_task(run_process([sys.executable, "-c", script], timeout=90))
    await until(pidfile.exists)
    pid = int(pidfile.read_text())
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.asyncio
async def test_excessive_output_terminates_process():
    with pytest.raises(ProcessOutputLimit):
        await run_process([sys.executable, "-c", "import sys,time;sys.stdout.write('x'*100000);sys.stdout.flush();time.sleep(60)"], max_output_bytes=4096)


@pytest.mark.asyncio
async def test_pause_waits_for_real_process_termination(cfg, tmp_path):
    agent = AutonomousOrchestrator(cfg, web_port=0)
    agent._running = True
    pidfile = tmp_path / "pause-pid"
    script = f"import os,time,pathlib;pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid()));time.sleep(60)"
    async def operation():
        await run_process([sys.executable, "-c", script], timeout=90)
    cycle = asyncio.create_task(agent._run_cycle(operation))
    await until(pidfile.exists)
    pid = int(pidfile.read_text())
    await agent.pause()
    await cycle
    assert agent.paused and not agent._cycles
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.asyncio
async def test_settings_persistence_failure_rolls_back_and_resumes(cfg):
    agent = AutonomousOrchestrator(cfg, web_port=0)
    agent._running = True
    with patch.object(type(cfg), "save_settings", side_effect=OSError("fixture disk failure")):
        with pytest.raises(OSError):
            await agent.control("settings", {"dry_run": False})
    assert cfg.dry_run and not agent.paused


@pytest.mark.asyncio
async def test_solver_concurrency_is_bounded(cfg):
    cfg.max_concurrent_tasks = 2
    agent = AutonomousOrchestrator(cfg, web_port=0)
    agent.hunter.hunt_issues = AsyncMock(return_value=[{"id": i} for i in range(5)])
    active = maximum = finished = 0
    async def solve(candidate):
        nonlocal active, maximum, finished
        active += 1
        maximum = max(maximum, active)
        try:
            await asyncio.sleep(.03)
            finished += 1
        finally:
            active -= 1
    agent.solver.solve_issue = AsyncMock(side_effect=solve)
    await agent._hunt_cycle()
    assert maximum == 2 and finished == 5 and active == 0
    agent.solver.solve_issue.reset_mock()
    await agent._hunt_cycle(hunt_only=True)
    agent.solver.solve_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_quota_blocks_workers(cfg):
    agent = AutonomousOrchestrator(cfg, web_port=0)
    agent.client.get_rate_limit = AsyncMock(side_effect=RuntimeError("unavailable"))
    assert not await agent._quota_ready(search=True)
    from src.status_tracker import status_tracker
    assert status_tracker.rate_limit_remaining is None


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "darwin", reason="Native macOS isolation check")
async def test_sandbox_blocks_network_secrets_external_writes_and_git(cfg, tmp_path, monkeypatch):
    repo = tmp_path / "checkout"
    repo.mkdir()
    (repo / ".git").mkdir()
    secret = tmp_path / "host-secret"
    secret.write_text("must remain private")
    outside = tmp_path / "outside-write"
    monkeypatch.setenv("GITHUB_TOKEN", "secret-not-for-tests")
    code = f'''
import os,json,socket,pathlib
results={{"credential_absent": "GITHUB_TOKEN" not in os.environ}}
try:
 os.kill({os.getpid()},0)
 results["host_signal"]=False
except PermissionError: results["host_signal"]=True
for name,path,mode in [("secret", {str(secret)!r}, "read"), ("outside", {str(outside)!r}, "write"), ("git", ".git/config", "write")]:
 try:
  p=pathlib.Path(path)
  p.read_text() if mode=="read" else p.write_text("bad")
  results[name]=False
 except PermissionError: results[name]=True
try:
 socket.create_connection(("127.0.0.1",80),timeout=.5)
 results["network"]=False
except PermissionError: results["network"]=True
pathlib.Path("allowed").write_text("ok")
print(json.dumps(results))
'''
    result = await RepositorySandbox(cfg).run([sys.executable, "-c", code], repo)
    assert result.returncode == 0, result.stderr
    assert all(json.loads(result.stdout).values())
    assert (repo / "allowed").read_text() == "ok"
    assert not outside.exists()


@pytest.mark.asyncio
async def test_settings_are_typed_atomic_and_persistent(cfg):
    server = start_web_server(0, agent_config=cfg)
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{server.server_address[1]}") as client:
            headers = {"Authorization": f"Bearer {server.control_token}"}
            r = await client.post("/api/settings", json={"dry_run": False, "inbox_poll_interval": -1}, headers=headers)
            assert r.status_code == 400 and cfg.dry_run
            r = await client.post("/api/settings", json={"dry_run": "false"}, headers=headers)
            assert r.status_code == 400 and cfg.dry_run
            r = await client.post("/api/settings", json={"inbox_poll_interval": 15}, headers=headers)
            assert r.status_code == 200
            cfg.inbox_poll_interval = 60
            cfg.load_settings()
            assert cfg.inbox_poll_interval == 15
            r = await client.post("/api/pause-resume", json={}, headers=headers)
            assert r.status_code == 409
            r = await client.get("/api/status")
            assert r.json()["status"] not in ("RUNNING", "PAUSED")
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()


def test_atomic_submission_reservations(tmp_path):
    a, b = StateStore(tmp_path / "state.json"), StateStore(tmp_path / "state.json")
    assert a.claim_issue("one", 1)
    assert not b.claim_issue("two", 1)
    assert not b.claim_issue("one", 5)
    a.release_issue("one")
    assert b.claim_issue("two", 1)


def test_orphan_claim_reset_preserves_submission_cap(tmp_path):
    state = StateStore(tmp_path / "state.json")
    assert state.claim_issue("pending", 3)
    state.record_pr_submission("fixture/repo", "completed", "https://github.com/fixture/repo/pull/1")
    state.clear_orphaned_claims()
    assert not state.claim_issue("pending", 1)
    assert state.claim_issue("pending", 2)


@pytest.mark.asyncio
async def test_antigravity_adapter_checks_completion_and_model(cfg):
    cfg.ai_provider = "antigravity"
    cfg.model_name = "claude-sonnet-4.6"
    engine = AIEngine(cfg)
    response = subprocess.CompletedProcess([], 0, '{"status":"SUCCESS","response":"{\\"ok\\":true}"}', "")
    with patch("src.ai_engine.shutil.which", return_value="/fixture/agy"), patch("src.ai_engine.run_process", AsyncMock(return_value=response)) as run:
        assert json.loads(await engine._call_model("fixture"))["ok"]
        args = run.await_args.args[0]
        assert args[args.index("--model") + 1] == "claude-sonnet-4-6"
        assert "--sandbox" in args and "--disable-slash-commands" in args
        assert engine.get_health()["state"] == "ONLINE"
        response.stdout = '{"status":"ERROR","response":"fake success"}'
        assert await engine._call_model("fixture") is None
        assert engine.get_health()["state"] == "DEGRADED"


@pytest.mark.asyncio
async def test_low_confidence_review_requires_attention(cfg):
    engine = AIEngine(cfg)
    engine._call_gemini = AsyncMock(return_value=json.dumps({"should_respond": False, "confidence": .1, "suggested_reply": ""}))
    evaluation = await engine.evaluate_notification("fixture/repo", "Needs investigation", "mention", "Issue", [], body="Important reproduction")
    assert evaluation["needs_attention"]
    assert "Important reproduction" in engine._call_gemini.await_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("correct_fix,live_push_failure", [(True, False), (False, False), (True, True)])
async def test_real_red_green_repair_and_dry_run_history(cfg, tmp_path, correct_fix, live_push_failure):
    fixture = tmp_path / "origin"
    fixture.mkdir()
    (fixture / "bug.py").write_text("def add(a, b):\n    return a - b\n")
    (fixture / "test_baseline.py").write_text("from bug import add\ndef test_zero():\n    assert add(0, 0) == 0\n")
    for args in (["init", "-b", "main"], ["config", "user.name", "Fixture"], ["config", "user.email", "fixture@example.test"], ["add", "."], ["commit", "-m", "fixture"]):
        subprocess.run(["git", *args], cwd=fixture, check=True, capture_output=True)
    # Linux CI permits only this explicitly trusted dry-run fixture on the host.
    cfg.allow_host_tests = True
    cfg.dry_run = not live_push_failure
    client = MagicMock()
    client.check_issue_eligibility = AsyncMock(return_value=(True, "ok"))
    client.get_repository = AsyncMock(return_value={"default_branch": "main"})
    client.get_rate_limit = AsyncMock(return_value={"remaining": 5000, "limit": 5000})
    client.ensure_fork = AsyncMock(return_value={"owner": {"login": "fixture-user"}})
    client.create_pull_request = AsyncMock(return_value={"html_url": "https://github.com/fixture/repo/pull/mock-dry-run"})
    ai = MagicMock()
    ai.generate_code_patch = AsyncMock(return_value={"can_fix": True, "confidence": .95,
        "target_file": "bug.py", "search_content": "return a - b", "replacement_content": "return a + b" if correct_fix else "return a * b",
        "regression_tests": [{"target_file": "test_regression.py", "file_content": "from bug import add\ndef test_add():\n    assert add(1, 2) == 3\n"}]})
    ai.generate_pr_metadata = AsyncMock(return_value={"title": "fix: addition", "body": "Correct the addition operator."})
    tasks = TaskTracker(cfg)
    solver = PRSolver(client=client, ai=ai, agent_config=cfg, tasks=tasks, status=StatusTracker(cfg))
    if live_push_failure:
        # The local fixture is trusted; production GitHub writes are all mocked.
        solver.sandbox = RepositorySandbox(cfg.model_copy(update={"dry_run": True}))
    original_git = solver._git
    async def local_git(repository, *args, **kwargs):
        if args[0] == "push":
            raise RuntimeError("fixture push failure")
        if args[0] == "clone":
            args = ("clone", "--branch", "main", str(fixture), ".")
        return await original_git(repository, *args, **kwargs)
    solver._git = local_git
    result = await solver.solve_issue({"repo": "fixture/repo", "issue_number": 1, "url": "https://github.com/fixture/repo/issues/1", "title": "Addition returns subtraction", "body": "add(1,2) should return 3"})
    expected_success = correct_fix and not live_push_failure
    assert bool(result) is expected_success, tasks.get_api_tasks()
    assert client.create_pull_request.await_count == int(expected_success)
    assert not solver.safety.state.is_issue_handled("https://github.com/fixture/repo/issues/1")
    assert solver.safety.state.get_recent_pr_count() == 0
    assert "return a - b" in ai.generate_code_patch.await_args.kwargs["source_context"]
    if expected_success:
        assert "FAILED" in result["test_output"] and "2 passed" in result["test_output"]
        assert client.create_pull_request.await_args.kwargs["draft"] is True
    else:
        assert tasks.get_api_tasks()[0]["status"] == "failed"
    if live_push_failure:
        assert "push failure" in tasks.get_api_tasks()[0]["error"]
        assert solver.safety.state.claim_issue("https://github.com/fixture/repo/issues/1", 1)
        solver.safety.state.release_issue("https://github.com/fixture/repo/issues/1")
