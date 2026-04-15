"""
Tests for dry/live agent call accounting (D3).
AC4: agent_runner logs dry_run=True in payload for dry-run calls.
AC5: agent_runner logs dry_run=False in payload for live calls.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mas.core.utils.log_helpers import init_db, query_events, _get_connection


@pytest.fixture()
def tmp_db(tmp_path):
    db = tmp_path / "test.db"
    init_db(db)
    return db


class TestAgentRunnerDryLiveFlag:
    """AC4/AC5: agent_runner._log_event() includes dry_run flag in payload."""

    def test_dry_run_logs_dry_true(self, tmp_db):
        from mas.core.engine.agent_runner import AgentRunner
        runner = AgentRunner(db_path=tmp_db)
        runner._log_event("proj-test", "test_agent", "test prompt",
                          tokens_prompt=0, tokens_completion=0, dry_run=True)

        conn = _get_connection(tmp_db)
        row = conn.execute(
            "SELECT payload FROM agent_events WHERE action_type='agent_call'"
        ).fetchone()
        conn.close()
        assert row is not None
        data = json.loads(row["payload"])
        payload = data.get("params", {}).get("inputs", {})
        assert payload.get("dry_run") is True

    def test_live_run_logs_dry_false(self, tmp_db):
        from mas.core.engine.agent_runner import AgentRunner
        runner = AgentRunner(db_path=tmp_db)
        runner._log_event("proj-test", "test_agent", "test prompt",
                          tokens_prompt=100, tokens_completion=50, dry_run=False)

        conn = _get_connection(tmp_db)
        row = conn.execute(
            "SELECT payload FROM agent_events WHERE action_type='agent_call'"
        ).fetchone()
        conn.close()
        assert row is not None
        data = json.loads(row["payload"])
        payload = data.get("params", {}).get("inputs", {})
        assert payload.get("dry_run") is False

    def test_run_without_key_logs_dry_true(self, tmp_db):
        """When no API key is set, run() is a dry run and should log dry_run=True."""
        from mas.core.engine.agent_runner import AgentRunner
        with patch.dict("os.environ", {}, clear=True):
            # Remove API key if present
            import os
            os.environ.pop("ANTHROPIC_API_KEY", None)
            runner = AgentRunner(db_path=tmp_db)
            runner.run(agent_id="test_agent", prompt="hello", project_id="proj-dry-check")

        conn = _get_connection(tmp_db)
        row = conn.execute(
            "SELECT payload FROM agent_events WHERE action_type='agent_call' AND project_id='proj-dry-check'"
        ).fetchone()
        conn.close()
        assert row is not None
        data = json.loads(row["payload"])
        payload = data.get("params", {}).get("inputs", {})
        assert payload.get("dry_run") is True

    def test_query_token_usage_dry_live_split(self, tmp_db):
        """query_token_usage correctly splits dry/live calls."""
        from mas.core.db import query_token_usage
        from mas.core.engine.agent_runner import AgentRunner
        runner = AgentRunner(db_path=tmp_db)

        runner._log_event("proj-split", "a1", "p1", tokens_prompt=100, tokens_completion=50, dry_run=False)
        runner._log_event("proj-split", "a2", "p2", tokens_prompt=0, tokens_completion=0, dry_run=True)
        runner._log_event("proj-split", "a3", "p3", tokens_prompt=200, tokens_completion=100, dry_run=False)

        result = query_token_usage("proj-split", db_path=tmp_db)
        assert result["calls"] == 3
        assert result["live_calls"] == 2
        assert result["dry_calls"] == 1
        assert result["total"] == 450

    def test_dry_run_row_has_zero_tokens(self, tmp_db):
        """Dry-run calls always have zero tokens."""
        from mas.core.engine.agent_runner import AgentRunner
        runner = AgentRunner(db_path=tmp_db)
        runner._log_event("proj-zero", "a", "p", tokens_prompt=0, tokens_completion=0, dry_run=True)

        conn = _get_connection(tmp_db)
        row = conn.execute(
            "SELECT payload FROM agent_events WHERE action_type='agent_call'"
        ).fetchone()
        conn.close()
        data = json.loads(row["payload"])
        payload = data.get("params", {}).get("inputs", {})
        assert payload.get("tokens_total") == 0
