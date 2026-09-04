import sys
import unittest
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ai_engine import AIEngine
from src.config import AgentConfig



class TestAIEngine(unittest.IsolatedAsyncioTestCase):
    async def test_notification_evaluation_fallback(self):
        engine = AIEngine(AgentConfig(gemini_api_key=None))
        eval_res = await engine.evaluate_notification(
            repo="facebook/react",
            title="Question about state update",
            reason="mention",
            subject_type="Issue",
            last_comments=[],
        )
        self.assertIn("should_respond", eval_res)
        self.assertTrue(eval_res["should_respond"])

    async def test_issue_actionability_fallback(self):
        engine = AIEngine(AgentConfig(gemini_api_key=None))
        res = await engine.analyze_issue_actionability(
            repo="tiangolo/fastapi",
            title="TypeError in response serialization with null fields",
            body="When returning None in schema:\n```python\nTraceback (most recent call last):\nTypeError\n```",
            labels=["bug", "help wanted"],
        )
        self.assertTrue(res["is_actionable"])
        self.assertGreaterEqual(res["actionability_score"], 0.6)

    async def test_pr_metadata_generation(self):
        engine = AIEngine(AgentConfig(gemini_api_key=None))
        meta = await engine.generate_pr_metadata(
            issue_title="TypeError in response serialization",
            issue_body="Repro steps...",
            issue_number=42,
            diff_summary="Added null check",
            test_output="1 passed",
        )
        self.assertIn("title", meta)
        self.assertIn("body", meta)
        self.assertIn("#42", meta["body"])


if __name__ == "__main__":
    unittest.main()
