"""Issue Hunter: Finds high-signal open issues across top-tier open-source repositories."""

import logging
from typing import Any, Dict, List, Optional

try:
    from .ai_engine import AIEngine
    from .config import AgentConfig, config
    from .github_client import GitHubClient
    from .safety_guardrails import SafetyGuardrails
    from .status_tracker import status_tracker
except ImportError:
    from ai_engine import AIEngine
    from config import AgentConfig, config
    from github_client import GitHubClient
    from safety_guardrails import SafetyGuardrails
    from status_tracker import status_tracker

logger = logging.getLogger("github_agent.hunter")


class IssueHunter:
    """Discovers high-quality, actionable open issues in top open-source projects."""

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

    async def hunt_issues(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Search GitHub for top-tier unassigned bug/help-wanted issues."""
        candidates = []
        status_tracker.update_hunter("HUNTING", "Scanning GitHub for top-tier open-source bug issues...")

        for lang in self.config.target_languages:
            for label in self.config.target_labels:
                stars_clause = f"stars:>={self.config.min_repo_stars} " if self.config.min_repo_stars > 0 else ""
                query = f"state:open no:assignee language:{lang} {stars_clause}label:\"{label}\""
                status_tracker.update_hunter("HUNTING", f"Searching {lang.upper()} issues (label: {label})...", current_query=query)
                logger.info(f"Searching issues: {query}")
                items = await self.client.search_issues(query=query, sort="updated", order="desc", per_page=10)

                for item in items:
                    html_url = item.get("html_url", "")
                    if not html_url or self.safety.state.is_issue_handled(html_url):
                        continue

                    # Filter out locked or assigned items
                    if item.get("locked") or item.get("assignee") or item.get("assignees"):
                        continue

                    title = item.get("title", "")
                    body = item.get("body", "") or ""
                    labels = [
                        (l.get("name", "") if isinstance(l, dict) else str(l))
                        for l in item.get("labels", [])
                    ]
                    repo_url = item.get("repository_url", "")
                    owner_repo = "/".join(repo_url.rstrip("/").split("/")[-2:])

                    # Assess actionability
                    analysis = await self.ai.analyze_issue_actionability(
                        repo=owner_repo,
                        title=title,
                        body=body,
                        labels=labels,
                    )

                    if analysis.get("is_actionable"):
                        candidates.append(
                            {
                                "issue_number": item.get("number"),
                                "repo": owner_repo,
                                "title": title,
                                "language": lang,
                                "url": html_url,
                                "body": body,
                                "labels": labels,
                                "analysis": analysis,
                                "score": analysis.get("actionability_score", 0.5),
                            }
                        )

                    if len(candidates) >= limit:
                        break

                if len(candidates) >= limit:
                    break

            if len(candidates) >= limit:
                break

        # Sort candidates by actionability score descending
        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[:limit]
