import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import AgentConfig
from src.inbox_manager import InboxManager
from src.issue_hunter import IssueHunter
from src.safety_guardrails import SafetyGuardrails, atomic_write_json
from src.cli import cmd_hunt


class TestInboxHunter(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        tmp = Path(self.temp_dir.name)
        self.state_file = tmp / "state.json"
        self.cfg = AgentConfig(
            scratch_dir=tmp / "scratch",
            repos_dir=tmp / "scratch" / "repos",
            state_file=self.state_file,
            min_repo_stars=1000,
            target_languages=["python"],
            target_labels=["bug"],
            dry_run=True,
        )
        self.safety = SafetyGuardrails(self.cfg)
        # Isolated trackers so tests never pollute real scratch/*.json
        from src.status_tracker import StatusTracker
        from src.task_tracker import TaskTracker
        self.status = StatusTracker(self.cfg)
        self.tasks = TaskTracker(self.cfg)

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    async def test_inbox_manager_populates_results(self):
        """Verify that process_inbox returns populated results list."""
        mock_client = MagicMock()
        mock_client.get_notifications = AsyncMock(
            return_value=[
                {
                    "id": "thread-101",
                    "repository": {"full_name": "owner/repo"},
                    "reason": "mention",
                    "subject": {
                        "title": "Bug in parser",
                        "type": "Issue",
                        "url": "https://api.github.com/repos/owner/repo/issues/1",
                    },
                }
            ]
        )
        mock_client.get_resource_by_url = AsyncMock(return_value={"comments_url": "https://api.github.com/comments"})
        mock_client.get_issue_comments = AsyncMock(return_value=[])
        mock_client.post_issue_comment = AsyncMock(return_value={"id": 1})
        mock_client.mark_notification_read = AsyncMock(return_value=True)
        mock_client.mark_notification_done = AsyncMock(return_value=True)

        inbox = InboxManager(client=mock_client, safety=self.safety, agent_config=self.cfg, status=self.status, tasks=self.tasks)
        results = await inbox.process_inbox()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["thread_id"], "thread-101")
        self.assertEqual(results[0]["repo"], "owner/repo")
        self.assertEqual(results[0]["title"], "Bug in parser")
        self.assertIn("action", results[0])

    async def test_issue_hunter_includes_language_and_stars(self):
        """Verify IssueHunter includes language in candidates and stars:>= in query."""
        mock_client = MagicMock()
        captured_queries = []

        async def mock_search(query, **kwargs):
            captured_queries.append(query)
            return [
                {
                    "number": 42,
                    "title": "IndexError in pipeline",
                    "html_url": "https://github.com/fastapi/fastapi/issues/42",
                    "body": "Repro: ```python\nraise IndexError\n```",
                    "labels": ["bug"],
                    "repository_url": "https://api.github.com/repos/fastapi/fastapi",
                    "assignees": [],
                    "state": "open",
                }
            ]

        mock_client.search_issues = AsyncMock(side_effect=mock_search)

        hunter = IssueHunter(client=mock_client, safety=self.safety, agent_config=self.cfg, status=self.status)
        candidates = await hunter.hunt_issues(limit=1)

        self.assertGreaterEqual(len(candidates), 1)
        self.assertIn("language", candidates[0])
        self.assertEqual(candidates[0]["language"], "python")
        self.assertTrue(any("stars:>=1000" in q for q in captured_queries))

    def test_atomic_write_json(self):
        """Verify atomic_write_json cleanly creates files without leaving tmp files."""
        target = Path(self.temp_dir.name) / "test_atomic.json"
        data = {"key": "value", "count": 42}
        atomic_write_json(target, data)

        self.assertTrue(target.exists())
        with open(target, "r") as f:
            loaded = json.load(f)
        self.assertEqual(loaded, data)

        # Check no tmp files remain
        tmp_files = list(Path(self.temp_dir.name).glob("*.tmp*"))
        self.assertEqual(len(tmp_files), 0)

    async def test_cli_cmd_hunt_rendering_safety(self):
        """Verify cmd_hunt renders table even if candidate lacks language key."""
        mock_hunter = MagicMock()
        mock_hunter.hunt_issues = AsyncMock(
            return_value=[
                {
                    "repo": "owner/repo",
                    "issue_number": 99,
                    "title": "Fix memory leak",
                    "score": 0.95,
                    "url": "https://github.com/owner/repo/issues/99",
                    # Deliberately omitting "language" to test resilience
                }
            ]
        )

        with patch("src.cli.IssueHunter", return_value=mock_hunter):
            with patch("src.cli.GitHubClient"):
                # Must not raise KeyError: 'language'
                await cmd_hunt(limit=1)


if __name__ == "__main__":
    unittest.main()
