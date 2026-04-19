"""
Unit Tests — AgentRunner

Tests live-only guardrails, availability flag, and SQLite event logging.
No live API calls are made in this file.
"""
import os
import pytest
from pathlib import Path
from unittest.mock import patch

from core.engine.agent_runner import AgentRunner, DEFAULT_MODEL
from core.db import query_events, init_db


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "test_events.db"
    init_db(db_path=p)
    return p


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------

class TestAvailability:

    def test_unavailable_without_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            runner = AgentRunner()
        assert runner.available is False

    def test_default_model(self):
        runner = AgentRunner()
        assert runner.model == DEFAULT_MODEL


# ---------------------------------------------------------------------------
# Live-only guardrails
# ---------------------------------------------------------------------------

class TestLiveOnly:

    def test_no_api_key_requires_live_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            runner = AgentRunner()
        result = runner.run("inquirer_agent", "prompt")
        assert "Live execution is mandatory" in result["error"]
        assert result["retryable"] is False

    def test_result_has_required_keys(self):
        runner = AgentRunner()
        result = runner.run("agent", "prompt")
        for key in ("text", "tokens_used", "model", "error", "retryable"):
            assert key in result


# ---------------------------------------------------------------------------
# SQLite logging
# ---------------------------------------------------------------------------

class TestSQLiteLogging:

    def test_blocked_call_does_not_log_agent_event(self, db):
        runner = AgentRunner(db_path=db)
        runner.run("inquirer_agent", "prompt", project_id="proj-test")
        rows = query_events(project_id="proj-test", action_type="agent_call", db_path=db)
        assert rows == []
