"""Authenticated GitHub REST/GraphQL transport with explicit failure states."""
import asyncio
import json
import logging
import shutil
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from .config import AgentConfig, config
from .process import run_process

logger = logging.getLogger("github_agent.client")


class GitHubAPIError(RuntimeError):
    pass


class GitHubClient:
    def __init__(self, agent_config: Optional[AgentConfig] = None):
        self.config = agent_config or config
        self.base_url = "https://api.github.com"
        self._has_gh = bool(shutil.which("gh"))
        self._client = None

    async def __aenter__(self):
        await self._ensure_client()
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def _ensure_client(self):
        if self._client is None or self._client.is_closed:
            headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                       "User-Agent": "Autonomous-GitHub-Agent/0.2"}
            if self.config.github_token:
                headers["Authorization"] = f"Bearer {self.config.github_token}"
            self._client = httpx.AsyncClient(base_url=self.base_url, headers=headers, timeout=20, follow_redirects=False)

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def _run_command(self, cmd, input_data=None, timeout=20):
        try:
            result = await run_process(cmd, timeout=timeout, input_data=input_data)
            return result.returncode, result.stdout, result.stderr
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("Command failed (%s): %s", cmd[0], type(error).__name__)
            return None

    async def _run_gh_api(self, endpoint, method="GET", body=None):
        if not self._has_gh:
            return None
        cmd = ["gh", "api", endpoint, "-X", method]
        if body is not None:
            cmd += ["--input", "-"]
        result = await self._run_command(cmd, json.dumps(body) if body is not None else None)
        if result and result[0] == 0:
            return json.loads(result[1]) if result[1].strip() else {}
        return None

    async def _request(self, method, endpoint, **kwargs):
        # gh auth is used for credential discovery, never as a lossy HTTP bridge.
        url = self.base_url + endpoint if endpoint.startswith("/") else endpoint
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "api.github.com":
            raise ValueError("GitHub requests must stay on api.github.com")
        await self._ensure_client()
        attempts = 4 if method in ("GET", "HEAD") else 1
        for attempt in range(attempts):
            try:
                response = await self._client.request(method, url, **kwargs)
            except httpx.HTTPError:
                if attempt == attempts - 1:
                    raise GitHubAPIError("GitHub transport unavailable") from None
                await asyncio.sleep(2 ** attempt)
                continue
            throttled = response.status_code == 429 or (response.status_code == 403 and
                (response.headers.get("x-ratelimit-remaining") == "0" or "retry-after" in response.headers))
            if (throttled or response.status_code >= 500) and attempt < attempts - 1:
                try:
                    delay = max(1, min(60, float(response.headers.get("retry-after", 2 ** attempt))))
                except ValueError:
                    delay = 2 ** attempt
                await asyncio.sleep(delay)
                continue
            return response

    async def _json(self, method, endpoint, **kwargs):
        response = await self._request(method, endpoint, **kwargs)
        if not 200 <= response.status_code < 300:
            raise GitHubAPIError(f"GitHub {method} failed with HTTP {response.status_code}")
        return response.json() if response.content else {}

    async def _pages(self, endpoint, params=None):
        items = []
        for page in range(1, 21):
            data = await self._json("GET", endpoint, params={**(params or {}), "per_page": 100, "page": page})
            if not isinstance(data, list):
                raise GitHubAPIError("Invalid GitHub collection response")
            items.extend(data)
            if len(data) < 100:
                return items
        raise GitHubAPIError("GitHub collection exceeds processing bound; narrow the scope")

    async def get_current_user(self):
        return await self._json("GET", "/user")

    async def get_rate_limit(self):
        data = await self._json("GET", "/rate_limit")
        rate = data.get("resources", {}).get("core", data.get("rate", {}))
        if type(rate.get("remaining")) is not int or type(rate.get("limit")) is not int:
            raise GitHubAPIError("GitHub quota unavailable")
        return {**rate, "resources": data.get("resources", {})}

    async def get_notifications(self, all_notifications=False, participating=False):
        return await self._pages("/notifications", {"all": str(all_notifications).lower(), "participating": str(participating).lower()})

    async def mark_notification_read(self, thread_id):
        if self.config.dry_run:
            return True
        await self._json("PATCH", f"/notifications/threads/{thread_id}")
        return True

    async def mark_notification_done(self, thread_id):
        if self.config.dry_run:
            return True
        await self._json("DELETE", f"/notifications/threads/{thread_id}")
        return True

    async def get_resource_by_url(self, url):
        return await self._json("GET", url)

    async def get_issue_comments(self, comments_url):
        return await self._pages(comments_url)

    async def post_issue_comment(self, owner, repo, issue_number, body):
        if self.config.dry_run:
            return {"id": "simulation", "body": body, "dry_run": True}
        return await self._json("POST", f"/repos/{owner}/{repo}/issues/{issue_number}/comments", json={"body": body})

    async def _graphql(self, query, variables):
        data = await self._json("POST", "/graphql", json={"query": query, "variables": variables})
        if data.get("errors") or not isinstance(data.get("data"), dict):
            raise GitHubAPIError("GitHub GraphQL operation failed")
        return data["data"]

    async def get_discussion(self, owner, repo, discussion_number):
        query = "query($owner:String!,$repo:String!,$number:Int!){repository(owner:$owner,name:$repo){discussion(number:$number){id title body url}}}"
        data = await self._graphql(query, {"owner": owner, "repo": repo, "number": discussion_number})
        discussion = data.get("repository", {}).get("discussion")
        if not discussion:
            raise GitHubAPIError("Discussion unavailable")
        return {**discussion, "node_id": discussion["id"]}

    async def get_discussion_comments(self, owner, repo, discussion_number):
        query = "query($owner:String!,$repo:String!,$number:Int!,$cursor:String){repository(owner:$owner,name:$repo){discussion(number:$number){comments(first:100,after:$cursor){nodes{body author{login}} pageInfo{hasNextPage endCursor}}}}}"
        cursor, comments = None, []
        for _ in range(20):
            data = await self._graphql(query, {"owner": owner, "repo": repo, "number": discussion_number, "cursor": cursor})
            conn = data["repository"]["discussion"]["comments"]
            comments.extend({"body": c["body"], "user": {"login": (c.get("author") or {}).get("login", "")}} for c in conn["nodes"])
            if not conn["pageInfo"]["hasNextPage"]:
                return comments
            cursor = conn["pageInfo"]["endCursor"]
        raise GitHubAPIError("Discussion exceeds processing bound")

    async def post_discussion_comment(self, owner, repo, discussion_number, body, discussion_node_id=None):
        if self.config.dry_run:
            return {"id": "simulation", "body": body, "dry_run": True}
        if not discussion_node_id:
            discussion_node_id = (await self.get_discussion(owner, repo, discussion_number))["node_id"]
        query = "mutation($id:ID!,$body:String!){addDiscussionComment(input:{discussionId:$id,body:$body}){comment{id url}}}"
        return (await self._graphql(query, {"id": discussion_node_id, "body": body}))["addDiscussionComment"]["comment"]

    async def search_issues(self, query, sort="updated", order="desc", per_page=30):
        data = await self._json("GET", "/search/issues", params={"q": query, "sort": sort, "order": order, "per_page": min(per_page, 100)})
        return data.get("items", [])

    async def get_repository(self, owner, repo):
        return await self._json("GET", f"/repos/{owner}/{repo}")

    async def get_issue(self, owner, repo, number):
        return await self._json("GET", f"/repos/{owner}/{repo}/issues/{number}")

    async def has_linked_pr(self, owner, repo, number):
        query = "query($owner:String!,$repo:String!,$number:Int!,$cursor:String){repository(owner:$owner,name:$repo){issue(number:$number){timelineItems(first:100,after:$cursor,itemTypes:[CROSS_REFERENCED_EVENT]){nodes{... on CrossReferencedEvent{source{... on PullRequest{state}}}} pageInfo{hasNextPage endCursor}}}}}"
        cursor = None
        for _ in range(20):
            data = await self._graphql(query, {"owner": owner, "repo": repo, "number": number, "cursor": cursor})
            conn = data["repository"]["issue"]["timelineItems"]
            if any((node.get("source") or {}).get("state") == "OPEN" for node in conn["nodes"]):
                return True
            if not conn["pageInfo"]["hasNextPage"]:
                return False
            cursor = conn["pageInfo"]["endCursor"]
        # Never assume no conflicts after incomplete traversal.
        return True

    async def check_issue_eligibility(self, owner, repo, number):
        issue = await self.get_issue(owner, repo, number)
        if issue.get("state") != "open" or issue.get("locked") or issue.get("assignees") or issue.get("pull_request"):
            return False, "Issue closed, assigned, locked, or a pull request"
        metadata = await self.get_repository(owner, repo)
        if metadata.get("archived") or metadata.get("disabled") or metadata.get("stargazers_count", 0) < self.config.min_repo_stars:
            return False, "Repository is ineligible"
        if await self.has_linked_pr(owner, repo, number):
            return False, "Issue already has an open linked pull request"
        return True, "Eligible"

    async def ensure_fork(self, owner, repo):
        user = (await self.get_current_user())["login"]
        if user.lower() == owner.lower():
            return await self.get_repository(owner, repo)
        response = await self._request("GET", f"/repos/{user}/{repo}")
        if response.status_code == 200:
            fork = response.json()
            if not fork.get("fork") or fork.get("parent", {}).get("full_name", "").lower() != f"{owner}/{repo}".lower():
                raise GitHubAPIError("Existing repository is not a fork of the selected upstream")
            return fork
        if response.status_code != 404:
            raise GitHubAPIError("Cannot verify fork")
        await self._json("POST", f"/repos/{owner}/{repo}/forks", json={"default_branch_only": True})
        for _ in range(10):
            await asyncio.sleep(2)
            response = await self._request("GET", f"/repos/{user}/{repo}")
            if response.status_code == 200:
                return response.json()
        raise GitHubAPIError("Fork creation is still pending; retry later")

    async def create_pull_request(self, owner, repo, title, body, head, base="main", draft=True):
        payload = {"title": title, "body": body, "head": head, "base": base, "draft": draft}
        if self.config.dry_run:
            return {**payload, "html_url": f"https://github.com/{owner}/{repo}/pull/mock-dry-run", "dry_run": True}
        return await self._json("POST", f"/repos/{owner}/{repo}/pulls", json=payload)
