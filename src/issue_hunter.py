"""Issue Hunter: Finds high-signal open issues across top-tier open-source repositories."""

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from .ai_engine import AIEngine
    from .config import AgentConfig, config
    from .github_client import GitHubClient
    from .safety_guardrails import SafetyGuardrails
    from .status_tracker import StatusTracker, status_tracker
else:
    try:
        from .ai_engine import AIEngine
        from .config import AgentConfig, config
        from .github_client import GitHubClient
        from .safety_guardrails import SafetyGuardrails
        from .status_tracker import StatusTracker, status_tracker
    except ImportError:
        from ai_engine import AIEngine
        from config import AgentConfig, config
        from github_client import GitHubClient
        from safety_guardrails import SafetyGuardrails
        from status_tracker import StatusTracker, status_tracker

logger = logging.getLogger("github_agent.hunter")


class IssueHunter:
    """Discovers high-quality, actionable open issues in top open-source projects."""

    def __init__(
        self,
        client: Optional[GitHubClient] = None,
        safety: Optional[SafetyGuardrails] = None,
        ai: Optional[AIEngine] = None,
        agent_config: Optional[AgentConfig] = None,
        status: Optional[StatusTracker] = None,
    ):
        self.config = agent_config or config
        self.client = client or GitHubClient(self.config)
        self.safety = safety or SafetyGuardrails(self.config)
        self.ai = ai or AIEngine(self.config)
        self.status = status if status is not None else status_tracker

    async def hunt_issues(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Search GitHub for top-tier unassigned bug/help-wanted issues."""
        candidates = []
        limit = max(1, min(int(limit or 10), 50))
        self.status.update_hunter("HUNTING", "Scanning GitHub for top-tier open-source bug issues...")

        for lang in self.config.target_languages:
            for label in self.config.target_labels:
                stars_clause = f"stars:>={self.config.min_repo_stars} " if self.config.min_repo_stars > 0 else ""
                query = f"state:open no:assignee language:{lang} {stars_clause}label:\"{label}\""
                self.status.update_hunter("HUNTING", f"Searching {lang.upper()} issues (label: {label})...", current_query=query)
                logger.info(f"Searching issues: {query}")
                try:
                    items = await self.client.search_issues(query=query, sort="updated", order="desc", per_page=10)
                except Exception as e:
                    logger.warning(f"Issue search failed for {query}: {e}")
                    continue

                for item in items:
                    html_url = item.get("html_url", "")
                    if not html_url or self.safety.state.is_issue_handled(html_url):
                        continue

                    # Filter out locked or assigned items
                    if item.get("locked") or item.get("assignee") or item.get("assignees"):
                        continue

                    title = item.get("title", "") or ""
                    body = item.get("body", "") or ""
                    labels = [
                        (l.get("name", "") if isinstance(l, dict) else str(l))
                        for l in item.get("labels", [])
                    ]
                    repo_url = item.get("repository_url", "") or ""
                    url_parts = [p for p in repo_url.rstrip("/").split("/") if p]
                    if len(url_parts) < 2:
                        continue
                    owner_repo = "/".join(url_parts[-2:])
                    if "/" not in owner_repo or owner_repo.startswith("/"):
                        continue
                    issue_number = item.get("number")
                    if not isinstance(issue_number, int):
                        continue

                    # Assess actionability
                    try:
                        analysis = await self.ai.analyze_issue_actionability(
                            repo=owner_repo,
                            title=title,
                            body=body,
                            labels=labels,
                        )
                    except Exception as e:
                        logger.warning(f"AI analysis failed for {owner_repo}: {e}")
                        continue

                    if analysis.get("is_actionable"):
                        try:
                            score = float(analysis.get("actionability_score", 0.5))
                        except (ValueError, TypeError):
                            score = 0.5
                        candidates.append(
                            {
                                "issue_number": issue_number,
                                "repo": owner_repo,
                                "title": title,
                                "language": lang,
                                "url": html_url,
                                "body": body,
                                "labels": labels,
                                "analysis": analysis,
                                "score": score,
                            }
                        )

                    if len(candidates) >= limit:
                        break

                if len(candidates) >= limit:
                    break

            if len(candidates) >= limit:
                break

        # Sort candidates by actionability score descending
        candidates.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        return candidates[:limit]
