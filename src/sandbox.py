"""Repository test execution without host secrets or submission credentials."""
import asyncio
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

from .process import run_process


class RepositorySandbox:
    def __init__(self, config):
        self.config = config

    async def run(self, command, repository):
        repository = repository.resolve()
        if self.config.sandbox_image and shutil.which("docker"):
            command = ["python3", *command[1:]] if command[0] == sys.executable else command
            name = "github-agent-test-" + uuid.uuid4().hex
            cmd = ["docker", "run", "--rm", "--name", name, "--network", "none", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--memory", "2g", "--cpus", "2", "--pids-limit", "128",
                "--read-only", "--tmpfs", "/tmp:rw,nosuid,size=256m", "--user", f"{os.getuid()}:{os.getgid()}",
                "--mount", f"type=bind,src={repository},dst=/workspace", "--workdir", "/workspace",
                "--mount", f"type=bind,src={repository / '.git'},dst=/workspace/.git,readonly",
                "--env", "HOME=/tmp", "--env", "CI=true", self.config.sandbox_image, *command]
            try:
                return await run_process(cmd, timeout=self.config.test_timeout)
            finally:
                # Killing the docker client alone does not stop its daemon-owned container.
                cleanup = asyncio.create_task(run_process(["docker", "rm", "--force", name], timeout=15))
                await asyncio.shield(cleanup)
        if sys.platform == "darwin" and shutil.which("sandbox-exec"):
            with tempfile.TemporaryDirectory(prefix="github-agent-tests-") as temp:
                directory = Path(temp).resolve()
                # Read system/toolchain libraries, repository, and an empty home only.
                paths = [repository, directory, Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(),
                         Path(__file__).resolve().parent.parent / ".venv", Path("/System"), Path("/Library/Frameworks"),
                         Path("/usr"), Path("/bin"), Path("/sbin"), Path("/private/etc"), Path("/dev")]
                reads = " ".join(f"(subpath {json.dumps(str(p))})" for p in paths)
                profile = f'(version 1) (deny default) (allow process-exec* process-fork) (allow signal (target same-sandbox)) (allow sysctl-read) (allow file-read-metadata) (allow file-read* (literal "/") {reads}) (allow file-write* (subpath {json.dumps(str(repository))}) (subpath {json.dumps(str(directory))}) (literal "/dev/null")) (deny file-write* (subpath {json.dumps(str(repository / ".git"))}))'
                env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(directory), "TMPDIR": str(directory),
                       "LANG": "en_US.UTF-8", "CI": "true", "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
                return await run_process(["sandbox-exec", "-p", profile, *command], cwd=repository,
                                         timeout=self.config.test_timeout, env=env)
        if self.config.allow_host_tests and self.config.dry_run:
            # Explicitly scoped escape hatch for trusted local dry-run fixtures only.
            with tempfile.TemporaryDirectory(prefix="github-agent-trusted-test-") as temp:
                env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": temp, "TMPDIR": temp, "CI": "true",
                       "LANG": "en_US.UTF-8", "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
                return await run_process(command, cwd=repository, timeout=self.config.test_timeout, env=env)
        raise RuntimeError("Isolated test runtime unavailable. Configure SANDBOX_IMAGE with Docker; host tests are prohibited in live mode.")


def detect_test_command(repository):
    """Select by the actual project manifest, not a generic tests directory."""
    if (repository / "package.json").exists():
        package = json.loads((repository / "package.json").read_text())
        if package.get("scripts", {}).get("test") and "no test specified" not in package["scripts"]["test"]:
            return ["npm", "test", "--", "--watch=false"]
        return None
    if (repository / "Cargo.toml").exists():
        return ["cargo", "test", "--offline"]
    if (repository / "go.mod").exists():
        return ["go", "test", "./..."]
    if any((repository / name).exists() for name in ("pyproject.toml", "pytest.ini", "setup.cfg", "setup.py")) or list(repository.rglob("test_*.py")):
        return [sys.executable, "-m", "pytest", "-q", "--maxfail=1"]
    return None


def tests_executed(command, output):
    if not output.strip():
        return False
    if "pytest" in command:
        return bool(re.search(r"\b[1-9]\d* passed\b", output))
    if command[0] == "npm":
        return bool(re.search(r"(?:Tests?:\s*[1-9]\d*\s+passed|[1-9]\d*\s+passing|# pass\s+[1-9]\d*|[✓✔])", output))
    if command[0] == "cargo":
        return bool(re.search(r"test result: ok\. [1-9]\d* passed", output))
    if command[0] == "go":
        return bool(re.search(r"^ok\s", output, re.MULTILINE)) and "[no tests to run]" not in output
    return False
