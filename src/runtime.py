"""Single-process ownership and authenticated cross-process control."""
import fcntl
import json
import os
from pathlib import Path

import httpx


class RunLease:
    def __init__(self, scratch_dir: Path):
        self.path = scratch_dir / "run.lock"
        self.file = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+")
        try:
            fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.file.close()
            self.file = None
            raise RuntimeError("An agent operation is already running in this workspace") from None

    def close(self):
        if self.file:
            fcntl.flock(self.file, fcntl.LOCK_UN)
            self.file.close()
            self.file = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.close()


def write_runtime(scratch_dir, port, token):
    from .safety_guardrails import atomic_write_json
    path = scratch_dir / "runtime.json"
    atomic_write_json(path, {"pid": os.getpid(), "port": port, "token": token})
    path.chmod(0o600)


def send_control(scratch_dir, action):
    path = scratch_dir / "runtime.json"
    if not path.exists():
        raise RuntimeError("No running agent control endpoint")
    data = json.loads(path.read_text())
    port = data.get("port")
    if type(port) is not int or not 1 <= port <= 65535:
        raise RuntimeError("Invalid runtime endpoint")
    try:
        response = httpx.post(f"http://127.0.0.1:{port}/api/{action}",
            headers={"Authorization": f"Bearer {data['token']}", "Content-Type": "application/json"},
            json={}, timeout=15, trust_env=False)
        response.raise_for_status()
        result = response.json()
        if result.get("status") != "ok":
            raise RuntimeError(result.get("error", "Control request rejected"))
        return result
    except (httpx.HTTPError, KeyError, ValueError):
        raise RuntimeError("Cannot reach the running agent; check its process and dashboard") from None
