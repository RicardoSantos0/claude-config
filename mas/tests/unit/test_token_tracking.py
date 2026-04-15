"""
Tests for token tracking — proj-20260415-001-db-semantic-and-acl-fix

AC7  agent_runner logs a token usage row on dry-run call
AC7b query_token_usage sums rows correctly
"""

import pytest
import tempfile
import json
from pathlib import Path


def _make_temp_db() -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return Path(tmp.name)


class TestAgentRunnerLogsTokenUsage:
    """AC7: agent_runner writes an agent_call row on every call."""

    def test_dry_run_logs_zero_token_row(self):
        """AC7: dry-run call writes a row with tokens_total=0 to SQLite."""
        from core.engine.agent_runner import AgentRunner
        from core.db import query_events

        db_path = _make_temp_db()
        runner = AgentRunner(db_path=db_path)

        result = runner.run(
            agent_id="master_orchestrator",
            prompt="Test prompt for token tracking",
            project_id="proj-token-test",
            dry_run=True,
        )

        assert result["dry_run"] is True
        events = query_events(project_id="proj-token-test",
                              action_type="agent_call", db_path=db_path)
        assert len(events) == 1, "Expected exactly one agent_call row"

        payload = json.loads(events[0]["payload"])
        inputs = payload["params"]["inputs"]
        assert inputs["tokens_prompt"]     == 0
        assert inputs["tokens_completion"] == 0
        assert inputs["tokens_total"]      == 0

    def test_dry_run_without_project_id_does_not_write(self):
        """AC7 edge case: no project_id → no SQLite write (nothing to scope to)."""
        from core.engine.agent_runner import AgentRunner
        from core.utils.log_helpers import init_db

        db_path = _make_temp_db()
        init_db(db_path)  # create schema so the count query works
        runner = AgentRunner(db_path=db_path)
        runner.run(agent_id="hr_agent", prompt="test", project_id="", dry_run=True)

        import sqlite3
        conn = sqlite3.connect(str(db_path))
        count = conn.execute(
            "SELECT count(*) FROM agent_events WHERE action_type='agent_call'"
        ).fetchone()[0]
        conn.close()
        assert count == 0


class TestQueryTokenUsage:
    """AC7: query_token_usage correctly sums token fields."""

    def test_sums_single_row(self):
        """AC7: single agent_call row returns correct totals."""
        from core.utils.log_helpers import init_db, append_event
        from core.db import query_token_usage

        db_path = _make_temp_db()
        init_db(db_path)
        append_event(
            project_id="proj-tok-sum",
            agent_id="master_orchestrator",
            action_type="agent_call",
            intent="prompt text",
            result_shape="tokens=150",
            payload={"tokens_prompt": 100, "tokens_completion": 50, "tokens_total": 150},
            db_path=db_path,
        )

        result = query_token_usage("proj-tok-sum", db_path=db_path)
        assert result["total_prompt"]     == 100
        assert result["total_completion"] == 50
        assert result["total"]            == 150
        assert result["calls"]            == 1

    def test_sums_multiple_rows(self):
        """AC7: multiple agent_call rows are summed correctly."""
        from core.utils.log_helpers import init_db, append_event
        from core.db import query_token_usage

        db_path = _make_temp_db()
        init_db(db_path)

        for i in range(3):
            append_event(
                project_id="proj-tok-multi",
                agent_id="master_orchestrator",
                action_type="agent_call",
                intent=f"call {i}",
                result_shape=f"tokens={50 * (i + 1)}",
                payload={
                    "tokens_prompt":     30 * (i + 1),
                    "tokens_completion": 20 * (i + 1),
                    "tokens_total":      50 * (i + 1),
                },
                db_path=db_path,
            )

        result = query_token_usage("proj-tok-multi", db_path=db_path)
        # rows: (30,20,50), (60,40,100), (90,60,150)
        assert result["total_prompt"]     == 180
        assert result["total_completion"] == 120
        assert result["total"]            == 300
        assert result["calls"]            == 3

    def test_empty_project_returns_zeros(self):
        """AC7: project with no agent_call rows returns all zeros."""
        from core.utils.log_helpers import init_db
        from core.db import query_token_usage

        db_path = _make_temp_db()
        init_db(db_path)

        result = query_token_usage("proj-no-calls", db_path=db_path)
        assert result["total_prompt"] == 0
        assert result["total_completion"] == 0
        assert result["total"] == 0
        assert result["calls"] == 0
        assert result["dry_calls"] == 0
        assert result["live_calls"] == 0

    def test_only_counts_agent_call_rows(self):
        """AC7: handoff rows are ignored; only action_type='agent_call' is summed."""
        from core.utils.log_helpers import init_db, append_event
        from core.db import query_token_usage

        db_path = _make_temp_db()
        init_db(db_path)

        # Insert a handoff row (should be ignored)
        append_event(
            project_id="proj-mixed",
            agent_id="master_orchestrator",
            action_type="handoff_created",
            intent="handoff event",
            payload={"tokens_prompt": 999, "tokens_total": 999},
            db_path=db_path,
        )
        # Insert one real agent_call row
        append_event(
            project_id="proj-mixed",
            agent_id="master_orchestrator",
            action_type="agent_call",
            intent="agent call event",
            payload={"tokens_prompt": 10, "tokens_completion": 5, "tokens_total": 15},
            db_path=db_path,
        )

        result = query_token_usage("proj-mixed", db_path=db_path)
        assert result["total"]  == 15   # only agent_call row counted
        assert result["calls"]  == 1
