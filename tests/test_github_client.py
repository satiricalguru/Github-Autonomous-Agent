import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import AgentConfig
from src.github_client import GitHubClient


class TestGitHubClient(unittest.IsolatedAsyncioTestCase):
    async def test_run_command_success(self):
        client = GitHubClient(AgentConfig(dry_run=True))
        res = await client._run_command(["echo", "hello"])
        self.assertIsNotNone(res)
        returncode, stdout, stderr = res
        self.assertEqual(returncode, 0)
        self.assertIn("hello", stdout)

    async def test_run_gh_api_without_gh(self):
        client = GitHubClient(AgentConfig(dry_run=True))
        client._has_gh = False
        res = await client._run_gh_api("/user")
        self.assertIsNone(res)

    async def test_run_gh_api_with_mock_command(self):
        client = GitHubClient(AgentConfig(dry_run=True))
        client._has_gh = True
        client._run_command = AsyncMock(return_value=(0, '{"login": "testuser"}', ""))
        data = await client._run_gh_api("/user")
        self.assertEqual(data, {"login": "testuser"})


if __name__ == "__main__":
    unittest.main()
