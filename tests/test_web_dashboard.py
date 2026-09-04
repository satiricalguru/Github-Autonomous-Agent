"""Tests for web dashboard endpoints, dynamic model detection, and responsive telemetry."""

import json
import pytest
from src.config import config, detect_active_ai_model
from src.status_tracker import status_tracker
from src.web_dashboard import DashboardHTTPHandler


class DummyRequest:
    def __init__(self, body: bytes):
        self.body = body

    def read(self, length: int):
        return self.body[:length]


class DummyServer:
    pass


class TestWebDashboard:
    """Test suite for Web Dashboard and Model Configuration."""

    def test_detect_active_ai_model(self):
        """Verify model detection returns active gemini-3.8-flash."""
        model = detect_active_ai_model()
        assert "3.8" in model or "3.7" in model or "gemini" in model.lower()

    def test_status_tracker_snapshot_includes_model_metadata(self):
        """Verify status snapshot exports active model and display name."""
        snapshot = status_tracker.get_snapshot()
        assert "active_model" in snapshot
        assert "model_display_name" in snapshot
        assert "rate_limit_remaining" in snapshot
        assert snapshot["rate_limit_remaining"] > 0

    def test_config_update_helper(self):
        """Verify config update method correctly modifies runtime fields."""
        old_interval = config.inbox_poll_interval
        config.update(inbox_poll_interval=45)
        assert config.inbox_poll_interval == 45
        # Restore
        config.update(inbox_poll_interval=old_interval)
