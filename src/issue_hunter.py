"""Deduplicated issue discovery with repository and linked-activity verification."""
import logging
from .config import config
from .github_client import GitHubClient
from .ai_engine import AIEngine
from .safety_guardrails import SafetyGuardrails
from .status_tracker import status_tracker

logger = logging.getLogger("github_agent.hunter")


class IssueHunter:
    def __init__(self, client=None, safety=None, ai=None, agent_config=None, status=None):
        self.config = agent_config or config
        self.client = client or GitHubClient(self.config)
        self.safety = safety or SafetyGuardrails(self.config)
        self.ai = ai or AIEngine(self.config)
        self.status = status if status is not None else status_tracker

    async def hunt_issues(self, limit=10):
        limit = max(1, min(int(limit), 50))
        candidates, seen, repositories = [], set(), {}
        for language in self.config.target_languages:
            for label in self.config.target_labels:
                query = f'is:issue state:open no:assignee language:{language} label:"{label}"'
                self.status.update_hunter("HUNTING", f"Searching {language} issues", current_query=query)
                items = await self.client.search_issues(query, per_page=30)
                for item in items:
                    url = item.get("html_url", "")
                    if url in seen or not url or item.get("pull_request") or item.get("locked") or item.get("assignees") or item.get("assignee"):
                        continue
                    seen.add(url)
                    if self.safety.state.is_issue_handled(url):
                        continue
                    repository = item.get("repository_url", "").removeprefix("https://api.github.com/repos/")
                    if repository.count("/") != 1 or not repository or url != f"https://github.com/{repository}/issues/{item.get('number')}":
                        continue
                    owner, name = repository.split("/")
                    if repository not in repositories:
                        repositories[repository] = await self.client.get_repository(owner, name)
                    metadata = repositories[repository]
                    if metadata.get("archived") or metadata.get("disabled") or metadata.get("stargazers_count", 0) < self.config.min_repo_stars:
                        continue
                    labels = [v["name"] if isinstance(v, dict) else str(v) for v in item.get("labels", [])]
                    analysis = await self.ai.analyze_issue_actionability(repository, item.get("title", ""), item.get("body") or "", labels)
                    if analysis.get("is_actionable") is not True:
                        continue
                    if await self.client.has_linked_pr(owner, name, item["number"]):
                        continue
                    score = analysis.get("actionability_score", 0)
                    if type(score) not in (int, float) or not 0 <= score <= 1:
                        continue
                    candidates.append({"repo": repository, "issue_number": item["number"], "url": url,
                        "title": item.get("title", ""), "body": item.get("body") or "", "labels": labels,
                        "language": language, "analysis": analysis, "score": score})
                    if len(candidates) >= limit:
                        self.status.update_hunter("IDLE", f"Found {len(candidates)} eligible issues")
                        return sorted(candidates, key=lambda v: v["score"], reverse=True)
        self.status.update_hunter("IDLE", f"Found {len(candidates)} eligible issues")
        return sorted(candidates, key=lambda v: v["score"], reverse=True)
