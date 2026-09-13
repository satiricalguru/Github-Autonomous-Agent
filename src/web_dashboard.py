"""Ultra-responsive web dashboard providing real-time telemetry, task inspection,
control actions, and WCAG 2.1 AA accessible visualization for the Autonomous GitHub Agent.
Now powered by a modular Vanilla TypeScript/HTML/CSS architecture.
"""

import asyncio
import http.server
import json
import logging
import mimetypes
from pathlib import Path
import socketserver
import threading
import time
import urllib.parse
from typing import Any, Dict, List, Optional

try:
    from .config import config
    from .safety_guardrails import SafetyGuardrails
    from .status_tracker import status_tracker
    from .task_tracker import task_tracker
except ImportError:
    from config import config
    from safety_guardrails import SafetyGuardrails
    from status_tracker import status_tracker
    from task_tracker import task_tracker

logger = logging.getLogger("github_agent.web")

SERVER_START_TIME = time.time()
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

ALLOWED_MODELS = frozenset({
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.1-pro",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "claude-sonnet-4.6",
    "claude-opus-4.6",
    "gpt-oss-120b",
})

MAX_SETTINGS_BYTES = 64 * 1024

# Fallback template if frontend/index.html is not found on disk
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <title>Autonomous GitHub Agent — Mission Control</title>
</head>
<body style="background:#06080d; color:#f0f6fc; font-family:sans-serif; padding:2rem;">
  <h2>Autonomous GitHub Agent Mission Control</h2>
  <p>Compiling frontend assets... Please refresh in a moment.</p>
</body>
</html>
"""


class DashboardHTTPHandler(http.server.BaseHTTPRequestHandler):
    """Custom HTTP handler serving JSON telemetry API and static frontend assets."""

    server_version = "GitHubAgent/2.0"

    def log_message(self, format, *args):
        pass

    def _read_json_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            return {}
        if length <= 0 or length > MAX_SETTINGS_BYTES:
            return {}
        try:
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/toggle-mode":
            config.dry_run = not config.dry_run
            status_tracker.config.dry_run = config.dry_run
            new_mode = "DRY_RUN" if config.dry_run else "LIVE"
            status_tracker.log_event(
                "SYSTEM",
                f"Operating mode toggled to: {'DRY-RUN' if config.dry_run else 'LIVE'}",
            )
            status_tracker.save()
            self._send_json({"dry_run": config.dry_run, "status": "ok", "mode": new_mode})

        elif parsed.path == "/api/inbox-mark-done":
            try:
                from .github_client import GitHubClient
                from .inbox_manager import InboxManager
            except ImportError:
                from github_client import GitHubClient
                from inbox_manager import InboxManager

            payload = self._read_json_body()
            thread_id = payload.get("thread_id")

            async def _mark_all():
                async with GitHubClient(config) as client:
                    mgr = InboxManager(client=client, agent_config=config)
                    if thread_id:
                        return await client.mark_notification_done(thread_id)
                    return await mgr.mark_all_completed_done()

            try:
                res = asyncio.run(_mark_all())
                status_tracker.log_event("INBOX", f"Marked notification thread as Done in GitHub Inbox")
                status_tracker.save()
                self._send_json({"status": "ok", "result": res})
            except Exception as e:
                self._send_json({"status": "error", "error": str(e)})

        elif parsed.path == "/api/pause-resume":
            curr = status_tracker.overall_status
            new_st = "PAUSED" if curr == "RUNNING" else "RUNNING"
            status_tracker.overall_status = new_st
            status_tracker.log_event("SYSTEM", f"Agent execution state set to: {new_st}")
            status_tracker.save()
            self._send_json({"status": "ok", "overall_status": new_st})

        elif parsed.path == "/api/settings":
            try:
                payload = self._read_json_body()
                model = payload.get("model_name") or payload.get("model")
                dry_run = payload.get("dry_run") if "dry_run" in payload else payload.get("is_dry_run")
                inbox_int = payload.get("inbox_poll_interval") or payload.get("polling_interval_inbox")
                hunt_int = payload.get("issue_hunt_interval") or payload.get("polling_interval_issues")
                max_tasks = payload.get("max_concurrent_tasks")

                updates = []
                if model:
                    model_str = str(model).strip().lower()[:64]
                    if model_str not in ALLOWED_MODELS:
                        self._send_json({"status": "error", "error": f"Unsupported model: {model_str}"})
                        return
                    config.model_name = model_str
                    status_tracker.active_model = model_str
                    updates.append(f"model={model_str}")
                if dry_run is not None:
                    config.dry_run = bool(dry_run)
                    status_tracker.config.dry_run = config.dry_run
                    updates.append(f"dry_run={config.dry_run}")
                if inbox_int is not None:
                    try:
                        inbox_val = max(10, min(int(inbox_int), 3600))
                    except (ValueError, TypeError):
                        self._send_json({"status": "error", "error": "Invalid inbox_poll_interval"})
                        return
                    config.inbox_poll_interval = inbox_val
                    updates.append(f"inbox_int={config.inbox_poll_interval}s")
                if hunt_int is not None:
                    try:
                        hunt_val = max(30, min(int(hunt_int), 7200))
                    except (ValueError, TypeError):
                        self._send_json({"status": "error", "error": "Invalid issue_hunt_interval"})
                        return
                    config.issue_hunt_interval = hunt_val
                    updates.append(f"hunt_int={config.issue_hunt_interval}s")
                if max_tasks is not None:
                    try:
                        config.max_concurrent_tasks = max(1, min(int(max_tasks), 10))
                        updates.append(f"max_tasks={config.max_concurrent_tasks}")
                    except (ValueError, TypeError):
                        pass

                status_tracker.save()
                status_tracker.log_event("SYSTEM", f"Agent configuration updated: {', '.join(updates)}")
                self._send_json({"status": "ok", "message": "Settings applied successfully"})
            except Exception as e:
                self._send_json({"status": "error", "error": str(e)})

        elif parsed.path == "/api/trigger-inbox":
            status_tracker.log_event("INBOX", "Manual inbox check requested from dashboard")
            self._send_json({"status": "triggered", "message": "Inbox scan initiated"})

        elif parsed.path == "/api/trigger-hunt":
            status_tracker.log_event("HUNT", "Manual issue hunt requested from dashboard")
            self._send_json({"status": "triggered", "message": "Issue hunt scan initiated"})

        elif parsed.path == "/api/trigger-solve":
            status_tracker.log_event("SOLVER", "Manual issue solver requested from dashboard")
            self._send_json({"status": "triggered", "message": "Solver process initiated"})

        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/status":
            try:
                status_tracker._load()
            except Exception:
                pass
            try:
                task_tracker._load()
            except Exception:
                pass
            snapshot = status_tracker.get_snapshot()
            tasks = task_tracker.get_all_tasks()
            snapshot["tasks"] = tasks

            # Enriched properties for modern frontend
            snapshot["status"] = snapshot.get("overall_status", "RUNNING")
            snapshot["mode"] = "DRY_RUN" if snapshot.get("dry_run", True) else "LIVE"
            snapshot["account"] = snapshot.get("github_user", config.github_username or "Authenticated User")
            snapshot["model"] = (snapshot.get("active_model", config.model_name) or "").upper()
            snapshot["config"] = {
                "dry_run": snapshot.get("dry_run", True),
                "account": snapshot.get("github_user", config.github_username or "Authenticated User"),
                "model": (snapshot.get("active_model", config.model_name) or "").upper(),
                "max_concurrent_tasks": getattr(config, "max_concurrent_tasks", 3),
                "polling_interval_inbox": snapshot.get("inbox_poll_interval", config.inbox_poll_interval),
                "polling_interval_issues": snapshot.get("issue_hunt_interval", config.issue_hunt_interval),
                "allowed_models": [m.upper() for m in sorted(ALLOWED_MODELS)],
            }

            completed_tasks = [t for t in tasks if t.get("status") == "completed"]
            pr_tasks = [t for t in completed_tasks if t.get("type") in ("pr_solve", "pull_request")]

            snapshot["metrics"] = {
                "uptime_seconds": int(time.time() - SERVER_START_TIME),
                "tasks_completed": len(completed_tasks),
                "prs_opened": len(pr_tasks),
                "inbox_processed": status_tracker.inbox_status.get("handled_count", 0),
                "active_workers": 3,
                "rate_limit_remaining": snapshot.get("rate_limit_remaining", 5000),
                "rate_limit_limit": snapshot.get("rate_limit_limit", 5000),
            }

            inbox_state = status_tracker.inbox_status.get("state", "IDLE")
            hunter_state = status_tracker.hunter_status.get("state", "IDLE")

            snapshot["workers"] = {
                "inbox": {
                    "name": "Inbox Zero Monitor",
                    "role": "Notifications & Discussions Poller",
                    "status": "running" if inbox_state in ("POLLING", "PROCESSING") else "idle",
                    "current_task": status_tracker.inbox_status.get("current_action", "Listening for notifications"),
                    "last_run": status_tracker.inbox_status.get("last_check"),
                    "next_run": status_tracker.inbox_status.get("next_check"),
                    "iteration": 1,
                },
                "hunter": {
                    "name": "Issue Hunter",
                    "role": "Tier-1 Open Source Scanner (>1000⭐)",
                    "status": "running" if hunter_state in ("HUNTING", "SEARCHING", "PROCESSING") else "idle",
                    "current_task": status_tracker.hunter_status.get("current_action", "Scanning repositories"),
                    "last_run": status_tracker.hunter_status.get("last_check"),
                    "next_run": status_tracker.hunter_status.get("next_check"),
                    "iteration": 1,
                },
                "solver": {
                    "name": "PR Solver & Verifier",
                    "role": "Local Test Runner & PR Submitter",
                    "status": "running" if any(t.get("status") == "running" for t in tasks) else "idle",
                    "current_task": "Executing test verification" if any(t.get("status") == "running" for t in tasks) else "Idle",
                    "last_run": "Standby",
                    "iteration": 1,
                },
            }

            recent_logs = []
            for ev in snapshot.get("recent_events", []):
                t = ev.get("time", "")
                comp = ev.get("component", "SYSTEM")
                msg = ev.get("message", "")
                lvl = "INFO"
                if "error" in msg.lower() or "fail" in msg.lower():
                    lvl = "ERROR"
                elif "warn" in msg.lower():
                    lvl = "WARN"
                elif "success" in msg.lower() or "marked" in msg.lower():
                    lvl = "SUCCESS"
                recent_logs.append(f"{t} [{lvl}] {comp}: {msg}")

            snapshot["recent_logs"] = recent_logs
            self._send_json(snapshot)
            return

        if parsed.path in ("/", "/index.html"):
            index_file = FRONTEND_DIR / "index.html"
            if index_file.exists():
                content = index_file.read_bytes()
            else:
                content = HTML_TEMPLATE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src data: https:; connect-src 'self'",
            )
            self.end_headers()
            self.wfile.write(content)
            return

        # Static assets serving
        clean_path = parsed.path.lstrip("/")
        target_file = (FRONTEND_DIR / clean_path).resolve()

        if target_file.is_file() and (FRONTEND_DIR in target_file.parents or target_file == FRONTEND_DIR):
            content_type, _ = mimetypes.guess_type(str(target_file))
            if target_file.suffix == ".css":
                content_type = "text/css; charset=utf-8"
            elif target_file.suffix == ".js":
                content_type = "application/javascript; charset=utf-8"
            elif target_file.suffix == ".map":
                content_type = "application/json; charset=utf-8"
            elif not content_type:
                content_type = "application/octet-stream"

            content = target_file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(content)
            return

        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_json(self, data: dict):
        body = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_web_server(port: int = 3000):
    """Start local web server on specified port in a daemon thread."""
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    socketserver.ThreadingTCPServer.daemon_threads = True
    try:
        httpd = socketserver.ThreadingTCPServer(("127.0.0.1", port), DashboardHTTPHandler)
        logger.info(f"Live Web Dashboard listening at http://localhost:{port}")
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        return httpd
    except Exception as e:
        logger.warning(f"Could not bind web dashboard on port {port}: {e}")
        return None
