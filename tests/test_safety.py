import sys
import tempfile
import unittest
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import AgentConfig
from src.safety_guardrails import SafetyGuardrails, StateStore



class TestSafetyGuardrails(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = Path(self.temp_dir.name) / "test_state.json"
        self.cfg = AgentConfig(
            state_file=self.state_file,
            max_prs_per_day=2,
            min_rate_limit_remaining=50,
        )
        self.safety = SafetyGuardrails(self.cfg)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_state_persistence(self):
        store = self.safety.state
        self.assertFalse(store.is_notification_handled("12345"))
        store.mark_notification_handled("12345")
        self.assertTrue(store.is_notification_handled("12345"))

        # Re-load from disk
        store2 = StateStore(self.state_file)
        self.assertTrue(store2.is_notification_handled("12345"))

    def test_spam_sanitization(self):
        raw_text = "As an AI language model, here is the fix for the bug:\n\n```python\nprint(1)\n```\n\nI hope this helps!"
        cleaned = self.safety.sanitize_comment(raw_text)
        self.assertNotIn("As an AI", cleaned)
        self.assertNotIn("I hope this helps", cleaned)
        self.assertIn("```python", cleaned)

    def test_content_safety_validation(self):
        safe, _ = self.safety.validate_content_safety("Fixing the parser null pointer by validating input.")
        self.assertTrue(safe)

        unsafe, msg = self.safety.validate_content_safety("As an AI, I am doing this.")
        self.assertFalse(unsafe)

    def test_pr_rate_limiting(self):
        self.safety.state.record_pr_submission("owner/repo", "http://issue/1", "http://pr/1")
        can_pr, _ = self.safety.can_submit_pr()
        self.assertTrue(can_pr)

        self.safety.state.record_pr_submission("owner/repo", "http://issue/2", "http://pr/2")
        can_pr, msg = self.safety.can_submit_pr()
        self.assertFalse(can_pr)
        self.assertIn("Daily PR limit reached", msg)

    def test_api_rate_limit_guard(self):
        safe, _ = self.safety.check_rate_limit(500)
        self.assertTrue(safe)

        safe, msg = self.safety.check_rate_limit(10)
        self.assertFalse(safe)
        self.assertIn("critical", msg)


if __name__ == "__main__":
    unittest.main()
