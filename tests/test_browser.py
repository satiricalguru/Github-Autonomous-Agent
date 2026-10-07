"""Browser checks against the actual dashboard and API payloads."""
import json
import os
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from src.web_dashboard import start_web_server


def test_dashboard_desktop_mobile_and_error_flows(cfg, tmp_path):
    cfg.model_name = "claude-sonnet-4-6"
    cfg.inbox_poll_interval = 77
    cfg.issue_hunt_interval = 333
    server = start_web_server(0, agent_config=cfg)
    status, tasks = server.status_tracker, server.task_tracker
    status.update_inbox("TRIAGING", '<img src="invalid" onerror="window.__xss=1">')
    status.log_event("SYSTEM", "Browser fixture event")
    tid = tasks.create_task("SOLVER", "Fixture", "fixture/repo")
    tasks.complete_task(tid, details_update={"pr_url": "javascript:alert(1)", "dry_run": True})
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with playwright.sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except playwright.Error:
                if os.getenv("CI"):
                    raise
                pytest.skip("Install Chromium with python -m playwright install chromium")
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base + "/classic")
            page.wait_for_load_state("networkidle")
            assert page.locator("#executionState").inner_text() == "STOPPED"
            for tab in ("overview", "tasks", "workers", "terminal", "settings"):
                page.locator(f'.nav-item[data-tab="{tab}"]').click()
                assert page.locator(f"#view-{tab}").is_visible()
            assert page.locator("#modelSelect").input_value() == cfg.model_name
            assert page.locator("#inboxIntervalInput").input_value() == "77"
            page.locator("#inboxIntervalInput").fill("88")
            page.wait_for_timeout(3100)
            assert page.locator("#inboxIntervalInput").input_value() == "88"
            page.route("**/api/settings", lambda route: route.fulfill(status=200, content_type="application/json", body='{"status":"error","error":"fixture rejection"}'))
            page.locator('#settingsForm button[type="submit"]').click()
            page.wait_for_function("() => document.getElementById('toastContainer').innerText.includes('fixture rejection')")
            assert "Settings saved successfully" not in page.locator("#toastContainer").inner_text()
            page.unroute("**/api/settings")
            page.locator('#settingsForm button[type="submit"]').click()
            page.wait_for_function("() => document.getElementById('toastContainer').innerText.includes('Settings saved successfully')")
            assert cfg.inbox_poll_interval == 88
            page.locator('.nav-item[data-tab="tasks"]').click()
            page.locator('[data-filter="completed"]').click()
            assert "fixture/repo" in page.locator("#tasksTableBody").inner_text()
            page.locator("#taskSearchInput").fill("fixture/repo")
            row = page.locator(f'[data-task-id="{tid}"]')
            row.focus()
            page.wait_for_timeout(3100)
            assert row.evaluate("el => el === document.activeElement")
            page.keyboard.press("Enter")
            assert page.locator("#drawerPanel").get_attribute("role") == "dialog"
            assert page.locator("#drawerPanel").evaluate("el => el.contains(document.activeElement)")
            assert page.locator('#drawerPanel a[href^="javascript:"]').count() == 0
            page.keyboard.press("Escape")
            assert row.evaluate("el => el === document.activeElement")
            page.locator('.nav-item[data-tab="workers"]').click()
            assert page.locator('#view-workers img[src="invalid"]').count() == 0
            assert not page.evaluate("window.__xss === 1")
            page.locator('.nav-item[data-tab="terminal"]').click()
            assert "Browser fixture event" in page.locator("#terminalBody").inner_text()
            page.locator("#terminalClearBtn").click()
            page.wait_for_timeout(3100)
            assert "Browser fixture event" not in page.locator("#terminalBody").inner_text()
            page.locator("#themeToggleBtn").click()
            theme = page.locator("html").get_attribute("data-theme")
            page.reload()
            page.wait_for_load_state("networkidle")
            assert page.locator("html").get_attribute("data-theme") == theme
            capture = Path(os.getenv("BROWSER_ARTIFACT_DIR", str(tmp_path)))
            capture.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(capture / "repaired-desktop.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            page.locator("#menuToggleBtn").click()
            page.locator('.nav-item[data-tab="settings"]').click()
            assert page.locator("#view-settings").is_visible()
            page.wait_for_function("() => document.querySelector('.sidebar').getBoundingClientRect().right <= 0")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            for button in page.locator(".top-header button:visible").all():
                box = button.bounding_box()
                header = page.locator(".top-header").bounding_box()
                assert box["x"] >= 0 and box["x"] + box["width"] <= 391
                assert box["y"] + box["height"] <= header["y"] + header["height"] + 1
            page.screenshot(path=str(capture / "repaired-mobile.png"), full_page=True)
            page.route("**/api/status", lambda route: route.fulfill(status=503, body="unavailable"))
            page.locator("#refreshBtn").click()
            page.wait_for_function("() => document.getElementById('executionState').innerText === 'DISCONNECTED'")
            assert page.locator("#connectionStatus").is_visible()
            assert errors == []
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
