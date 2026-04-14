"""
Unit Tests — core.db (central SQLite access layer)

Tests append, query, and formatting helpers.
Uses tmp_path for full DB isolation — no writes to mas/data/episodic.db.
"""
import pytest
from pathlib import Path

from core.db import (
    init_db,
    append_event,
    query_events,
    query_project_history,
    query_agent_context,
    format_events_for_prompt,
)


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "test_events.db"
    init_db(db_path=p)
    return p


# ---------------------------------------------------------------------------
# append_event / query_events
# ---------------------------------------------------------------------------

class TestAppendAndQuery:

    def test_append_returns_action_id(self, db):
        aid = append_event("proj-1", "master_orchestrator", "handoff_created",
                           "start intake", db_path=db)
        assert isinstance(aid, str)
        assert len(aid) > 0

    def test_appended_event_is_queryable(self, db):
        append_event("proj-1", "scribe_agent", "handoff_accepted",
                     "accepted intake handoff", db_path=db)
        rows = query_events(project_id="proj-1", db_path=db)
        assert len(rows) == 1
        assert rows[0]["agent_id"] == "scribe_agent"
        assert rows[0]["action_type"] == "handoff_accepted"

    def test_query_by_agent_filters(self, db):
        append_event("proj-1", "agent_a", "handoff_created", "task A", db_path=db)
        append_event("proj-1", "agent_b", "handoff_created", "task B", db_path=db)
        rows = query_events(project_id="proj-1", agent_id="agent_a", db_path=db)
        assert len(rows) == 1
        assert rows[0]["agent_id"] == "agent_a"

    def test_query_by_project_isolates(self, db):
        append_event("proj-A", "agent_x", "handoff_created", "A", db_path=db)
        append_event("proj-B", "agent_x", "handoff_created", "B", db_path=db)
        rows = query_events(project_id="proj-A", db_path=db)
        assert all(r["project_id"] == "proj-A" for r in rows)
        assert len(rows) == 1

    def test_query_respects_limit(self, db):
        for i in range(10):
            append_event("proj-1", "agent", "ping", f"event {i}", db_path=db)
        rows = query_events(project_id="proj-1", limit=3, db_path=db)
        assert len(rows) == 3

    def test_missing_db_returns_empty(self, tmp_path):
        rows = query_events(project_id="proj-x",
                            db_path=tmp_path / "nonexistent.db")
        assert rows == []


# ---------------------------------------------------------------------------
# query_project_history / query_agent_context
# ---------------------------------------------------------------------------

class TestProjectHistory:

    def test_history_is_chronological(self, db):
        for i in range(3):
            append_event("proj-1", "agent", "ping", f"event {i}", db_path=db)
        history = query_project_history("proj-1", limit=10, db_path=db)
        intents = [r["intent"] for r in history]
        assert intents == ["event 0", "event 1", "event 2"]

    def test_agent_context_filters_by_agent(self, db):
        append_event("proj-1", "agent_a", "ping", "a1", db_path=db)
        append_event("proj-1", "agent_b", "ping", "b1", db_path=db)
        append_event("proj-1", "agent_a", "ping", "a2", db_path=db)
        ctx = query_agent_context("proj-1", "agent_a", limit=10, db_path=db)
        assert len(ctx) == 2
        assert all(r["agent_id"] == "agent_a" for r in ctx)


# ---------------------------------------------------------------------------
# format_events_for_prompt
# ---------------------------------------------------------------------------

class TestFormatForPrompt:

    def test_empty_returns_placeholder(self):
        result = format_events_for_prompt([])
        assert "(no prior events recorded)" in result

    def test_formats_events(self, db):
        append_event("proj-1", "master_orchestrator", "handoff_created",
                     "start intake", db_path=db)
        events = query_project_history("proj-1", db_path=db)
        text = format_events_for_prompt(events)
        assert "master_orchestrator" in text
        assert "handoff_created" in text
        assert "start intake" in text

    def test_caps_at_five_events(self, db):
        for i in range(10):
            append_event("proj-1", "agent", "ping", f"event {i}", db_path=db)
        events = query_project_history("proj-1", db_path=db)
        text = format_events_for_prompt(events)
        lines = [l for l in text.splitlines() if l.strip()]
        assert len(lines) <= 5
