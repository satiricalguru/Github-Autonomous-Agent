"""Inbox actions preserve failed/unverified work instead of hiding it."""
import asyncio
import re
from .config import config
from .github_client import GitHubClient
from .ai_engine import AIEngine
from .safety_guardrails import SafetyGuardrails
from .status_tracker import status_tracker
from .task_tracker import task_tracker


class InboxManager:
    def __init__(self, client=None, safety=None, ai=None, agent_config=None, status=None, tasks=None):
        self.config = agent_config or config
        self.client = client or GitHubClient(self.config)
        self.safety = safety or SafetyGuardrails(self.config)
        self.ai = ai or AIEngine(self.config)
        self.status = status if status is not None else status_tracker
        self.tasks = tasks if tasks is not None else task_tracker
        self._dry_run_handled = set()

    async def process_inbox(self):
        self.status.update_inbox("POLLING", "Fetching GitHub notifications")
        notifications = await self.client.get_notifications(all_notifications=self.config.check_read_discussions)
        results = []
        for notification in notifications:
            thread = str(notification.get("id", ""))
            if not re.fullmatch(r"[A-Za-z0-9_-]+", thread):
                continue
            if self.config.dry_run and thread in self._dry_run_handled:
                continue
            if not notification.get("unread", True) and self.safety.state.is_notification_handled(thread):
                continue
            subject = notification.get("subject") or {}
            repository = notification.get("repository", {}).get("full_name", "")
            if repository.count("/") != 1:
                continue
            owner, repo = repository.split("/")
            title, kind, url = subject.get("title", "Untitled"), subject.get("type", "Unknown"), subject.get("url", "")
            task = self.tasks.create_task("INBOX", title, repository, url,
                {"thread_id": thread, "dry_run": self.config.dry_run, "subject_type": kind})
            try:
                self.status.update_inbox("TRIAGING", f"Evaluating {repository}: {title}")
                match = re.fullmatch(r"https://api\.github\.com/repos/([^/]+)/([^/]+)/(issues|pulls|discussions)/(\d+)", url)
                comments, node = [], None
                if not match or match.group(1, 2) != (owner, repo):
                    raise RuntimeError("Unsupported notification resource; requires manual review")
                number = int(match[4])
                discussion = match[3] == "discussions" or kind == "Discussion"
                if discussion:
                    resource = await self.client.get_discussion(owner, repo, number)
                    node = resource["node_id"]
                    comments = await self.client.get_discussion_comments(owner, repo, number)
                else:
                    resource = await self.client.get_resource_by_url(url)
                    comments = await self.client.get_issue_comments(resource["comments_url"])
                latest_author = (comments[-1].get("user", {}).get("login", "").lower() if comments else "")
                if latest_author and latest_author == (self.config.github_username or "").lower():
                    evaluation = {"should_respond": False, "rationale": "User already replied", "provider_verified": True}
                else:
                    evaluation = await self.ai.evaluate_notification(repository, title, notification.get("reason", ""), "Discussion" if discussion else kind, comments, body=resource.get("body") or "")
                if evaluation.get("needs_attention") or evaluation.get("provider_verified") is not True:
                    raise RuntimeError(evaluation.get("rationale", "Model evaluation unavailable"))
                action = "reviewed"
                if evaluation.get("should_respond"):
                    if discussion and not self.config.engage_discussions:
                        raise RuntimeError("Discussion replies are disabled; review manually")
                    reply = self.safety.sanitize_comment(evaluation.get("suggested_reply", ""))
                    safe, reason = self.safety.validate_content_safety(reply)
                    if not safe or evaluation.get("confidence", 0) < 0.85:
                        raise RuntimeError(reason if not safe else "Reply confidence is below threshold")
                    if discussion:
                        posted = await self.client.post_discussion_comment(owner, repo, number, reply, node)
                    else:
                        posted = await self.client.post_issue_comment(owner, repo, number, reply)
                    if not posted:
                        raise RuntimeError("Reply failed; notification preserved")
                    action = "replied (discussion)" if discussion else "replied"
                if not await self.client.mark_notification_read(thread):
                    raise RuntimeError("Mark-read failed; notification preserved")
                if not await self.client.mark_notification_done(thread):
                    raise RuntimeError("Archive failed; notification preserved")
                if self.config.dry_run:
                    self._dry_run_handled.add(thread)
                else:
                    self.safety.state.mark_notification_handled(thread)
                self.tasks.complete_task(task, "COMPLETED", action.title(), {"evaluation": evaluation, "action_taken": action})
                self.status.log_event("INBOX", f"{action}: {repository} — {title}")
                results.append({"thread_id": thread, "repo": repository, "title": title, "action": action, "evaluation": evaluation})
            except asyncio.CancelledError:
                self.tasks.complete_task(task, "CANCELLED", "Execution cancelled; notification preserved")
                raise
            except Exception as error:
                message = str(error) if isinstance(error, (ValueError, RuntimeError)) else f"Inbox operation failed ({type(error).__name__})"
                self.tasks.complete_task(task, "FAILED", message)
                self.status.log_event("ERROR", message)
        self.status.update_inbox("IDLE", f"Handled {len(results)} notifications; unresolved threads preserved", handled_count=len(results))
        return results

    async def mark_all_completed_done(self):
        self.safety.state._load()
        count = 0
        for thread in self.safety.state.handled_notifications:
            if await self.client.mark_notification_done(thread):
                count += 1
        return count
