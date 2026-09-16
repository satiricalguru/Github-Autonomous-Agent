"""Tests for web dashboard endpoints, dynamic model detection, and responsive telemetry."""

from src.config import config, detect_active_ai_model
from src.status_tracker import status_tracker
from src.web_dashboard import ALLOWED_MODELS


class TestWebDashboard:
    """Test suite for Web Dashboard and Model Configuration."""

    def test_detect_active_ai_model(self):
        """Verify model detection returns active gemini-3.8-flash."""
        model = detect_active_ai_model()
        assert "3.8" in model or "3.7" in model or "gemini" in model.lower()

    def test_status_tracker_snapshot_includes_model_metadata(self, cfg):
        """Verify status snapshot exports active model and display name."""
        from src.status_tracker import StatusTracker
        snapshot = StatusTracker(cfg).get_snapshot()
        assert "active_model" in snapshot
        assert "model_display_name" in snapshot
        assert "rate_limit_remaining" in snapshot
        assert snapshot["rate_limit_remaining"] is None

    def test_config_update_helper(self):
        """Verify config update method correctly modifies runtime fields."""
        old_interval = config.inbox_poll_interval
        config.update(inbox_poll_interval=45)
        assert config.inbox_poll_interval == 45
        # Restore
        config.update(inbox_poll_interval=old_interval)

    def test_settings_model_allowlist(self):
        """Settings endpoint must only accept known model identifiers."""
        assert "gemini-3.8-flash" in ALLOWED_MODELS
        assert "claude-sonnet-4.6" in ALLOWED_MODELS
        assert "gpt-oss-120b" in ALLOWED_MODELS
        assert "evil-model;rm -rf" not in ALLOWED_MODELS

    def test_rate_limit_tracking(self):
        """Status tracker records live quota instead of hardcoded 5000."""
        old_rem, old_lim = status_tracker.rate_limit_remaining, status_tracker.rate_limit_limit
        status_tracker.set_rate_limit(1234, 5000)
        try:
            snapshot = status_tracker.get_snapshot()
            assert snapshot["rate_limit_remaining"] == 1234
            assert snapshot["rate_limit_limit"] == 5000
        finally:
            status_tracker.set_rate_limit(old_rem, old_lim)
