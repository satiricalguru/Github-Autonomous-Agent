"""Loopback dashboard: authenticated controls, typed settings, accurate telemetry."""
import asyncio
import http.server
import json
import logging
import mimetypes
import secrets
import socketserver
import threading
import time
import urllib.parse
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError
from .ai_engine import AIEngine, sanitize_model_name
from .config import config
from .status_tracker import StatusTracker, status_tracker
from .task_tracker import TaskTracker, task_tracker

logger = logging.getLogger("github_agent.web")
SOURCE_FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
FRONTEND_DIR = SOURCE_FRONTEND if SOURCE_FRONTEND.exists() else Path(__file__).resolve().parent / "_frontend"
ALLOWED_MODELS = frozenset({"gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.1-pro",
    "gemini-2.5-flash", "gemini-2.5-pro", "claude-sonnet-4.6", "claude-opus-4.6", "gpt-oss-120b",
    "gemini-3.8-flash-high", "gemini-3.8-flash-medium", "gemini-3.8-flash-low",
    "gemini-3.7-flash-high", "gemini-3.7-flash-medium", "gemini-3.7-flash-low",
    "gemini-3.6-flash-high", "gemini-3.6-flash-medium", "gemini-3.6-flash-low",
    "gemini-3.1-pro-high", "gemini-3.1-pro-low", "claude-sonnet-4-6", "claude-opus-4-6-thinking", "gpt-oss-120b-medium"})
MAX_SETTINGS_BYTES = 64 * 1024
HTML_TEMPLATE = "<!doctype html><title>Dashboard unavailable</title><p>Dashboard assets are missing. Run npm run build in the frontend directory.</p>"


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_name: Optional[str] = None
    ai_provider: Optional[str] = None
    sync_ide_model: Optional[StrictBool] = None
    dry_run: Optional[StrictBool] = None
    inbox_poll_interval: Optional[StrictInt] = Field(default=None, ge=5, le=3600)
    issue_hunt_interval: Optional[StrictInt] = Field(default=None, ge=5, le=7200)
    max_concurrent_tasks: Optional[StrictInt] = Field(default=None, ge=1, le=10)


class DashboardHTTPHandler(http.server.BaseHTTPRequestHandler):
    server_version = "GitHubAgent/0.2"

    def log_message(self, *args):
        pass

    def _trusted_request(self):
        port = self.server.server_address[1]
        hosts = {f"localhost:{port}", f"127.0.0.1:{port}"}
        if self.headers.get("Host") not in hosts:
            return False
        origin = self.headers.get("Origin")
        return not origin or origin in {f"http://{host}" for host in hosts}

    def _authorized(self):
        token = self.server.control_token
        if secrets.compare_digest(self.headers.get("Authorization", ""), f"Bearer {token}"):
            return True
        if self.headers.get("X-Agent-Control") != "1":
            return False
        try:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            return "agent_control" in cookie and secrets.compare_digest(cookie["agent_control"].value, token)
        except Exception:
            return False

    def _read_json_body(self):
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            raise ValueError("Content-Type must be application/json")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Invalid request length") from None
        if not 0 <= length <= MAX_SETTINGS_BYTES:
            raise ValueError("Request body exceeds size limit")
        if self.headers.get("Transfer-Encoding"):
            raise ValueError("Transfer-Encoding is not supported")
        self.connection.settimeout(5)
        data = json.loads(self.rfile.read(length)) if length else {}
        if not isinstance(data, dict):
            raise ValueError("Request body must be an object")
        return data

    def _control(self, action, updates=None):
        controller = self.server.controller
        if controller is None:
            raise RuntimeError("Agent is not running; start it from the CLI")
        future = asyncio.run_coroutine_threadsafe(controller.control(action, updates), controller.loop)
        return future.result(timeout=40)

    def do_POST(self):
        if not self._trusted_request() or not self._authorized():
            self._send_json({"status": "error", "error": "Untrusted or unauthenticated control request"}, 403)
            return
        path = urllib.parse.urlparse(self.path).path
        try:
            payload = self._read_json_body()
            cfg, status = self.server.agent_config, self.server.status_tracker
            if path in ("/api/settings", "/api/toggle-mode"):
                if path == "/api/toggle-mode":
                    payload = {"dry_run": not cfg.dry_run}
                aliases = {"model": "model_name", "is_dry_run": "dry_run", "polling_interval_inbox": "inbox_poll_interval", "polling_interval_issues": "issue_hunt_interval"}
                normalized = {}
                for key, value in payload.items():
                    key = aliases.get(key, key)
                    if key in normalized:
                        raise ValueError("Duplicate settings field")
                    normalized[key] = value.lower().strip() if key == "model_name" and isinstance(value, str) else value
                updates = SettingsUpdate.model_validate(normalized).model_dump(exclude_none=True)
                if "model_name" in updates and sanitize_model_name(updates["model_name"], "") != updates["model_name"]:
                    raise ValueError("Invalid model identifier")
                type(cfg).model_validate({**cfg.model_dump(), **updates})
                if self.server.controller:
                    result = self._control("settings", updates)
                else:
                    previous = cfg.public_settings()
                    try:
                        cfg.update(**updates)
                        cfg.save_settings()
                    except Exception:
                        cfg.update(**previous)
                        raise
                    result = {"status": "ok", "message": "Settings saved for the next run"}
                status.log_event("SYSTEM", "Settings updated")
                result.update(mode="DRY_RUN" if cfg.dry_run else "LIVE", dry_run=cfg.dry_run)
                self._send_json(result)
            elif path in ("/api/pause-resume", "/api/stop", "/api/trigger-inbox", "/api/trigger-hunt", "/api/trigger-solve"):
                self._send_json(self._control(path.removeprefix("/api/")))
            elif path == "/api/inbox-mark-done":
                # Automatic processing already archives confirmed outcomes. Never bulk-archive new work.
                raise RuntimeError("Use inbox processing to archive verified handled threads")
            else:
                self._send_json({"status": "error", "error": "Unknown endpoint"}, 404)
        except (ValidationError, ValueError, json.JSONDecodeError):
            self._send_json({"status": "error", "error": "Invalid settings or request body"}, 400)
        except Exception as error:
            message = str(error) if isinstance(error, RuntimeError) else "Control operation failed"
            self._send_json({"status": "error", "error": message}, 409)

    def do_GET(self):
        if not self._trusted_request():
            self._send_json({"status": "error", "error": "Untrusted host or origin"}, 403)
            return
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/status":
            self._send_json(self._status())
            return
        routes = {"/": "home.html", "/dashboard": "dashboard.html", "/classic": "index.html"}
        file = (FRONTEND_DIR / routes.get(path, path.lstrip("/"))).resolve()
        if FRONTEND_DIR.resolve() not in file.parents or not file.is_file():
            self._send_json({"status": "error", "error": "Asset not found"}, 404)
            return
        body = file.read_bytes()
        mime = mimetypes.guess_type(str(file))[0] or "application/octet-stream"
        if file.suffix == ".js":
            mime = "application/javascript"
        self.send_response(200)
        self.send_header("Content-Type", mime + "; charset=utf-8" if file.suffix in (".html", ".js", ".css") else mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data: https:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if file.suffix == ".html":
            self.send_header("Set-Cookie", f"agent_control={self.server.control_token}; HttpOnly; SameSite=Strict; Path=/")
        self.end_headers()
        self.wfile.write(body)

    def _status(self):
        cfg, tracker, tasks = self.server.agent_config, self.server.status_tracker, self.server.task_tracker
        if not self.server.controller:
            tracker._load()
        snapshot = tracker.get_snapshot()
        records = tasks.get_api_tasks()
        state = snapshot["overall_status"]
        heartbeat = snapshot.get("heartbeat_at")
        healthy = self.server.controller is not None and self.server.controller._running
        if not healthy and state in ("RUNNING", "PAUSED", "INITIALIZING", "STOPPING"):
            state = "DISCONNECTED" if heartbeat else "STOPPED"
        if healthy and heartbeat and time.time() - heartbeat > 10:
            state = "DISCONNECTED"
        paused = state in ("PAUSED", "STOPPED", "STOPPING", "DISCONNECTED")
        def worker(name, role, data, kind):
            status = "stopped" if paused else "error" if data["state"] in ("ERROR", "BLOCKED") else "running" if data["state"] not in ("IDLE", "STOPPED") else "idle"
            return {"name": name, "role": role, "status": status, "current_task": data["current_action"], "last_run": data.get("last_check"),
                    "next_run": data.get("next_check"), "iteration": tracker.iterations.get(kind, 0)}
        workers = {"inbox": worker("Inbox Monitor", "Notifications and discussions", tracker.inbox_status, "inbox"),
                   "hunter": worker("Issue Hunter", "Eligible open bug issues", tracker.hunter_status, "hunter"),
                   "solver": {"name": "PR Solver", "role": "Isolated repair and regression verification", "status": "stopped" if paused else "running" if any(t["type"] == "pr_solve" and t["status"] == "running" for t in records) else "idle",
                              "current_task": "Repairing issues" if not paused and tasks.get_active_tasks() else "Idle", "iteration": tracker.iterations.get("hunter", 0)}}
        logs = [f"{e.get('timestamp','')} [{'ERROR' if e.get('type') == 'ERROR' else 'INFO'}] {e.get('type','SYSTEM')}: {e.get('description','')}" for e in reversed(snapshot["recent_events"])]
        return {**snapshot, "status": state, "mode": "DRY_RUN" if cfg.dry_run else "LIVE", "account": cfg.github_username or "Unverified account",
                "model": cfg.model_name, "tasks": records, "recent_logs": logs, "workers": workers,
                "config": {"dry_run": cfg.dry_run, "model": cfg.model_name, "ai_provider": cfg.ai_provider, "sync_ide_model": cfg.sync_ide_model,
                    "max_concurrent_tasks": cfg.max_concurrent_tasks, "polling_interval_inbox": cfg.inbox_poll_interval, "polling_interval_issues": cfg.issue_hunt_interval,
                    "allowed_models": sorted(ALLOWED_MODELS | {cfg.model_name})},
                "ai_health": self.server.controller.ai.get_health() if self.server.controller else AIEngine(cfg).get_health(),
                "metrics": {"uptime_seconds": int(time.time() - tracker.started_at) if healthy and tracker.started_at else 0,
                    "tasks_completed": len([t for t in records if t["status"] == "completed"]),
                    "prs_opened": len([t for t in records if t["pr_url"] and not t["details"].get("dry_run") and not t["pr_url"].endswith("mock-dry-run")]),
                    "inbox_processed": len([t for t in records if t["type"] == "inbox_notification" and t["status"] == "completed"]),
                    "active_workers": sum(w["status"] == "running" for w in workers.values()),
                    "rate_limit_remaining": tracker.rate_limit_remaining, "rate_limit_limit": tracker.rate_limit_limit}}

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


class DashboardServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def start_web_server(port=3000, agent_config=None, controller=None):
    cfg = agent_config or config
    try:
        server = DashboardServer(("127.0.0.1", port), DashboardHTTPHandler)
        server.agent_config = cfg
        server.controller = controller
        server.control_token = secrets.token_urlsafe(32)
        server.status_tracker = status_tracker if controller or cfg is config else StatusTracker(cfg)
        server.task_tracker = task_tracker if controller or cfg is config else TaskTracker(cfg)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        logger.info("Dashboard at http://127.0.0.1:%s", server.server_address[1])
        return server
    except OSError as error:
        logger.error("Dashboard bind failed: %s", error)
        return None
