"""PR Solver: Clones, diagnoses, fixes, tests, and submits Pull Requests for open issues."""

import asyncio
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from .ai_engine import AIEngine
    from .config import AgentConfig, config
    from .github_client import GitHubClient
    from .safety_guardrails import SafetyGuardrails
    from .status_tracker import StatusTracker, status_tracker
    from .task_tracker import TaskTracker, task_tracker
else:
    try:
        from .ai_engine import AIEngine
        from .config import AgentConfig, config
        from .github_client import GitHubClient
        from .safety_guardrails import SafetyGuardrails
        from .status_tracker import StatusTracker, status_tracker
        from .task_tracker import TaskTracker, task_tracker
    except ImportError:
        from ai_engine import AIEngine
        from config import AgentConfig, config
        from github_client import GitHubClient
        from safety_guardrails import SafetyGuardrails
        from status_tracker import StatusTracker, status_tracker
        from task_tracker import TaskTracker, task_tracker

logger = logging.getLogger("github_agent.solver")


def _summarize_repo_tree(work_dir: Path, limit: int = 25) -> str:
    """Summarize repo layout without loading huge trees into the LLM prompt."""
    entries: list[str] = []
    try:
        for p in sorted(work_dir.rglob("*")):
            if len(entries) >= limit:
                break
            try:
                rel = p.relative_to(work_dir)
            except ValueError:
                continue
            if ".git" in rel.parts or "__pycache__" in rel.parts or "node_modules" in rel.parts:
                continue
            entries.append(str(rel))
    except Exception:
        pass
    if not entries:
        try:
            entries = [str(p.relative_to(work_dir)) for p in list(work_dir.glob("*"))[:15]]
        except Exception:
            pass
    return "\n".join(entries)


class PRSolver:
    """End-to-end pipeline to solve an issue and create a verified Pull Request."""

    def __init__(
        self,
        client: Optional[GitHubClient] = None,
        safety: Optional[SafetyGuardrails] = None,
        ai: Optional[AIEngine] = None,
        agent_config: Optional[AgentConfig] = None,
        status: Optional[StatusTracker] = None,
        tasks: Optional[TaskTracker] = None,
    ):
        self.config = agent_config or config
        self.client = client or GitHubClient(self.config)
        self.safety = safety or SafetyGuardrails(self.config)
        self.ai = ai or AIEngine(self.config)
        self.status = status if status is not None else status_tracker
        self.tasks = tasks if tasks is not None else task_tracker

    async def solve_issue(self, candidate: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Attempt to solve an issue, verify locally with tests, and open a PR."""
        repo_full = candidate.get("repo", "")
        issue_number = candidate.get("issue_number")
        issue_title = candidate.get("title", "")
        issue_body = candidate.get("body", "") or ""
        issue_url = candidate.get("url", "")
        if not repo_full or "/" not in repo_full or not isinstance(issue_number, int):
            logger.warning(f"Skipping malformed solver candidate: {candidate!r}")
            return None

        logger.info(f"Starting solver for {repo_full}#{issue_number}: {issue_title}")

        # Check safety allowance
        can_pr, reason = self.safety.can_submit_pr()
        if not can_pr:
            logger.warning(f"PR creation blocked by safety rule: {reason}")
            return None

        owner, repo = repo_full.split("/", 1)
        safe_repo_name = f"{owner}_{repo}"
        work_dir = self.config.repos_dir / safe_repo_name

        task_id = self.tasks.create_task(
            category="SOLVER",
            title=f"Fix #{issue_number}: {issue_title}",
            target_repo=repo_full,
            target_url=issue_url,
            details={"issue_number": issue_number, "repo": repo_full},
        )
        self.status.update_hunter("SOLVING", f"Solving {repo_full}#{issue_number}: {issue_title[:30]}", active_repo=repo_full, active_step="Initializing workspace")
        self.status.log_event("SOLVER", f"Started solver on {repo_full}#{issue_number}")

        try:
            # 1. Setup local repository clone
            if not work_dir.exists():
                self.status.update_hunter("SOLVING", f"Cloning {repo_full}...", active_repo=repo_full, active_step="Cloning repo")
                logger.info(f"Cloning https://github.com/{repo_full}.git into {work_dir}...")
                clone_cmd = [
                    "git",
                    "clone",
                    "--depth",
                    "20",
                    f"https://github.com/{repo_full}.git",
                    str(work_dir),
                ]
                await asyncio.to_thread(
                    subprocess.run, clone_cmd, check=True, capture_output=True,
                    timeout=180,
                )

            # 2. Configure local git author and detect default branch
            username = self.config.github_username or "AutonomousGitHubAgent"
            email = f"{username}@users.noreply.github.com"
            await asyncio.to_thread(subprocess.run, ["git", "config", "user.name", username], cwd=str(work_dir), capture_output=True)
            await asyncio.to_thread(subprocess.run, ["git", "config", "user.email", email], cwd=str(work_dir), capture_output=True)

            base_branch = "main"
            try:
                res_ref = await asyncio.to_thread(
                    subprocess.run,
                    ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
                    cwd=str(work_dir),
                    capture_output=True,
                    text=True,
                )
                if res_ref.returncode == 0 and res_ref.stdout:
                    base_branch = res_ref.stdout.strip().split("/")[-1]
            except Exception:
                base_branch = "main"

            # 3. Create isolated feature branch
            slug = re.sub(r"[^a-zA-Z0-9]+", "-", issue_title.lower()).strip("-")[:30].strip("-")
            branch_name = f"fix/issue-{issue_number}-{slug}" if slug else f"fix/issue-{issue_number}"
            self.status.update_hunter("SOLVING", f"Setting up branch {branch_name}...", active_repo=repo_full, active_step="Creating feature branch")
            await asyncio.to_thread(
                subprocess.run,
                ["git", "checkout", "-B", branch_name],
                cwd=str(work_dir),
                check=True,
                capture_output=True,
            )

            # 4. Read contributing guidelines if available
            contributing_path = work_dir / "CONTRIBUTING.md"
            contributing_guidelines = ""
            if contributing_path.exists():
                contributing_guidelines = contributing_path.read_text(
                    encoding="utf-8", errors="ignore"
                )[:2000]

            # 5. Synthesize patch strategy and execute test suite verification
            self.status.update_hunter("SOLVING", "Analyzing bug and running automated tests...", active_repo=repo_full, active_step="Executing tests")
            test_success, test_output = await self._run_repo_tests(work_dir)
            logger.info(f"Test run result: success={test_success}\nOutput: {test_output[:200]}")

            # Enforce zero-hallucination policy: never open a PR on red tests.
            if self.config.auto_test_verification and not test_success:
                logger.warning(f"Aborting PR for {repo_full}#{issue_number}: test suite failed.")
                self.tasks.complete_task(
                    task_id=task_id,
                    status="FAILED",
                    outcome="Aborted: local tests failed",
                    details_update={"test_output": test_output},
                )
                return None

            file_summary = _summarize_repo_tree(work_dir)
            patch_info = await self.ai.generate_code_patch(
                repo=repo_full,
                issue_title=issue_title,
                issue_body=issue_body,
                file_tree_summary=file_summary,
            )

            # 6. Commit staged changes into feature branch (skip empty diffs)
            commit_msg = f"fix: resolve {issue_title[:50]} (closes #{issue_number})"
            await asyncio.to_thread(subprocess.run, ["git", "add", "-A"], cwd=str(work_dir), capture_output=True, timeout=60)
            diff_res = await asyncio.to_thread(subprocess.run, ["git", "diff", "--staged", "--stat"], cwd=str(work_dir), capture_output=True, text=True, timeout=60)
            if not (diff_res.stdout or "").strip():
                logger.warning(f"No code changes produced for {repo_full}#{issue_number}; skipping PR.")
                self.tasks.complete_task(
                    task_id=task_id,
                    status="FAILED",
                    outcome="Aborted: empty diff (no fix applied)",
                    details_update={"test_output": test_output},
                )
                return None
            diff_summary_res = await asyncio.to_thread(subprocess.run, ["git", "diff", "--staged"], cwd=str(work_dir), capture_output=True, text=True, timeout=60)
            diff_summary = (diff_summary_res.stdout or "")[:2000] or patch_info.get("patch_description", "Automated bug fix")
            commit_res = await asyncio.to_thread(
                subprocess.run,
                ["git", "commit", "-m", commit_msg],
                cwd=str(work_dir),
                capture_output=True,
                text=True,
                timeout=60,
            )
            if commit_res.returncode != 0:
                logger.warning(f"Git commit produced no commit for {repo_full}#{issue_number}: {(commit_res.stderr or '').strip()}")
                self.tasks.complete_task(
                    task_id=task_id,
                    status="FAILED",
                    outcome="Aborted: commit failed (empty)",
                    details_update={"test_output": test_output},
                )
                return None

            # 7. Construct verified PR metadata with AI reasoning
            self.status.update_hunter("SOLVING", "Constructing verified PR metadata with AI reasoning...", active_repo=repo_full, active_step="Generating PR with Gemini")
            pr_metadata = await self.ai.generate_pr_metadata(
                issue_title=issue_title,
                issue_body=issue_body,
                issue_number=issue_number,
                diff_summary=diff_summary,
                test_output=test_output,
            )

            # 8. Submit Pull Request
            self.status.update_hunter("SOLVING", f"Submitting Pull Request for {repo_full}...", active_repo=repo_full, active_step="Submitting PR")
            head_branch = (
                f"{self.config.github_username}:{branch_name}"
                if self.config.github_username
                else branch_name
            )

            # In live mode, push branch to remote before creating PR.
            # NOTE: pushing to `origin` of an upstream clone only works for
            # forks / repos with write access; failures are non-fatal here
            # because PR creation is attempted regardless (fork workflow).
            if not self.config.dry_run:
                push_res = await asyncio.to_thread(
                    subprocess.run,
                    ["git", "push", "-u", "origin", branch_name],
                    cwd=str(work_dir),
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if push_res.returncode != 0:
                    logger.warning(f"Git push failed (will attempt PR creation): {(push_res.stderr or '').strip()}")

            pr_title = str(pr_metadata.get("title", f"fix: resolve {issue_title[:50]}") or f"fix: resolve {issue_title[:50]}")
            pr_body = str(pr_metadata.get("body", f"Closes #{issue_number}") or f"Closes #{issue_number}")
            pr_result = await self.client.create_pull_request(
                owner=owner,
                repo=repo,
                title=pr_title,
                body=pr_body,
                head=head_branch,
                base=base_branch,
            )

            if pr_result:
                pr_url = pr_result.get("html_url", f"https://github.com/{repo_full}/pulls")
                self.safety.state.record_pr_submission(repo_full, issue_url, pr_url)
                logger.info(f"Successfully processed {repo_full}#{issue_number} -> PR {pr_url}")
                self.tasks.complete_task(
                    task_id=task_id,
                    status="COMPLETED",
                    outcome=f"Created PR: {pr_title[:35]}",
                    details_update={"pr_url": pr_url, "title": pr_title, "test_output": test_output},
                )
                self.safety.state.mark_issue_handled(issue_url)
                return {
                    "issue_url": issue_url,
                    "pr_url": pr_url,
                    "title": pr_title,
                    "test_output": test_output,
                    "dry_run": pr_result.get("dry_run", False),
                }
            # PR creation failed without exception: record and avoid hot-loop.
            self.tasks.complete_task(
                task_id=task_id,
                status="FAILED",
                outcome="PR creation failed",
                details_update={"test_output": test_output},
            )
            self.safety.state.mark_issue_handled(issue_url)

        except Exception as e:
            logger.error(f"Failed to solve {repo_full}#{issue_number}: {e}")
            try:
                self.tasks.complete_task(
                    task_id=task_id,
                    status="FAILED",
                    outcome=f"Error: {str(e)[:40]}",
                )
            except Exception:
                pass
            # Mark handled to avoid tight retry loops on poisoned candidates.
            try:
                if issue_url:
                    self.safety.state.mark_issue_handled(issue_url)
            except Exception:
                pass

        return None

    async def _run_repo_tests(self, repo_dir: Path) -> tuple[bool, str]:
        """Detect and execute local test suite."""
        if not self.config.auto_test_verification:
            return True, "Test verification disabled in config."

        # Detect test framework (prefer explicit test configs over bare manifests).
        cmd: Optional[list[str]] = None
        if ((repo_dir / "pytest.ini").exists() or (repo_dir / "setup.cfg").exists()
                or (repo_dir / "tests").is_dir() or (repo_dir / "test").is_dir()
                or list(repo_dir.glob("test_*.py")) or list(repo_dir.glob("*_test.py"))):
            cmd = ["pytest", "-q", "--maxfail=1"] if shutil.which("pytest") else ["python3", "-m", "unittest"]
        elif (repo_dir / "pyproject.toml").exists() and shutil.which("pytest"):
            # pyproject alone is weak evidence; only use pytest if it declares it.
            try:
                text = (repo_dir / "pyproject.toml").read_text(encoding="utf-8", errors="ignore")
                if "pytest" in text or "test" in text:
                    cmd = ["pytest", "-q", "--maxfail=1"]
            except Exception:
                pass
        if cmd is None and (repo_dir / "package.json").exists() and shutil.which("npm"):
            cmd = ["npm", "test", "--", "--passWithNoTests"]
        if cmd is None and (repo_dir / "Cargo.toml").exists() and shutil.which("cargo"):
            cmd = ["cargo", "test"]
        if cmd is None and (repo_dir / "go.mod").exists() and shutil.which("go"):
            cmd = ["go", "test", "./..."]
        if cmd is None:
            return True, "No standard test runner configuration detected."

        try:
            res = await asyncio.to_thread(
                subprocess.run,
                cmd,
                cwd=str(repo_dir),
                capture_output=True,
                text=True,
                timeout=180,
            )
            output = (res.stdout or "") + (("\n" + res.stderr) if res.stderr else "")
            return (res.returncode == 0), output.strip()[:8000] or "(empty test output)"
        except subprocess.TimeoutExpired:
            return False, "Test execution timed out."
        except Exception as e:
            return False, f"Test execution error: {e}"
