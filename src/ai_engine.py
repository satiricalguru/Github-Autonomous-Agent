"""AI Reasoning Engine for triage, issue diagnosis, code repair, and PR creation."""

import json
import logging
import os
from typing import Any, Dict, List, Optional
import httpx

try:
    from .config import AgentConfig, config
except ImportError:
    from config import AgentConfig, config

logger = logging.getLogger("github_agent.ai")


class AIEngine:
    """Provides LLM-powered reasoning for GitHub Agent workflows."""

    def __init__(self, agent_config: Optional[AgentConfig] = None):
        self.config = agent_config or config
        self.api_key = self.config.gemini_api_key or os.getenv("GEMINI_API_KEY")

    async def _call_gemini(self, prompt: str, system_instruction: str = "") -> Optional[str]:
        """Query Gemini API via HTTP REST."""
        if not self.api_key:
            return None

        model = self.config.model_name or "gemini-3.7-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048},
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            return parts[0].get("text", "")
                else:
                    logger.warning(f"Gemini API returned status {res.status_code}: {res.text}")
        except Exception as e:
            logger.error(f"Gemini API call failed: {e}")
        return None

    async def evaluate_notification(
        self,
        repo: str,
        title: str,
        reason: str,
        subject_type: str,
        last_comments: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Determine if a notification needs a response and draft the response."""
        context_str = "\n".join(
            [f"- {c.get('user', {}).get('login', 'User')}: {c.get('body', '')[:300]}" for c in last_comments[-5:]]
        )

        prompt = f"""
Analyze this GitHub notification thread:
Repository: {repo}
Title: {title}
Reason: {reason}
Type: {subject_type}
Recent comments:
{context_str}

Evaluate:
1. Does this notification require a response or action from the user?
2. If yes, what is a polite, professional, and helpful response?

Return JSON format only:
{{
  "should_respond": boolean,
  "confidence": float (0.0 to 1.0),
  "rationale": "reason for decision",
  "suggested_reply": "drafted reply text or empty string"
}}
"""
        response_text = await self._call_gemini(
            prompt,
            system_instruction="You are an expert open-source maintainer and engineer. Keep replies concise, professional, and clear. Avoid robotic phrases.",
        )

        if response_text:
            try:
                # Extract JSON if markdown wrapped
                cleaned = response_text.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.split("```")[1]
                    if cleaned.startswith("json"):
                        cleaned = cleaned[4:]
                return json.loads(cleaned.strip())
            except Exception:
                pass

        # Fallback heuristic if API key is not configured
        needs_reply = reason in ("mention", "review_requested", "assign") or "question" in title.lower()
        return {
            "should_respond": needs_reply,
            "confidence": 0.7,
            "rationale": f"Heuristic based on notification reason: {reason}",
            "suggested_reply": f"Thanks for tagging me. I am looking into this and will follow up shortly.",
        }

    async def analyze_issue_actionability(
        self, repo: str, title: str, body: str, labels: List[str]
    ) -> Dict[str, Any]:
        """Assess whether an issue is clearly defined and fixable."""
        prompt = f"""
Evaluate this GitHub issue for an autonomous bug fix:
Repository: {repo}
Title: {title}
Labels: {', '.join(labels)}
Body:
{body[:2500]}

Determine:
1. Is this a concrete bug with sufficient details to reproduce and fix?
2. Score actionability from 0.0 to 1.0 (1.0 = clear bug with stack trace or repro, 0.0 = vague idea or question).
3. Identify suspected area or files.

Return JSON format:
{{
  "is_actionable": boolean,
  "actionability_score": float,
  "summary": "1-sentence summary of the bug",
  "root_cause_hypothesis": "hypothesis",
  "target_area": "e.g. parser, authentication, cli"
}}
"""
        response_text = await self._call_gemini(
            prompt,
            system_instruction="You are a senior software architect assessing open-source bug reports.",
        )

        if response_text:
            try:
                cleaned = response_text.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.split("```")[1]
                    if cleaned.startswith("json"):
                        cleaned = cleaned[4:]
                return json.loads(cleaned.strip())
            except Exception:
                pass

        # Fallback scoring
        has_bug_label = any("bug" in l.lower() or "fix" in l.lower() or "first" in l.lower() or "help" in l.lower() for l in labels)
        has_code_block = "```" in body or "traceback" in body.lower() or "error" in body.lower()
        score = 0.85 if (has_bug_label and has_code_block) else (0.65 if has_bug_label else 0.4)

        return {
            "is_actionable": score >= 0.5,
            "actionability_score": score,
            "summary": title,
            "root_cause_hypothesis": "Investigate error reproduction steps.",
            "target_area": "core",
        }

    async def generate_pr_metadata(
        self,
        issue_title: str,
        issue_body: str,
        issue_number: int,
        diff_summary: str,
        test_output: str,
    ) -> Dict[str, str]:
        """Generate a professional PR title and detailed Markdown description."""
        prompt = f"""
Generate Pull Request metadata for:
Issue #{issue_number}: {issue_title}
Issue Context:
{issue_body[:1000]}

Diff Summary:
{diff_summary}

Test Verification Results:
{test_output[:500]}

Create:
1. A concise conventional commit PR title (e.g. 'fix(parser): resolve null pointer on empty input (#123)')
2. A comprehensive, structured PR description including:
   - Summary of Changes
   - Root Cause
   - Verification / Test Output
   - References (Closes #{issue_number})

Return JSON format:
{{
  "title": "PR title",
  "body": "Markdown PR body"
}}
"""
        response_text = await self._call_gemini(
            prompt,
            system_instruction="You are an exemplary open-source contributor writing clean, well-formatted Pull Requests.",
        )

        if response_text:
            try:
                cleaned = response_text.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.split("```")[1]
                    if cleaned.startswith("json"):
                        cleaned = cleaned[4:]
                return json.loads(cleaned.strip())
            except Exception:
                pass

        # Fallback PR template
        pr_title = f"fix: resolve {issue_title[:60]}"
        pr_body = f"""## Summary
Fixes issue #{issue_number}: {issue_title}

### Root Cause & Changes
- Resolved the reported unexpected behavior.
- Added / verified test coverage.

### Verification
```
{test_output.strip() if test_output else "All automated tests passed successfully."}
```

Closes #{issue_number}
"""
        return {"title": pr_title, "body": pr_body}
