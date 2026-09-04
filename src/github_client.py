"""Async GitHub API client with automatic gh CLI and REST support."""

import asyncio
import json
import logging
import shutil
import subprocess
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple
import httpx

if TYPE_CHECKING:
    from .config import AgentConfig, config
else:
    try:
        from .config import AgentConfig, config
    except ImportError:
        from config import AgentConfig, config

logger = logging.getLogger("github_agent.client")


class GitHubClient:
    """High-level async client for GitHub API using gh CLI or HTTP REST."""

    def __init__(self, agent_config: Optional[AgentConfig] = None):
        self.config = agent_config or config
        self.base_url = "https://api.github.com"
        self._has_gh = bool(shutil.which("gh"))
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "GitHubClient":
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def _ensure_client(self):
        if self._client is None or self._client.is_closed:
            headers = {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "Antigravity-GitHub-Agent/1.0",
            }
            if self.config.github_token:
                headers["Authorization"] = f"Bearer {self.config.github_token}"

            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=httpx.Timeout(15.0, connect=10.0),
            )

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _run_command(
        self, cmd: List[str], input_data: Optional[str] = None, timeout: float = 20.0
    ) -> Optional[Tuple[int, str, str]]:
        """Execute an external CLI command asynchronously using native asyncio subprocess."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE if input_data else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=input_data.encode("utf-8") if input_data else None),
                timeout=timeout,
            )
            stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
            stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
            return (proc.returncode if proc.returncode is not None else 0), stdout, stderr
        except Exception as e:
            logger.warning(f"Command execution failed ({cmd[0] if cmd else ''}): {e}")
            return None

    async def _run_gh_api(
        self, endpoint: str, method: str = "GET", body: Optional[Dict[str, Any]] = None
    ) -> Optional[Any]:
        """Execute request via gh CLI."""
        if not self._has_gh:
            return None

        cmd = ["gh", "api", endpoint, "-X", method]
        if body:
            cmd.extend(["--input", "-"])

        input_data = json.dumps(body) if body else None

        res = await self._run_command(cmd, input_data=input_data, timeout=20.0)
        if res is not None:
            returncode, stdout, stderr = res
            if returncode == 0 and stdout:
                try:
                    return json.loads(stdout)
                except Exception:
                    return stdout.strip()
            elif returncode != 0:
                logger.warning(f"gh api error on {endpoint}: {stderr.strip()}")
        return None

    async def _request(
        self, method: str, endpoint: str, **kwargs
    ) -> httpx.Response:
        if self._has_gh:
            cli_data = await self._run_gh_api(
                endpoint=endpoint, method=method, body=kwargs.get("json")
            )
            if cli_data is not None:
                content = json.dumps(cli_data).encode("utf-8")
                return httpx.Response(status_code=200, content=content)
            return httpx.Response(status_code=500, content=b"{}")

        await self._ensure_client()
        assert self._client is not None
        url = endpoint if endpoint.startswith("http") else f"{self.base_url}{endpoint}"
        # Exponential backoff on rate-limit / transient errors (REST path only).
        delays = (1.0, 2.0, 4.0)
        last_exc: Optional[Exception] = None
        for attempt in range(len(delays) + 1):
            try:
                res = await self._client.request(method, url, **kwargs)
            except httpx.HTTPError as e:
                last_exc = e
                if attempt < len(delays):
                    await asyncio.sleep(delays[attempt])
                    continue
                raise
            if res.status_code in (403, 429) and attempt < len(delays):
                retry_after = res.headers.get("Retry-After")
                try:
                    wait = float(retry_after) if retry_after else delays[attempt]
                except ValueError:
                    wait = delays[attempt]
                logger.warning(
                    f"GitHub API rate limited ({res.status_code}); backing off {wait}s"
                )
                await asyncio.sleep(min(wait, 30.0))
                continue
            return res
        assert last_exc is not None  # pragma: no cover - defensive
        raise last_exc

    async def get_current_user(self) -> Dict[str, Any]:
        """Fetch the authenticated user profile."""
        if self._has_gh:
            data = await self._run_gh_api("/user")
            if data and isinstance(data, dict):
                return data

        res = await self._request("GET", "/user")
        if res.status_code == 200:
            return res.json()
        return {"login": self.config.github_username or "user"}

    async def get_rate_limit(self) -> Dict[str, Any]:
        """Fetch current rate limit status."""
        if self._has_gh:
            data = await self._run_gh_api("/rate_limit")
            if data and isinstance(data, dict):
                return data.get("rate", {})

        res = await self._request("GET", "/rate_limit")
        if res.status_code == 200:
            return res.json().get("rate", {})
        return {"remaining": 5000, "limit": 5000}

    async def get_notifications(
        self, all_notifications: bool = False, participating: bool = False
    ) -> List[Dict[str, Any]]:
        """Fetch notifications for the authenticated user."""
        if self._has_gh:
            endpoint = f"/notifications?all={'true' if all_notifications else 'false'}&participating={'true' if participating else 'false'}&per_page=50"
            data = await self._run_gh_api(endpoint)
            if data and isinstance(data, list):
                return data

        params = {
            "all": "true" if all_notifications else "false",
            "participating": "true" if participating else "false",
            "per_page": 50,
        }
        res = await self._request("GET", "/notifications", params=params)
        if res.status_code != 200:
            return []
        return res.json()

    async def mark_notification_read(self, thread_id: str) -> bool:
        """Mark a notification thread as read."""
        if self.config.dry_run:
            logger.info(f"[DRY-RUN] Mark notification {thread_id} as read.")
            return True

        if self._has_gh:
            res = await self._run_gh_api(f"/notifications/threads/{thread_id}", method="PATCH")
            # _run_gh_api returns None on failure; empty dict/str is still success.
            return res is not None

        res = await self._request("PATCH", f"/notifications/threads/{thread_id}")
        return res.status_code in (200, 202, 205)

    async def mark_notification_done(self, thread_id: str) -> bool:
        """Mark a notification thread as done.

        The notifications API has no DELETE endpoint for threads; marking
        read via PATCH is the supported operation. This method therefore
        marks the thread read (archiving it from the inbox view) and reports
        the real outcome instead of optimistically returning True.
        """
        if self.config.dry_run:
            logger.info(f"[DRY-RUN] Mark notification {thread_id} as done.")
            return True

        return await self.mark_notification_read(thread_id)

    async def get_resource_by_url(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetch resource by API URL or endpoint."""
        endpoint = url.replace("https://api.github.com", "") if url.startswith("https://api.github.com") else url
        if self._has_gh:
            data = await self._run_gh_api(endpoint)
            if data and isinstance(data, dict):
                return data

        res = await self._request("GET", url)
        if res.status_code == 200:
            return res.json()
        return None

    async def get_issue_comments(self, comments_url: str) -> List[Dict[str, Any]]:
        """Fetch comments for an issue or PR."""
        endpoint = comments_url.replace("https://api.github.com", "") if comments_url.startswith("https://api.github.com") else comments_url
        if self._has_gh:
            data = await self._run_gh_api(endpoint)
            if data and isinstance(data, list):
                return data

        res = await self._request("GET", comments_url)
        if res.status_code == 200:
            return res.json()
        return []

    async def post_issue_comment(
        self, owner: str, repo: str, issue_number: int, body: str
    ) -> Optional[Dict[str, Any]]:
        """Post a comment to an issue or pull request."""
        if self.config.dry_run:
            logger.info(
                f"[DRY-RUN] Would post comment to {owner}/{repo}#{issue_number}:\n{body}"
            )
            return {"id": 999999, "body": body, "dry_run": True}

        endpoint = f"/repos/{owner}/{repo}/issues/{issue_number}/comments"
        if self._has_gh:
            data = await self._run_gh_api(endpoint, method="POST", body={"body": body})
            if data and isinstance(data, dict):
                return data

        res = await self._request("POST", endpoint, json={"body": body})
        if res.status_code == 201:
            return res.json()
        return None

    async def search_issues(
        self, query: str, sort: str = "updated", order: str = "desc", per_page: int = 30
    ) -> List[Dict[str, Any]]:
        """Search issues across GitHub repositories."""
        if self._has_gh:
            cmd = [
                "gh",
                "search",
                "issues",
                query,
                "--limit",
                str(min(per_page, 50)),
                "--json",
                "number,title,url,repository,labels,body,state,assignees",
            ]
            res = await self._run_command(cmd, timeout=20.0)
            if res is not None:
                returncode, stdout, stderr = res
                if returncode == 0 and stdout:
                    try:
                        items = json.loads(stdout)
                        # Normalize fields for compatibility
                        formatted = []
                        for it in items:
                            repo_info = it.get("repository", {})
                            repo_name = repo_info.get("nameWithOwner") or repo_info.get("name", "")
                            formatted.append({
                                "number": it.get("number"),
                                "title": it.get("title", ""),
                                "html_url": it.get("url", ""),
                                "body": it.get("body", ""),
                                "labels": it.get("labels", []),
                                "repository_url": f"https://api.github.com/repos/{repo_name}",
                                "assignees": it.get("assignees", []),
                                "assignee": it.get("assignees", [None])[0] if it.get("assignees") else None,
                                "locked": bool(it.get("locked", False)),
                                "state": it.get("state", "open"),
                            })
                        return formatted
                    except Exception as e:
                        logger.warning(f"gh search issues parse error: {e}")

        res = await self._request("GET", "/search/issues", params={"q": query, "sort": sort, "order": order, "per_page": per_page})
        if res.status_code == 200:
            return res.json().get("items", [])
        return []

    async def create_pull_request(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
        draft: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Create a new Pull Request."""
        payload = {
            "title": title,
            "body": body,
            "head": head,
            "base": base,
            "draft": draft,
        }
        if self.config.dry_run:
            logger.info(
                f"[DRY-RUN] Would create PR on {owner}/{repo} from {head} -> {base}:\n"
                f"Title: {title}\nBody:\n{body}"
            )
            return {
                "id": 888888,
                "html_url": f"https://github.com/{owner}/{repo}/pull/mock-dry-run",
                "number": 12345,
                "title": title,
                "body": body,
                "dry_run": True,
            }

        endpoint = f"/repos/{owner}/{repo}/pulls"
        if self._has_gh:
            data = await self._run_gh_api(endpoint, method="POST", body=payload)
            if data and isinstance(data, dict):
                return data

        res = await self._request("POST", endpoint, json=payload)
        if res.status_code == 201:
            return res.json()
        return None
