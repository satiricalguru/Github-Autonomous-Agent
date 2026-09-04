"""GitHub Inbox & Notification Manager."""

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from rich.console import Console

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

logger = logging.getLogger("github_agent.inbox")
console = Console()


class InboxManager:
    """Manages GitHub inbox notifications, evaluating context and generating smart replies."""

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

    async def process_inbox(self) -> List[Dict[str, Any]]:
        """Fetch and process all unread GitHub notifications."""
        results = []
        self.status.update_inbox("POLLING", "Fetching unread notifications from GitHub...")
        notifications = await self.client.get_notifications(all_notifications=False)

        if not notifications:
            logger.info("Inbox clean: No unread notifications.")
            self.status.update_inbox("IDLE", "Inbox clean (0 unread notifications)")
            return []

        logger.info(f"Found {len(notifications)} unread notification(s). Processing...")
        self.status.update_inbox("PROCESSING", f"Triaging {len(notifications)} notification(s)...")

        for notif in notifications:
            thread_id = str(notif.get("id", ""))
            if not thread_id:
                continue
            repo_name = notif.get("repository", {}).get("full_name", "unknown")
            reason = notif.get("reason", "unknown")
            subject = notif.get("subject", {}) or {}
            subject_title = subject.get("title", "No Title")
            subject_type = subject.get("type", "Unknown")
            subject_url = subject.get("url", "") or ""

            # Check if already processed
            if self.safety.state.is_notification_handled(thread_id):
                continue

            self.status.update_inbox("TRIAGING", f"Evaluating [{repo_name}] {subject_title[:30]}...")
            logger.info(f"Triage: [{repo_name}] {subject_type} - {subject_title} (Reason: {reason})")

            # Fetch issue/PR context if available
            comments = []
            issue_number = None
            if subject_url and isinstance(subject_url, str) and ("/issues/" in subject_url or "/pulls/" in subject_url):
                try:
                    parts = subject_url.rstrip("/").split("/")
                    issue_number = int(parts[-1])
                    resource_data = await self.client.get_resource_by_url(subject_url)
                    if resource_data and "comments_url" in resource_data:
                        comments = await self.client.get_issue_comments(
                            resource_data["comments_url"]
                        )
                except Exception as e:
                    logger.warning(f"Could not load comments for {subject_url}: {e}")

            # AI Evaluation
            evaluation = await self.ai.evaluate_notification(
                repo=repo_name,
                title=subject_title,
                reason=reason,
                subject_type=subject_type,
                last_comments=comments,
            )

            action_taken = "reviewed"
            reply_text = evaluation.get("suggested_reply", "")

            if evaluation.get("should_respond") and reply_text and issue_number:
                # Sanitize and check safety
                sanitized_reply = self.safety.sanitize_comment(reply_text)
                is_safe, reason_msg = self.safety.validate_content_safety(sanitized_reply)

                if is_safe and "/" in repo_name:
                    owner, repo = repo_name.split("/", 1)
                    logger.info(f"Replying to {repo_name}#{issue_number}: {sanitized_reply}")
                    post_res = await self.client.post_issue_comment(
                        owner=owner, repo=repo, issue_number=issue_number, body=sanitized_reply
                    )
                    if post_res:
                        action_taken = "replied"
                elif not is_safe:
                    logger.warning(f"Reply rejected by safety guardrail: {reason_msg}")

            task_id = self.tasks.create_task(
                category="INBOX",
                title=f"Triage {subject_type}: {subject_title}",
                target_repo=repo_name,
                target_url=subject_url,
                details={"reason": reason, "subject_type": subject_type},
            )

            # Mark as read, done (archived from inbox), and handled
            await self.client.mark_notification_read(thread_id)
            if hasattr(self.client, "mark_notification_done"):
                done_coro = self.client.mark_notification_done(thread_id)
                if hasattr(done_coro, "__await__"):
                    await done_coro
            self.safety.state.mark_notification_handled(thread_id)
            self.status.log_event("INBOX", f"{action_taken.title()} on [{repo_name}] {subject_title[:40]}")
            self.tasks.complete_task(
                task_id=task_id,
                status="COMPLETED",
                outcome=f"{action_taken.title()}: {evaluation.get('rationale', 'Evaluated with AI')}",
                details_update={"evaluation": evaluation, "action_taken": action_taken},
            )

            results.append(
                {
                    "thread_id": thread_id,
                    "repo": repo_name,
                    "title": subject_title,
                    "reason": reason,
                    "action": action_taken,
                    "evaluation": evaluation,
                }
            )

        self.status.update_inbox("IDLE", "Inbox triage completed", handled_count=len(self.safety.state.handled_notifications))
        return results
