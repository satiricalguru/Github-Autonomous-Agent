"""Read-only production audit: local fixtures, mocked providers, temporary state.

Run from the repository root: python3 docs/audits/2026-09-16/probe_audit.py
Results describe observed behavior; they are not a passing regression suite.
"""
import asyncio
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix="github-agent-audit-")
TMP = Path(TEMP.name)
os.environ.update(SCRATCH_DIR=str(TMP / "scratch"), GITHUB_AGENT_NO_GH="true",
                  AI_PROVIDER="gemini", GEMINI_API_KEY="", GITHUB_TOKEN="", GITHUB_USERNAME="audit-user",
                  MODEL_NAME="gemini-3.8-flash", DRY_RUN="true")

import httpx
from src.config import config
from src.ai_engine import AIEngine
from src.github_client import GitHubClient
from src.orchestrator import AutonomousOrchestrator
from src.pr_solver import PRSolver
from src.status_tracker import status_tracker
from src.task_tracker import task_tracker
from src.web_dashboard import start_web_server
from src import cli

results = {}


async def backend_probes():
    server = start_web_server(0)
    assert server is not None
    base = f"http://127.0.0.1:{server.server_address[1]}"
    async with httpx.AsyncClient(base_url=base) as http:
        tid = task_tracker.create_task("SOLVER", "Fixture task", "fixture/repo")
        task_tracker.complete_task(tid, details_update={"pr_url": "https://github.com/fixture/repo/pull/1"})
        status_tracker.update_inbox("PROCESSING", "Fixture processing")
        status_tracker.log_event("SYSTEM", "audit-visible-event")
        status_tracker._load()
        fresh = type(status_tracker)(config)
        snapshot = (await http.get("/api/status")).json()
        results["telemetry"] = {"task": snapshot["tasks"][0], "metrics": snapshot["metrics"],
                                "recent_logs": snapshot["recent_logs"],
                                "fresh_tracker_inbox_state": fresh.inbox_status["state"]}

        orch = AutonomousOrchestrator(config, web_port=0)
        orch._running = True
        orch.client.get_rate_limit = AsyncMock(return_value={"remaining": 5000, "limit": 5000})
        calls = []
        async def inbox():
            calls.append(time.monotonic())
            if len(calls) >= 5:
                orch.stop()
            return []
        orch.inbox.process_inbox = inbox
        async def short_wait(_):
            await asyncio.sleep(0.015)
        orch._wait_or_stop = short_wait
        config.inbox_poll_interval = 60
        status_tracker.overall_status = "RUNNING"
        worker = asyncio.create_task(orch._inbox_loop())
        while len(calls) < 1:
            await asyncio.sleep(0.001)
        pause = (await http.post("/api/pause-resume")).json()
        before = len(calls)
        await asyncio.sleep(0.035)
        after_pause = len(calls)
        cli.cmd_stop()
        before_stop = len(calls)
        await worker
        results["control"] = {"pause_response": pause, "calls_after_pause": after_pause - before,
                              "calls_after_cli_stop": len(calls) - before_stop,
                              "total_iterations": len(calls)}
        trigger = {}
        for name in ("inbox", "hunt", "solve"):
            trigger[name] = (await http.post(f"/api/trigger-{name}")).json()
        results["manual_triggers"] = trigger

        config.inbox_poll_interval = 77
        bad = await http.post("/api/settings", json={"model": "claude-sonnet-4.6", "polling_interval_inbox": "bad"})
        results["settings_partial_write"] = {"http_status": bad.status_code, "body": bad.json(), "model_after_error": config.model_name}
        string_bool = (await http.post("/api/settings", json={"dry_run": "false"})).json()
        results["settings_string_boolean"] = {"body": string_bool, "actual_dry_run": config.dry_run}
        config.dry_run = True
        list_body = await http.post("/api/settings", json=[])
        results["settings_list_body"] = list_body.json()
        forged = await http.post("/api/settings", headers={"Origin": "https://untrusted.example", "Content-Type": "text/plain"},
                                 content=json.dumps({"dry_run": False}))
        results["cross_origin_write"] = {"http_status": forged.status_code, "body": forged.json(), "dry_run": config.dry_run}
        config.dry_run = True
        config.model_name = "claude-sonnet-4.6"
        orch._sync_dynamic_model()
        results["model_sync_overwrite"] = config.model_name

    try:
        await solver_probes()
        await model_and_process_probes()
        await inbox_and_hunter_probes()
        await lifecycle_probe()
        await asyncio.to_thread(browser_probes, base)
    finally:
        server.shutdown()
        server.server_close()


async def solver_probes():
    work = config.repos_dir / "fixture_repo"
    work.mkdir(parents=True)
    def git(*args):
        return subprocess.run(["git", *args], cwd=work, check=True, capture_output=True, text=True)
    git("init", "-q", "-b", "main")
    git("config", "user.name", "audit")
    git("config", "user.email", "audit@example.invalid")
    (work / "module.py").write_text("value = 1\n")
    (work / "tests").mkdir()
    (work / "tests/test_value.py").write_text("import runpy\nfrom pathlib import Path\ndef test_value():\n    value = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'module.py'))['value']\n    assert value == 1\n")
    git("add", ".")
    git("commit", "-qm", "fixture")
    client = GitHubClient(config)
    client.create_pull_request = AsyncMock(return_value={"html_url": "https://github.com/fixture/repo/pull/mock", "dry_run": True})
    ai = AIEngine(config)
    ai.generate_code_patch = AsyncMock(return_value={"can_fix": False, "confidence": 0.0,
                                                   "target_file": "module.py", "file_content": "value = 2\n"})
    ai.generate_pr_metadata = AsyncMock(return_value={"title": "fixture", "body": "fixture"})
    solver = PRSolver(client=client, ai=ai, agent_config=config)
    count = 0
    real_tests = solver._run_repo_tests
    async def counted(path):
        nonlocal count
        count += 1
        return await real_tests(path)
    solver._run_repo_tests = counted
    candidate = {"repo": "fixture/repo", "issue_number": 1, "title": "fixture bug", "url": "https://github.com/fixture/repo/issues/1"}
    res = await solver.solve_issue(candidate)
    post = await real_tests(work)
    results["solver_unverified_patch"] = {"pr_returned": bool(res), "pr_calls": client.create_pull_request.await_count,
                                          "test_runs_in_pipeline": count, "tests_after_patch_pass": post[0],
                                          "can_fix_false_ignored": bool(res)}
    empty = TMP / "no-tests"
    empty.mkdir()
    results["solver_no_tests"] = await real_tests(empty)
    # Only reset the disposable fixture repository, never the workspace.
    git("reset", "--hard", "HEAD~1")
    outside = TMP / "outside-fixture.txt"
    outside.write_text("original outside fixture\n")
    (work / "linked.txt").symlink_to(outside)
    ai.generate_code_patch.return_value = {"target_file": "linked.txt", "file_content": "audit proof only\n"}
    await solver.solve_issue({**candidate, "issue_number": 3})
    results["solver_path_escape"] = {"wrote_outside_repo_via_symlink": outside.read_text() == "audit proof only\n"}
    results["scratch_state"] = {"recorded_prs": len(solver.safety.state.submitted_prs),
                                "handled_issues": len(solver.safety.state.handled_issues)}


async def model_and_process_probes():
    captured = []
    class FakeHTTP:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, json):
            captured.append(url.split("?")[0])
            return httpx.Response(404, json={"error": "fixture unavailable model"})
    config.model_name = "claude-sonnet-4.6"
    engine = AIEngine(config)
    engine.api_key = "fixture-key"
    with patch("src.ai_engine.httpx.AsyncClient", FakeHTTP):
        fallback = await engine.evaluate_notification("fixture/repo", "fixture", "mention", "Issue", [])
    results["provider_routing"] = {"request_urls": captured, "fallback": fallback}
    engine.api_key = None
    results["offline_patch"] = await engine.generate_code_patch("fixture/repo", "bug module.py", "error")
    client = GitHubClient(config)
    client._has_gh = True
    client._run_gh_api = AsyncMock(return_value=None)
    results["github_failed_rate_limit"] = await client.get_rate_limit()
    child_file = TMP / "child.pid"
    code = "import os,time,pathlib; pathlib.Path(" + repr(str(child_file)) + ").write_text(str(os.getpid())); time.sleep(10)"
    await client._run_command([sys.executable, "-c", code], timeout=0.1)
    pid = int(child_file.read_text())
    try:
        os.kill(pid, 0)
        alive = True
    except ProcessLookupError:
        alive = False
    finally:
        if 'alive' in locals() and alive:
            os.kill(pid, signal.SIGTERM)
    results["subprocess_timeout"] = {"child_alive_after_timeout": alive}


async def inbox_and_hunter_probes():
    from src.inbox_manager import InboxManager
    from src.issue_hunter import IssueHunter
    client = MagicMock()
    client.get_notifications = AsyncMock(return_value=[{"id": "failed-reply-fixture", "unread": True,
        "repository": {"full_name": "fixture/repo"}, "reason": "mention",
        "subject": {"title": "fixture", "type": "Issue", "url": "https://api.github.com/repos/fixture/repo/issues/1"}}])
    client.get_resource_by_url = AsyncMock(return_value={"comments_url": "fixture"})
    client.get_issue_comments = AsyncMock(return_value=[])
    client.post_issue_comment = AsyncMock(return_value=None)
    client.mark_notification_read = AsyncMock(return_value=False)
    client.mark_notification_done = AsyncMock(return_value=False)
    ai = MagicMock()
    ai.evaluate_notification = AsyncMock(return_value={"should_respond": True, "suggested_reply": "fixture meaningful reply", "rationale": "fixture"})
    config.dry_run = False
    manager = InboxManager(client=client, ai=ai, agent_config=config)
    await manager.process_inbox()
    results["inbox_failed_reply"] = {"attempted_archive": client.mark_notification_done.await_count,
                                    "persisted_as_handled": manager.safety.state.is_notification_handled("failed-reply-fixture"),
                                    "task_status": task_tracker.tasks[0]["status"]}
    config.dry_run = True
    client.search_issues = AsyncMock(return_value=[{"number": 99, "title": "fixture PR", "html_url": "https://github.com/fixture/repo/pull/99",
        "pull_request": {"url": "fixture"}, "body": "error fixture", "labels": [{"name": "bug"}],
        "repository_url": "https://api.github.com/repos/fixture/repo", "assignees": []}])
    ai.analyze_issue_actionability = AsyncMock(return_value={"is_actionable": True, "actionability_score": 0.9})
    hunter = IssueHunter(client=client, ai=ai, agent_config=config)
    with patch("src.issue_hunter.asyncio.sleep", new=AsyncMock()):
        candidates = await hunter.hunt_issues(limit=2)
    results["hunter"] = {"accepted_pr_as_issue": any('/pull/' in c['url'] for c in candidates),
                         "duplicate_candidate_urls": len(candidates) != len({c['url'] for c in candidates}),
                         "query": client.search_issues.call_args_list[0].kwargs['query']}


async def lifecycle_probe():
    orch = AutonomousOrchestrator(config, web_port=0)
    orch._sync_dynamic_model = lambda: None
    orch.client.get_rate_limit = AsyncMock(return_value={"remaining": 5000, "limit": 5000})
    orch.inbox.process_inbox = AsyncMock(side_effect=[RuntimeError("fixture transient failure")] + [[]] * 100)
    orch.hunter.hunt_issues = AsyncMock(return_value=[])
    old_intervals = config.inbox_poll_interval, config.issue_hunt_interval
    config.inbox_poll_interval = 0.01
    config.issue_hunt_interval = 0.01
    with patch("src.orchestrator.start_web_server", return_value=None):
        task = asyncio.create_task(orch.start())
        await asyncio.sleep(0.085)
        orch.stop()
        start = time.monotonic()
        await asyncio.wait_for(task, timeout=2)
    results["lifecycle"] = {"inbox_iterations": orch.inbox.process_inbox.await_count,
                            "hunter_iterations": orch.hunter.hunt_issues.await_count,
                            "recovered_from_transient_failure": orch.inbox.process_inbox.await_count > 1,
                            "direct_stop_seconds": round(time.monotonic() - start, 4),
                            "final_status": status_tracker.overall_status}
    config.inbox_poll_interval, config.issue_hunt_interval = old_intervals
    from src.safety_guardrails import StateStore
    path = TMP / "multiple-writers.json"
    first, second = StateStore(path), StateStore(path)
    first.record_pr_submission("fixture/repo", "fixture-issue", "fixture-pr")
    second.mark_notification_handled("fixture-thread")
    results["multiple_state_writers"] = {"pr_records_after_second_writer": len(StateStore(path).submitted_prs)}


def browser_probes(base):
    from playwright.sync_api import sync_playwright
    status_tracker.overall_status = "STOPPED"
    config.model_name = "gemini-3.8-flash"
    config.inbox_poll_interval = 77
    config.issue_hunt_interval = 333
    status_tracker.save()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base)
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(OUT / "desktop.png"), full_page=True)
        nav = {}
        for tab in ("overview", "tasks", "workers", "terminal", "settings"):
            page.locator(f'.nav-item[data-tab="{tab}"]').click()
            nav[tab] = page.locator(f"#view-{tab}").is_visible()
        results["browser_navigation"] = nav
        results["browser_settings"] = {"selected_model": page.locator("#modelSelect").input_value(),
                                      "inbox_input": page.locator("#inboxIntervalInput").input_value(), "actual_inbox_interval": config.inbox_poll_interval,
                                      "hunt_input": page.locator("#issuesIntervalInput").input_value(), "actual_hunt_interval": config.issue_hunt_interval}
        page.locator("#modelSelect").select_option("GEMINI-3.8-FLASH")
        page.route("**/api/settings", lambda route: route.fulfill(status=200, content_type="application/json", body='{"status":"error","error":"fixture rejection"}'))
        page.locator("#settingsForm button[type=submit]").click()
        page.wait_for_timeout(100)
        results["browser_error_toast"] = page.locator("#toastContainer").inner_text()
        page.locator('.nav-item[data-tab="tasks"]').click()
        results["browser_tasks"] = {"all_rows": page.locator("#tasksTableBody").inner_text()}
        page.locator('[data-filter="completed"]').click()
        results["browser_tasks"]["completed_filter"] = page.locator("#tasksTableBody").inner_text()
        page.locator('[data-filter="all"]').click()
        page.locator("#taskSearchInput").fill("fixture/repo")
        results["browser_tasks"]["repo_search"] = page.locator("#tasksTableBody").inner_text()
        page.locator("#taskSearchInput").fill("")
        page.locator("#tasksTableBody tr[data-task-id]").first.click()
        results["browser_drawer"] = {"open": "open" in page.locator("#drawerPanel").get_attribute("class"),
                                    "dialog_role": page.locator("#drawerPanel").get_attribute("role"),
                                    "focus_inside": page.evaluate("document.getElementById('drawerPanel').contains(document.activeElement)")}
        page.keyboard.press("Escape")
        results["browser_drawer"]["escape_closed"] = "open" not in page.locator("#drawerPanel").get_attribute("class")
        page.locator('.nav-item[data-tab="terminal"]').click()
        results["browser_terminal"] = page.locator("#terminalBody").inner_text()
        results["browser_static_state"] = page.locator(".system-status-indicator").inner_text()
        page.locator("#themeToggleBtn").click()
        results["browser_theme"] = page.locator("html").get_attribute("data-theme")
        page.reload()
        page.wait_for_load_state("networkidle")
        results["browser_theme_persisted"] = page.locator("html").get_attribute("data-theme")
        page.route("**/api/status", lambda route: route.fulfill(status=503, body="unavailable"))
        page.locator("#refreshBtn").click()
        page.wait_for_timeout(150)
        results["browser_offline_state"] = page.locator(".system-status-indicator").inner_text()
        # Harmless HTML injection proof through a real backend worker status field.
        page.unroute("**/api/status")
        status_tracker.update_inbox("PROCESSING", '<img src="invalid-fixture" onerror="window.__auditXss=1">')
        page.locator("#refreshBtn").click()
        page.wait_for_timeout(150)
        page.locator('.nav-item[data-tab="workers"]').click()
        results["browser_untrusted_html"] = page.evaluate("window.__auditXss === 1")
        status_tracker.update_inbox("IDLE", "Fixture idle")
        page.locator("#refreshBtn").click()
        page.wait_for_timeout(100)
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(400)
        page.screenshot(path=str(OUT / "mobile.png"), full_page=True)
        results["browser_mobile"] = page.evaluate("""() => ({viewport: innerWidth, documentWidth:document.documentElement.scrollWidth,
            headerWidth:document.querySelector('.top-header').getBoundingClientRect().width,
            sidebarRight:document.querySelector('.sidebar').getBoundingClientRect().right,
            visibleNavigation:[...document.querySelectorAll('.nav-item')].some(x=>x.getBoundingClientRect().left>=0),
            hasMenuButton:!!document.querySelector('[aria-label*=menu i], .menu-toggle, #menuToggle'),
            offscreenHeaderButtons:[...document.querySelectorAll('.top-header button')].filter(x=>x.getBoundingClientRect().right>innerWidth).map(x=>x.id)})""")
        results["browser_page_errors"] = errors
        browser.close()


if __name__ == "__main__":
    try:
        asyncio.run(backend_probes())
    finally:
        (OUT / "probe-results.json").write_text(json.dumps(results, indent=2))
        TEMP.cleanup()
    print(json.dumps(results, indent=2))
