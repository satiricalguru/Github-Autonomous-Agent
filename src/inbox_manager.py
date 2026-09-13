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
        """Fetch and process GitHub notifications, including unread and read discussions."""
        results = []
        self.status.update_inbox("POLLING", "Fetching notifications from GitHub...")
        notifications = await self.client.get_notifications(all_notifications=False)
        notifications = list(notifications or [])

        # Also inspect read/all notifications for discussions to engage if configured
        if getattr(self.config, "check_read_discussions", True):
            try:
                all_notifs = await self.client.get_notifications(all_notifications=True)
                unread_ids = {str(n.get("id", "")) for n in notifications}
                for n in (all_notifs or []):
                    nid = str(n.get("id", ""))
                    if nid and nid not in unread_ids:
                        subj = n.get("subject", {}) or {}
                        stype = subj.get("type", "")
                        surl = subj.get("url", "") or ""
                        if stype == "Discussion" or "/discussions/" in surl:
                            if not self.safety.state.is_notification_handled(nid):
                                notifications.append(n)
            except Exception as e:
                logger.warning(f"Failed fetching read discussions: {e}")

        if not notifications:
            logger.info("Inbox clean: No pending notifications or discussions.")
            self.status.update_inbox("IDLE", "Inbox clean (0 pending notifications)")
            return []

        logger.info(f"Found {len(notifications)} notification(s) to triage. Processing...")
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

            # Fetch issue/PR or discussion context
            comments = []
            issue_number = None
            discussion_number = None
            discussion_node_id = None
            is_discussion = (subject_type == "Discussion") or (isinstance(subject_url, str) and "/discussions/" in subject_url)

            if subject_url and isinstance(subject_url, str):
                try:
                    parts = [p for p in subject_url.rstrip("/").split("/") if p]
                    if parts and parts[-1].isdigit():
                        num = int(parts[-1])
                        if "/issues/" in subject_url or "/pulls/" in subject_url:
                            issue_number = num
                            resource_data = await self.client.get_resource_by_url(subject_url)
                            if resource_data and "comments_url" in resource_data:
                                comments = await self.client.get_issue_comments(
                                    resource_data["comments_url"]
                                )
                        elif is_discussion and "/" in repo_name:
                            discussion_number = num
                            owner, repo = repo_name.split("/", 1)
                            disc_data = await self.client.get_discussion(owner, repo, discussion_number)
                            if disc_data:
                                discussion_node_id = disc_data.get("node_id")
                            comments = await self.client.get_discussion_comments(owner, repo, discussion_number)
                except Exception as e:
                    logger.warning(f"Could not load resource context for {subject_url}: {e}")

            # AI Evaluation
            evaluation = await self.ai.evaluate_notification(
                repo=repo_name,
                title=subject_title,
                reason=reason,
                subject_type="Discussion" if is_discussion else subject_type,
                last_comments=comments,
            )

            action_taken = "reviewed"
            reply_text = evaluation.get("suggested_reply", "")

            if evaluation.get("should_respond") and reply_text:
                # Sanitize and check safety
                sanitized_reply = self.safety.sanitize_comment(reply_text)
                is_safe, reason_msg = self.safety.validate_content_safety(sanitized_reply)

                if is_safe and "/" in repo_name:
                    owner, repo = repo_name.split("/", 1)
                    if issue_number is not None:
                        logger.info(f"Replying to issue/PR {repo_name}#{issue_number}: {sanitized_reply}")
                        post_res = await self.client.post_issue_comment(
                            owner=owner, repo=repo, issue_number=issue_number, body=sanitized_reply
                        )
                        if post_res:
                            action_taken = "replied"
                    elif is_discussion and discussion_number is not None:
                        logger.info(f"Replying to discussion {repo_name}#{discussion_number}: {sanitized_reply}")
                        post_res = await self.client.post_discussion_comment(
                            owner=owner,
                            repo=repo,
                            discussion_number=discussion_number,
                            body=sanitized_reply,
                            discussion_node_id=discussion_node_id,
                        )
                        if post_res:
                            action_taken = "replied (discussion)"
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

    async def mark_all_completed_done(self) -> int:
        """Mark all handled notifications and completed tasks as Done in GitHub inbox."""
        done_count = 0
        marked_threads = set()

        # 1. Mark all thread IDs stored in safety state as done
        for thread_id in list(self.safety.state.handled_notifications):
            if thread_id and thread_id not in marked_threads:
                try:
                    success = await self.client.mark_notification_done(str(thread_id))
                    if success:
                        done_count += 1
                        marked_threads.add(thread_id)
                except Exception as e:
                    logger.debug(f"Failed marking thread {thread_id} done: {e}")

        # 2. Also inspect any active notifications returned by GitHub API
        try:
            notifications = await self.client.get_notifications(all_notifications=True)
            for notif in (notifications or []):
                thread_id = str(notif.get("id", ""))
                if thread_id and thread_id not in marked_threads:
                    await self.client.mark_notification_read(thread_id)
                    success = await self.client.mark_notification_done(thread_id)
                    if success:
                        self.safety.state.mark_notification_handled(thread_id)
                        done_count += 1
                        marked_threads.add(thread_id)
        except Exception as e:
            logger.warning(f"Error fetching/marking notifications as done: {e}")

        return done_count
