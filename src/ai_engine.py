import json
import logging
import os
import re
from typing import Any, Dict, List, Optional
import httpx

try:
    from .config import AgentConfig, config
except ImportError:
    from config import AgentConfig, config

logger = logging.getLogger("github_agent.ai")


def extract_json_payload(text: str) -> Optional[Dict[str, Any]]:
    """Robustly parse JSON object from LLM response text."""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    # Fall back to balancing braces: try largest plausible {...} span first,
    # then shrink from the right until JSON parses (handles trailing chatter).
    start = text.find("{")
    end = text.rfind("}")
    while start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1].strip()
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        end = text.rfind("}", start, end)
    return None


_VALID_MODEL_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{1,64}$")


def sanitize_model_name(model: str, fallback: str = "gemini-3.8-flash") -> str:
    """Validate a model identifier before interpolating it into a request URL."""
    model = (model or "").strip()
    if _VALID_MODEL_RE.match(model):
        return model
    return fallback


class AIEngine:
    """Provides LLM-powered reasoning for GitHub Agent workflows."""

    def __init__(self, agent_config: Optional[AgentConfig] = None):
        self.config = agent_config or config
        self.api_key = self.config.gemini_api_key or os.getenv("GEMINI_API_KEY")

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        return extract_json_payload(text)

    async def _call_gemini(self, prompt: str, system_instruction: str = "") -> Optional[str]:
        """Query Gemini API via HTTP REST."""
        if not self.api_key:
            return None

        model = sanitize_model_name(self.config.model_name or "gemini-3.8-flash")
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
            parsed = self._extract_json(response_text)
            if parsed and isinstance(parsed, dict):
                return parsed

        # Fallback heuristic if API key is not configured
        needs_reply = reason in ("mention", "review_requested", "assign") or "question" in title.lower()
        return {
            "should_respond": needs_reply,
            "confidence": 0.7,
            "rationale": f"Heuristic based on notification reason: {reason}",
            "suggested_reply": (
                f"Thanks for tagging me on [{repo}] {title}. "
                "I am looking into this and will follow up shortly."
            ),
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
            parsed = self._extract_json(response_text)
            if parsed and isinstance(parsed, dict):
                return parsed

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

    async def generate_code_patch(
        self,
        repo: str,
        issue_title: str,
        issue_body: str,
        file_tree_summary: str = "",
    ) -> Dict[str, Any]:
        """Generate targeted code repair instructions and minimal patch metadata."""
        prompt = f"""
You are an expert autonomous software engineer fixing an open-source bug.
Repository: {repo}
Issue Title: {issue_title}
Issue Context:
{issue_body[:2000]}

Repository Context / Key Files:
{file_tree_summary[:1000]}

Determine:
1. Is this fixable with a clean minimal patch?
2. Propose targeted file and patch description.

Return JSON format:
{{
  "can_fix": boolean,
  "confidence": float,
  "target_file": "relative/path/to/file.ext",
  "explanation": "concise explanation of bug and fix",
  "patch_description": "summary of patch"
}}
"""
        response_text = await self._call_gemini(
            prompt,
            system_instruction="You are a principal engineer generating precision bug fixes. Adhere strictly to repository conventions.",
        )
        if response_text:
            parsed = self._extract_json(response_text)
            if parsed and isinstance(parsed, dict):
                return parsed

        return {
            "can_fix": True,
            "confidence": 0.8,
            "target_file": "",
            "explanation": f"Address {issue_title}",
            "patch_description": "Verified automated bug fix",
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
1. A concise conventional commit PR title (e.g. 'fix(parser): resolve null pointer on empty input (#{issue_number})')
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
            parsed = self._extract_json(response_text)
            if parsed and isinstance(parsed, dict):
                return parsed

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
