"""Regression tests for deep-audit fixes (config, safety, solver gates, trackers)."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ai_engine import extract_json_payload, sanitize_model_name
from src.config import AgentConfig
from src.pr_solver import PRSolver
from src.safety_guardrails import SafetyGuardrails
from src.status_tracker import StatusTracker
from src.task_tracker import TaskTracker


class TestAuditFixes(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        tmp = Path(self.temp_dir.name)
        self.cfg = AgentConfig(
            scratch_dir=tmp / "scratch",
            repos_dir=tmp / "scratch" / "repos",
            state_file=tmp / "scratch" / "state.json",
            dry_run=True,
        )
        self.safety = SafetyGuardrails(self.cfg)
        self.status = StatusTracker(self.cfg)
        self.tasks = TaskTracker(self.cfg)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_safe_int_fallback_on_bad_env(self):
        import os

        os.environ["INBOX_POLL_INTERVAL"] = "not-a-number"
        try:
            cfg = AgentConfig(
                scratch_dir=Path(self.temp_dir.name) / "s2",
                repos_dir=Path(self.temp_dir.name) / "s2" / "repos",
                state_file=Path(self.temp_dir.name) / "s2" / "state.json",
            )
            self.assertEqual(cfg.inbox_poll_interval, 60)
        finally:
            del os.environ["INBOX_POLL_INTERVAL"]

    def test_target_languages_normalized(self):
        import os

        os.environ["TARGET_LANGUAGES"] = "Python, TYPESCRIPT ,,Go"
        try:
            cfg = AgentConfig(
                scratch_dir=Path(self.temp_dir.name) / "s3",
                repos_dir=Path(self.temp_dir.name) / "s3" / "repos",
                state_file=Path(self.temp_dir.name) / "s3" / "state.json",
            )
            self.assertEqual(cfg.target_languages, ["python", "typescript", "go"])
        finally:
            del os.environ["TARGET_LANGUAGES"]

    def test_json_extraction_handles_trailing_chatter(self):
        payload = extract_json_payload('Here you go:\n{"a": 1, "b": [1,2]} thanks!')
        self.assertEqual(payload, {"a": 1, "b": [1, 2]})
        self.assertIsNone(extract_json_payload("no json here"))

    def test_model_name_sanitization(self):
        self.assertEqual(sanitize_model_name("gemini-3.8-flash"), "gemini-3.8-flash")
        self.assertEqual(sanitize_model_name("evil/model;rm"), "gemini-3.8-flash")
        self.assertEqual(sanitize_model_name(""), "gemini-3.8-flash")

    async def test_solver_rejects_malformed_candidate(self):
        solver = PRSolver(
            client=MagicMock(), safety=self.safety, agent_config=self.cfg,
            status=self.status, tasks=self.tasks,
        )
        res = await solver.solve_issue({"repo": "bad", "title": "x"})
        self.assertIsNone(res)

    async def test_solver_aborts_on_failing_tests(self):
        mock_client = MagicMock()
        mock_client.create_pull_request = AsyncMock(return_value={"html_url": "http://pr"})
        mock_client.check_issue_eligibility = AsyncMock(return_value=(True, "ok"))
        mock_client.get_repository = AsyncMock(return_value={"default_branch": "main"})
        solver = PRSolver(
            client=mock_client, safety=self.safety, agent_config=self.cfg,
            status=self.status, tasks=self.tasks,
        )
        solver._run_repo_tests = AsyncMock(return_value=(False, "FAILED"))
        solver._git = AsyncMock(return_value="")
        candidate = {
            "repo": "owner/repo", "issue_number": 1, "title": "bug",
            "body": "body", "url": "https://github.com/owner/repo/issues/1",
        }
        res = await solver.solve_issue(candidate)
        self.assertIsNone(res)
        solver._run_repo_tests.assert_awaited_once()
        self.assertIn("Baseline tests failed", self.tasks.get_api_tasks()[0]["error"])
        mock_client.create_pull_request.assert_not_called()

    def test_task_tracker_includes_failed(self):
        tid = self.tasks.create_task(category="SOLVER", title="t")
        self.tasks.complete_task(task_id=tid, status="FAILED", outcome="err")
        self.assertEqual(len(self.tasks.get_completed_tasks()), 1)
        self.assertEqual(len(self.tasks.get_active_tasks()), 0)

    def test_state_collision_safe_tmp(self):
        from src.safety_guardrails import atomic_write_json

        target = Path(self.temp_dir.name) / "x.json"
        atomic_write_json(target, {"a": 1})
        leftovers = list(Path(self.temp_dir.name).glob("*.tmp*"))
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
