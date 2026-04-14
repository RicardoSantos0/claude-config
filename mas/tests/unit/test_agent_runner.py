"""
Unit Tests — AgentRunner

Tests dry-run mode, availability flag, and SQLite event logging.
No live API calls — all tests use dry_run=True or patch ANTHROPIC_API_KEY absent.
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
# Dry-run mode
# ---------------------------------------------------------------------------

class TestDryRun:

    def test_dry_run_returns_text(self):
        runner = AgentRunner()
        result = runner.run("inquirer_agent", "some prompt", dry_run=True)
        assert "dry_run" in result["text"]
        assert result["dry_run"] is True
        assert result["tokens_used"] == 0

    def test_no_api_key_implies_dry_run(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            runner = AgentRunner()
        result = runner.run("inquirer_agent", "prompt")
        assert result["dry_run"] is True

    def test_dry_run_includes_agent_id(self):
        runner = AgentRunner()
        result = runner.run("risk_advisor", "prompt", dry_run=True)
        assert "risk_advisor" in result["text"]

    def test_result_has_required_keys(self):
        runner = AgentRunner()
        result = runner.run("agent", "prompt", dry_run=True)
        for key in ("text", "tokens_used", "model", "dry_run"):
            assert key in result


# ---------------------------------------------------------------------------
# SQLite logging (dry_run does NOT log — only live calls log)
# ---------------------------------------------------------------------------

class TestSQLiteLogging:

    def test_dry_run_does_not_log_to_db(self, db):
        runner = AgentRunner(db_path=db)
        runner.run("inquirer_agent", "prompt", project_id="proj-test", dry_run=True)
        rows = query_events(project_id="proj-test", db_path=db)
        assert len(rows) == 0
