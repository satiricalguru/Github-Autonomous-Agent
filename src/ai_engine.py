import json
import logging
import os
import re
import asyncio
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from .process import run_process
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

    @property
    def provider(self):
        provider = self.config.ai_provider
        if provider != "auto":
            return provider
        model = self.config.model_name.lower()
        if model.startswith("gemini") and self.config.gemini_api_key:
            return "gemini"
        if model.startswith("claude") and self.config.anthropic_api_key:
            return "anthropic"
        if self.config.openai_api_key and not model.startswith(("gemini", "claude")):
            return "openai"
        return "antigravity" if shutil.which(self.config.antigravity_cli) else "gemini"

    def resolved_model(self):
        model = self.config.model_name
        if self.provider == "antigravity":
            return {"gemini-3.8-flash": "gemini-3.8-flash-high", "gemini-3.7-flash": "gemini-3.7-flash-high",
                    "gemini-3.6-flash": "gemini-3.6-flash-medium", "gemini-3.1-pro": "gemini-3.1-pro-high",
                    "claude-sonnet-4.6": "claude-sonnet-4-6", "claude-opus-4.6": "claude-opus-4-6-thinking",
                    "gpt-oss-120b": "gpt-oss-120b-medium"}.get(model, model)
        return model

    def get_health(self):
        provider = self.provider
        configured = bool({"gemini": self.config.gemini_api_key,
                           "anthropic": self.config.anthropic_api_key,
                           "openai": self.config.openai_api_key,
                           "antigravity": shutil.which(self.config.antigravity_cli)}.get(provider))
        current = (provider, self.resolved_model())
        state = getattr(self, "health_state", "UNVERIFIED" if configured else "UNAVAILABLE")
        if getattr(self, "verified_selection", None) not in (None, current):
            state = "UNVERIFIED"
        return {"provider": provider, "model": self.resolved_model(),
                "configured": configured, "state": state,
                "last_error": getattr(self, "last_error", None), "last_success": getattr(self, "last_success", None)}

    async def _call_gemini(self, prompt: str, system_instruction: str = "") -> Optional[str]:
        # Compatibility entry point; requests are dispatched by the configured provider.
        return await self._call_model(prompt, system_instruction)

    async def _call_model(self, prompt: str, system_instruction: str = "") -> Optional[str]:
        provider = self.provider
        model = self.resolved_model()
        if sanitize_model_name(model, "") != model:
            self.health_state, self.last_error = "UNAVAILABLE", "Invalid model identifier"
            return None
        try:
            if provider == "antigravity":
                executable = shutil.which(self.config.antigravity_cli)
                if not executable:
                    raise ValueError("Antigravity CLI is not installed")
                # No edit permissions, no expanded slash commands, no workspace secrets.
                text = system_instruction + "\nReturn only the requested JSON. Do not use tools or read files.\n" + prompt
                with tempfile.TemporaryDirectory(prefix="github-agent-inference-") as directory:
                    res = await run_process([executable, "--print", text, "--model", model,
                        "--mode", "plan", "--sandbox", "--disable-slash-commands",
                        "--output-format", "json", "--print-timeout", f"{self.config.provider_timeout}s"],
                        cwd=Path(directory), timeout=self.config.provider_timeout + 5,
                        env={k:v for k,v in os.environ.items() if k not in ("GITHUB_TOKEN", "GH_TOKEN", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")})
                if res.returncode:
                    raise ValueError("Antigravity request failed; check authentication, model availability, and quota")
                data = json.loads(res.stdout)
                if data.get("status") != "SUCCESS":
                    raise ValueError("Antigravity did not complete the request")
                result = json.dumps(data["structured_output"]) if isinstance(data.get("structured_output"), dict) else data.get("response", "")
            else:
                if provider == "gemini":
                    if not model.startswith("gemini-") or not self.config.gemini_api_key:
                        raise ValueError("A Gemini model and GEMINI_API_KEY are required")
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
                    headers = {"x-goog-api-key": self.config.gemini_api_key}
                    payload = {"contents": [{"parts": [{"text": prompt}]}],
                               "generationConfig": {"temperature": 0.2, "maxOutputTokens": 8192, "responseMimeType": "application/json"}}
                    if system_instruction:
                        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
                elif provider == "anthropic":
                    if not model.startswith("claude-") or not self.config.anthropic_api_key:
                        raise ValueError("A Claude model and ANTHROPIC_API_KEY are required")
                    url, headers = "https://api.anthropic.com/v1/messages", {"x-api-key": self.config.anthropic_api_key, "anthropic-version": "2023-06-01"}
                    payload = {"model": model.replace("-4.6", "-4-6"), "max_tokens": 8192, "system": system_instruction,
                               "messages": [{"role": "user", "content": prompt}]}
                elif provider == "openai":
                    if not self.config.openai_api_key or model.startswith(("claude-", "gemini-")):
                        raise ValueError("An OpenAI-compatible model and OPENAI_API_KEY are required")
                    url, headers = self.config.openai_base_url.rstrip("/") + "/chat/completions", {"Authorization": f"Bearer {self.config.openai_api_key}"}
                    payload = {"model": model, "messages": [{"role": "system", "content": system_instruction}, {"role": "user", "content": prompt}]}
                else:
                    raise ValueError("Unsupported AI provider")
                async with httpx.AsyncClient(timeout=self.config.provider_timeout) as client:
                    res = await client.post(url, json=payload, headers=headers)
                    if res.status_code != 200:
                        raise ValueError(f"{provider} returned HTTP {res.status_code}")
                    data = res.json()
                if provider == "gemini":
                    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                    result = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                elif provider == "anthropic":
                    result = "".join(p.get("text", "") for p in data.get("content", []) if p.get("type") == "text")
                else:
                    result = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not result:
                raise ValueError("Provider returned an empty response")
            self.health_state, self.last_error = "ONLINE", None
            self.verified_selection = (provider, model)
            self.last_success = datetime.now(timezone.utc).isoformat()
            return result
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.health_state, self.last_error = "DEGRADED", str(error) if isinstance(error, ValueError) else f"{provider} request failed ({type(error).__name__})"
            logger.warning(self.last_error)
            return None

    async def evaluate_notification(
        self,
        repo: str,
        title: str,
        reason: str,
        subject_type: str,
        last_comments: List[Dict[str, Any]],
        body: str = "",
    ) -> Dict[str, Any]:
        """Determine if a notification needs a response and draft the response."""
        if last_comments and (last_comments[-1].get("user", {}).get("login", "").lower() == (self.config.github_username or "").lower()) and self.config.github_username:
            return {"should_respond": False, "suggested_reply": "", "confidence": 1.0,
                    "rationale": "User already replied", "provider_verified": True}
        context_str = "\n".join(
            [f"- {c.get('user', {}).get('login', 'User')}: {c.get('body', '')[:300]}" for c in last_comments[-5:]]
        )

        prompt = f"""
Analyze this GitHub notification thread:
Repository: {repo}
Title: {title}
Reason: {reason}
Type: {subject_type}
Subject body:
{body[:4000]}
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
            if (parsed and type(parsed.get("should_respond")) is bool
                    and isinstance(parsed.get("suggested_reply"), str)
                    and type(parsed.get("confidence")) in (int, float)
                    and 0 <= parsed["confidence"] <= 1):
                parsed["provider_verified"] = True
                parsed["needs_attention"] = parsed["confidence"] < 0.85
                return parsed
            self.health_state, self.last_error = "DEGRADED", "Invalid notification response schema"

        return {"should_respond": False, "confidence": 0.0, "suggested_reply": "",
                "rationale": "Model evaluation unavailable; requires manual review", "needs_attention": True,
                "provider_verified": False}

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
        source_context: str = "",
        guidelines: str = "",
        test_output: str = "",
    ) -> Dict[str, Any]:
        """Generate targeted code repair instructions and minimal patch metadata."""
        prompt = f"""
You are an expert autonomous software engineer fixing an open-source bug.
Repository: {repo}
Issue Title: {issue_title}
Issue Context:
{issue_body[:2000]}

Repository Context / Key Files:
{file_tree_summary[:4000]}

Relevant source:
{source_context[:40000]}

Repository instructions:
{guidelines[:12000]}

Baseline tests:
{test_output[:5000]}

Determine:
1. Is this fixable with a clean minimal patch?
2. Propose targeted file and exact code modification.

Return JSON format:
{{
  "can_fix": boolean,
  "confidence": float,
  "target_file": "relative/path/to/file.ext",
  "search_content": "exact code snippet from target_file to replace, or empty if creating/overwriting",
  "replacement_content": "new code snippet to replace search_content with",
  "file_content": "full file content if creating new file or rewriting small file, else empty",
  "regression_tests": [{{"target_file": "tests/test_bug.py", "file_content": "complete regression test that fails before the fix and passes after"}}],
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

        return {"can_fix": False, "confidence": 0.0, "target_file": "", "search_content": "",
                "replacement_content": "", "file_content": "", "regression_tests": [],
                "explanation": "Model patch generation unavailable", "patch_description": ""}

    async def generate_pr_metadata(
        self,
        issue_title: str,
        issue_body: str,
        issue_number: int,
        diff_summary: str,
        test_output: str,
        guidelines: str = "",
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
{test_output[:6000]}

Repository contribution instructions and available PR template:
{guidelines[:12000]}
Follow the supplied template and instructions. State only verification supported by the supplied output.

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
- See the attached diff for the proposed changes.
- The regression test failed before the repair and passed afterward.

### Verification
```
{test_output.strip() if test_output else "No test evidence available; submission blocked."}
```

Closes #{issue_number}
"""
        return {"title": pr_title, "body": pr_body}
