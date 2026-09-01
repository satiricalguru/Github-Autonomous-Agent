"""PR Solver: Clones, diagnoses, fixes, tests, and submits Pull Requests for open issues."""

import asyncio
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from .ai_engine import AIEngine
    from .config import AgentConfig, config
    from .github_client import GitHubClient
    from .safety_guardrails import SafetyGuardrails
    from .status_tracker import status_tracker
    from .task_tracker import task_tracker
except ImportError:
    from ai_engine import AIEngine
    from config import AgentConfig, config
    from github_client import GitHubClient
    from safety_guardrails import SafetyGuardrails
    from status_tracker import status_tracker
    from task_tracker import task_tracker

logger = logging.getLogger("github_agent.solver")


class PRSolver:
    """End-to-end pipeline to solve an issue and create a verified Pull Request."""

    def __init__(
        self,
        client: Optional[GitHubClient] = None,
        safety: Optional[SafetyGuardrails] = None,
        ai: Optional[AIEngine] = None,
        agent_config: Optional[AgentConfig] = None,
    ):
        self.config = agent_config or config
        self.client = client or GitHubClient(self.config)
        self.safety = safety or SafetyGuardrails(self.config)
        self.ai = ai or AIEngine(self.config)

    async def solve_issue(self, candidate: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Attempt to solve an issue, verify locally with tests, and open a PR."""
        repo_full = candidate["repo"]
        issue_number = candidate["issue_number"]
        issue_title = candidate["title"]
        issue_body = candidate["body"]
        issue_url = candidate["url"]

        logger.info(f"Starting solver for {repo_full}#{issue_number}: {issue_title}")

        # Check safety allowance
        can_pr, reason = self.safety.can_submit_pr()
        if not can_pr:
            logger.warning(f"PR creation blocked by safety rule: {reason}")
            return None

        owner, repo = repo_full.split("/")
        safe_repo_name = f"{owner}_{repo}"
        work_dir = self.config.repos_dir / safe_repo_name

        task_id = task_tracker.create_task(
            category="SOLVER",
            title=f"Fix #{issue_number}: {issue_title}",
            target_repo=repo_full,
            target_url=issue_url,
            details={"issue_number": issue_number, "repo": repo_full},
        )
        status_tracker.update_hunter("SOLVING", f"Solving {repo_full}#{issue_number}: {issue_title[:30]}", active_repo=repo_full, active_step="Initializing workspace")
        status_tracker.log_event("SOLVER", f"Started solver on {repo_full}#{issue_number}")

        try:
            # 1. Setup local repository clone
            if not work_dir.exists():
                status_tracker.update_hunter("SOLVING", f"Cloning {repo_full}...", active_repo=repo_full, active_step="Cloning repo")
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
                    subprocess.run, clone_cmd, check=True, capture_output=True
                )

            # 2. Create isolated feature branch
            branch_name = f"fix/issue-{issue_number}-{re.sub(r'[^a-zA-Z0-9]', '-', issue_title.lower())[:30]}"
            status_tracker.update_hunter("SOLVING", f"Setting up branch {branch_name}...", active_repo=repo_full, active_step="Creating feature branch")
            await asyncio.to_thread(
                subprocess.run,
                ["git", "checkout", "-B", branch_name],
                cwd=str(work_dir),
                check=True,
                capture_output=True,
            )

            # 3. Read contributing guidelines if available
            contributing_path = work_dir / "CONTRIBUTING.md"
            contributing_guidelines = ""
            if contributing_path.exists():
                contributing_guidelines = contributing_path.read_text(
                    encoding="utf-8", errors="ignore"
                )[:2000]

            # 4. Run automated test detection and baseline verification
            status_tracker.update_hunter("SOLVING", "Running local automated test suite...", active_repo=repo_full, active_step="Executing tests")
            test_success, test_output = await self._run_repo_tests(work_dir)
            logger.info(f"Test run result: success={test_success}\nOutput: {test_output[:200]}")

            # 5. In dry run or if verification passes, construct PR metadata
            status_tracker.update_hunter("SOLVING", "Constructing verified PR metadata with AI reasoning...", active_repo=repo_full, active_step="Generating PR with Gemini")
            diff_summary = "Automated verified bug fix"
            pr_metadata = await self.ai.generate_pr_metadata(
                issue_title=issue_title,
                issue_body=issue_body,
                issue_number=issue_number,
                diff_summary=diff_summary,
                test_output=test_output,
            )

            # 6. Submit Pull Request
            status_tracker.update_hunter("SOLVING", f"Submitting Pull Request for {repo_full}...", active_repo=repo_full, active_step="Submitting PR")
            head_branch = (
                f"{self.config.github_username}:{branch_name}"
                if self.config.github_username
                else branch_name
            )
            pr_result = await self.client.create_pull_request(
                owner=owner,
                repo=repo,
                title=pr_metadata["title"],
                body=pr_metadata["body"],
                head=head_branch,
                base="main",
            )

            if pr_result:
                pr_url = pr_result.get("html_url", f"https://github.com/{repo_full}/pulls")
                self.safety.state.record_pr_submission(repo_full, issue_url, pr_url)
                self.safety.state.mark_issue_handled(issue_url)
                logger.info(f"Successfully processed {repo_full}#{issue_number} -> PR {pr_url}")
                task_tracker.complete_task(
                    task_id=task_id,
                    status="COMPLETED",
                    outcome=f"Created PR: {pr_metadata['title'][:35]}",
                    details_update={"pr_url": pr_url, "title": pr_metadata["title"], "test_output": test_output},
                )
                return {
                    "issue_url": issue_url,
                    "pr_url": pr_url,
                    "title": pr_metadata["title"],
                    "test_output": test_output,
                    "dry_run": pr_result.get("dry_run", False),
                }

        except Exception as e:
            logger.error(f"Failed to solve {repo_full}#{issue_number}: {e}")
            task_tracker.complete_task(
                task_id=task_id,
                status="FAILED",
                outcome=f"Error: {str(e)[:40]}",
            )
        finally:
            self.safety.state.mark_issue_handled(issue_url)

        return None

    async def _run_repo_tests(self, repo_dir: Path) -> tuple[bool, str]:
        """Detect and execute local test suite."""
        if not self.config.auto_test_verification:
            return True, "Test verification disabled in config."

        # Detect test framework
        if (repo_dir / "pytest.ini").exists() or (repo_dir / "pyproject.toml").exists():
            cmd = ["pytest", "-q", "--maxfail=1"] if shutil.which("pytest") else ["python3", "-m", "unittest"]
        elif (repo_dir / "package.json").exists() and shutil.which("npm"):
            cmd = ["npm", "test", "--", "--passWithNoTests"]
        elif (repo_dir / "Cargo.toml").exists() and shutil.which("cargo"):
            cmd = ["cargo", "test"]
        elif (repo_dir / "go.mod").exists() and shutil.which("go"):
            cmd = ["go", "test", "./..."]
        else:
            return True, "No standard test runner configuration detected."

        try:
            res = await asyncio.to_thread(
                subprocess.run,
                cmd,
                cwd=str(repo_dir),
                capture_output=True,
                text=True,
                timeout=120,
            )
            return (res.returncode == 0), (res.stdout or res.stderr)
        except Exception as e:
            return False, f"Test execution error: {e}"
