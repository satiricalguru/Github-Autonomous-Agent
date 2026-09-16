"""Issue repair with isolated tests, red/green regression evidence, and checked git operations."""
import asyncio
import base64
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

from .ai_engine import AIEngine
from .config import config
from .github_client import GitHubClient
from .process import run_process
from .sandbox import RepositorySandbox, detect_test_command, tests_executed
from .safety_guardrails import SafetyGuardrails
from .status_tracker import status_tracker
from .task_tracker import task_tracker

logger = logging.getLogger("github_agent.solver")
REPO_NAME = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SOURCE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".c", ".cpp", ".h"}


def _is_test_path(relative):
    path = Path(relative)
    return (any(part.lower() in ("test", "tests", "__tests__", "spec", "specs") for part in path.parts)
            or path.name.startswith("test_") or bool(re.search(r"(?:_test\.[^.]+|\.(?:test|spec)\.[^.]+)$", path.name)))


def _safe_target(repository, relative):
    path = Path(relative)
    if not relative or path.is_absolute() or any(part in ("..", ".git") for part in path.parts):
        raise ValueError("Unsafe patch path")
    if path.name.startswith(".env") or path.suffix in (".pem", ".key"):
        raise ValueError("Sensitive file cannot be a patch target")
    current = repository.resolve()
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Patch targets must not traverse symlinks")
    if repository.resolve() not in current.resolve().parents:
        raise ValueError("Patch target escapes repository")
    return current


def _summarize_repo_tree(work_dir, limit=200):
    paths = []
    for path in work_dir.rglob("*"):
        if len(paths) >= limit:
            break
        relative = path.relative_to(work_dir)
        if not any(part in (".git", "node_modules", "__pycache__", ".venv") for part in relative.parts) and path.is_file() and not path.is_symlink():
            paths.append(str(relative))
    return "\n".join(sorted(paths))


class PRSolver:
    def __init__(self, client=None, safety=None, ai=None, agent_config=None, status=None, tasks=None):
        self.config = agent_config or config
        self.client = client or GitHubClient(self.config)
        self.safety = safety or SafetyGuardrails(self.config)
        self.ai = ai or AIEngine(self.config)
        self.status = status if status is not None else status_tracker
        self.tasks = tasks if tasks is not None else task_tracker
        self.sandbox = RepositorySandbox(self.config)
        self._dry_run_issues = set()

    def _apply_patch(self, repository, patch):
        relative = patch.get("target_file")
        if not isinstance(relative, str):
            raise ValueError("Missing patch target")
        target = _safe_target(repository, relative)
        search, replacement, content = patch.get("search_content", ""), patch.get("replacement_content", ""), patch.get("file_content", "")
        if not all(isinstance(value, str) for value in (search, replacement, content)):
            raise ValueError("Patch content must be text")
        if search:
            original = target.read_text()
            if original.count(search) != 1:
                raise ValueError("Patch search snippet must match exactly once")
            content = original.replace(search, replacement, 1)
        elif not content:
            raise ValueError("Patch contains no modification")
        if len(content.encode()) > 256 * 1024:
            raise ValueError("Patch exceeds size bound")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return relative

    async def _git(self, repository, *args, authenticated=False):
        env = dict(os.environ)
        env.update(GIT_TERMINAL_PROMPT="0", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
        if authenticated:
            if not self.config.github_token:
                raise RuntimeError("GitHub authentication unavailable")
            auth = base64.b64encode(f"x-access-token:{self.config.github_token}".encode()).decode()
            env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader", GIT_CONFIG_VALUE_0=f"AUTHORIZATION: basic {auth}")
        result = await run_process(["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", *args], cwd=repository, timeout=180, env=env)
        if result.returncode:
            raise RuntimeError(f"git {args[0]} failed (exit {result.returncode})")
        return result.stdout

    def _source_context(self, repository, candidate):
        words = set(re.findall(r"[a-zA-Z_]{4,}", candidate.get("title", "") + " " + candidate.get("body", "")))
        files = [p for p in repository.rglob("*") if p.suffix in SOURCE_EXTENSIONS and p.is_file() and not p.is_symlink()
                 and not any(part in (".git", "node_modules", "__pycache__", ".venv") for part in p.relative_to(repository).parts)]
        files.sort(key=lambda p: (-sum(w.lower() in str(p.relative_to(repository)).lower() for w in words), str(p)))
        snippets, remaining = [], 40000
        for path in files[:12]:
            if path.stat().st_size > 256000:
                continue
            content = path.read_text(errors="replace")[:remaining]
            snippets.append(f"FILE {path.relative_to(repository)}\n{content}")
            remaining -= len(content)
            if remaining <= 0:
                break
        return "\n\n".join(snippets)

    async def _run_repo_tests(self, repo_dir):
        if not self.config.auto_test_verification:
            return False, "Test verification cannot be disabled for submission"
        command = detect_test_command(repo_dir)
        if not command:
            return False, "No executable test suite was detected"
        try:
            result = await self.sandbox.run(command, repo_dir)
            output = (result.stdout + "\n" + result.stderr).strip()
            passed = result.returncode == 0 and tests_executed(command, output)
            return passed, output[:16000] or "No tests produced evidence"
        except asyncio.CancelledError:
            raise
        except Exception as error:
            return False, str(error) if isinstance(error, RuntimeError) else f"Test execution failed ({type(error).__name__})"

    async def solve_issue(self, candidate):
        repo = candidate.get("repo", "")
        number = candidate.get("issue_number")
        if not REPO_NAME.fullmatch(repo) or type(number) is not int or number < 1:
            return None
        owner, name = repo.split("/")
        issue_url = f"https://github.com/{repo}/issues/{number}"
        if candidate.get("url") != issue_url:
            return None
        if self.config.dry_run and issue_url in self._dry_run_issues:
            return None
        # Dry-run does not touch eligibility history or reserve live submission capacity.
        claimed = False
        if not self.config.dry_run:
            claimed = self.safety.state.claim_issue(issue_url, self.config.max_prs_per_day)
            if not claimed:
                return None
        task_id = self.tasks.create_task("SOLVER", f"Fix #{number}: {candidate.get('title', '')}", repo, issue_url, {"dry_run": self.config.dry_run, "issue_number": number})
        try:
            eligible, reason = await self.client.check_issue_eligibility(owner, name, number)
            if not eligible:
                raise RuntimeError(reason)
            metadata = await self.client.get_repository(owner, name)
            base = metadata["default_branch"]
            self.config.repos_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=f"{owner}_{name}_{number}_", dir=self.config.repos_dir) as directory:
                work = Path(directory)
                self.status.update_hunter("SOLVING", f"Repairing {repo}#{number}", active_repo=repo)
                await self._git(work, "clone", "--depth", "20", "--branch", base, f"https://github.com/{repo}.git", ".")
                branch = f"codex/fix-issue-{number}"
                await self._git(work, "checkout", "-b", branch)
                await self._git(work, "config", "user.name", self.config.github_username or "GitHub Agent")
                await self._git(work, "config", "user.email", f"{self.config.github_username or 'agent'}@users.noreply.github.com")
                guidelines = []
                for file in ("AGENTS.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", ".github/CONTRIBUTING.md", ".github/PULL_REQUEST_TEMPLATE.md", ".github/pull_request_template.md"):
                    path = _safe_target(work, file)
                    if path.is_file():
                        guidelines.append(f"{file}:\n{path.read_text(errors='replace')[:10000]}")
                guidelines = "\n\n".join(guidelines)
                if re.search(r"\bCLA\b|contributor license agreement", guidelines, re.IGNORECASE) and repo not in self.config.accepted_cla_repos:
                    raise RuntimeError("Repository requires CLA acceptance; configure ACCEPTED_CLA_REPOS after completing it")
                success, baseline = await self._run_repo_tests(work)
                if not success:
                    raise RuntimeError("Baseline tests failed or isolated test evidence is unavailable: " + baseline[:300])
                patch = await self.ai.generate_code_patch(repo, candidate.get("title", ""), candidate.get("body", ""),
                    _summarize_repo_tree(work), source_context=self._source_context(work, candidate), guidelines=guidelines, test_output=baseline)
                if patch.get("can_fix") is not True or type(patch.get("confidence")) not in (float, int) or not 0.85 <= patch["confidence"] <= 1:
                    raise RuntimeError("Model did not provide a sufficiently confident repair")
                repair_file = patch.get("target_file")
                if not isinstance(repair_file, str) or Path(repair_file).suffix not in SOURCE_EXTENSIONS or _is_test_path(repair_file):
                    raise ValueError("Repair must modify a supported source file and preserve existing tests")
                regression = patch.get("regression_tests")
                if not isinstance(regression, list) or not 1 <= len(regression) <= 5:
                    raise RuntimeError("A reproducible regression test is required")
                test_files = []
                for test in regression:
                    relative = test.get("target_file", "")
                    if not isinstance(relative, str) or not _is_test_path(relative):
                        raise ValueError("Regression test path must identify a test file")
                    target = _safe_target(work, relative)
                    if target.exists():
                        raise ValueError("Regression tests must be new files to preserve the existing suite")
                    test_files.append(self._apply_patch(work, test))
                if patch.get("target_file") in test_files:
                    raise ValueError("Repair must not modify its regression test")
                red_success, red_output = await self._run_repo_tests(work)
                if red_success:
                    raise RuntimeError("Regression test did not reproduce the defect")
                # A test-runtime error is not a reproduced defect.
                if not re.search(r"FAILED|FAIL|failed|AssertionError|panic|not ok", red_output):
                    raise RuntimeError("Regression test failed without reproducible assertion evidence")
                changed_file = self._apply_patch(work, patch)
                green_success, green_output = await self._run_repo_tests(work)
                if not green_success:
                    raise RuntimeError("Patched regression suite failed: " + green_output[:300])
                await self._git(work, "add", "--", changed_file, *test_files)
                diff = await self._git(work, "diff", "--cached")
                if not diff.strip():
                    raise RuntimeError("Repair produced an empty diff")
                await self._git(work, "commit", "-s", "-m", f"fix: resolve issue #{number}")
                final_success, final_output = await self._run_repo_tests(work)
                dirty = (await self._git(work, "diff", "HEAD", "--")).strip()
                untracked = (await self._git(work, "ls-files", "--others", "--exclude-standard")).splitlines()
                unsubmitted_source = any(Path(file).suffix in SOURCE_EXTENSIONS for file in untracked)
                if not final_success or dirty or unsubmitted_source:
                    raise RuntimeError("The exact commit could not be verified")
                test_evidence = f"Baseline:\n{baseline}\n\nRegression before fix:\n{red_output}\n\nCommitted repair:\n{final_output}"
                pr = await self.ai.generate_pr_metadata(candidate.get("title", ""), candidate.get("body", ""), number, diff[:20000], test_evidence, guidelines=guidelines)
                pr_body = pr.get("body", "") + f"\n\n### Executed verification\n```text\n{test_evidence[-12000:]}\n```\n\nCloses #{number}\n"
                if not self.config.dry_run:
                    eligible, reason = await self.client.check_issue_eligibility(owner, name, number)
                    if not eligible:
                        raise RuntimeError(reason)
                    quota = await self.client.get_rate_limit()
                    safe, reason = self.safety.check_rate_limit(quota.get("remaining"))
                    if not safe:
                        raise RuntimeError(reason)
                    fork = await self.client.ensure_fork(owner, name)
                    fork_owner = fork["owner"]["login"]
                    if not REPO_NAME.fullmatch(f"{fork_owner}/{name}"):
                        raise RuntimeError("Invalid fork owner")
                    await self._git(work, "remote", "add", "submission", f"https://github.com/{fork_owner}/{name}.git")
                    await self._git(work, "push", "submission", f"HEAD:refs/heads/{branch}", authenticated=True)
                    head = f"{fork_owner}:{branch}"
                else:
                    head = f"{self.config.github_username}:{branch}"
                result = await self.client.create_pull_request(owner, name, pr.get("title") or f"fix: resolve issue #{number}", pr_body, head, base, draft=True)
                if not result or not result.get("html_url"):
                    raise RuntimeError("PR creation failed")
                url = result["html_url"]
                if not self.config.dry_run:
                    self.safety.state.record_pr_submission(repo, issue_url, url)
                    self.safety.state.mark_issue_handled(issue_url)
                else:
                    self._dry_run_issues.add(issue_url)
                self.tasks.complete_task(task_id, "COMPLETED", "Verified repair simulated" if self.config.dry_run else "Draft PR created",
                    {"pr_url": url, "test_output": test_evidence, "diff_preview": diff, "dry_run": self.config.dry_run})
                return {"pr_url": url, "issue_url": issue_url, "test_output": test_evidence, "dry_run": self.config.dry_run}
        except asyncio.CancelledError:
            self.tasks.complete_task(task_id, "CANCELLED", "Execution cancelled")
            raise
        except Exception as error:
            message = str(error) if isinstance(error, (ValueError, RuntimeError)) else f"Repair failed ({type(error).__name__})"
            self.tasks.complete_task(task_id, "FAILED", message)
            self.status.log_event("ERROR", message)
            return None
        finally:
            if claimed:
                self.safety.state.release_issue(issue_url)
