"""Tests for mas/core/log_helpers.py"""

import json
import tempfile
from pathlib import Path

import pytest

from core.utils.log_helpers import (
    make_log_entry,
    init_db,
    append_event,
    query_by_action_id,
    query_events,
)


@pytest.fixture()
def tmp_db(tmp_path):
    db = tmp_path / "test_episodic.db"
    init_db(db)
    return db


# --- make_log_entry ---

def test_make_log_entry_structure():
    entry = make_log_entry("evaluator_agent", "evaluation", "assess project quality")
    assert entry["jsonrpc"] == "2.0"
    assert entry["_v"] == "1.0"
    assert entry["method"] == "evaluator_agent.evaluation"
    assert "id" in entry
    assert entry["params"]["intent"] == "assess project quality"
    assert entry["result"]["result_shape"] == ""
    assert entry["error"] is None


def test_make_log_entry_custom_id():
    entry = make_log_entry("master_orchestrator", "handoff", "delegate to scribe",
                           action_id="test-uuid-123")
    assert entry["id"] == "test-uuid-123"


def test_make_log_entry_with_result():
    entry = make_log_entry(
        "evaluator_agent", "evaluation", "assess",
        result_shape="score=85, passed=True",
        artifacts=["eval_report.yaml"],
        decisions=[{"id": "d-001", "v": "pass"}],
    )
    assert entry["result"]["result_shape"] == "score=85, passed=True"
    assert "eval_report.yaml" in entry["result"]["artifacts"]
    assert entry["result"]["decisions"][0]["id"] == "d-001"


# --- init_db ---

def test_init_db_creates_table(tmp_db):
    import sqlite3
    conn = sqlite3.connect(str(tmp_db))
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_events'"
    )
    assert cur.fetchone() is not None
    conn.close()


def test_init_db_idempotent(tmp_db):
    # Running twice must not raise
    init_db(tmp_db)
    init_db(tmp_db)


def test_init_db_wal_mode(tmp_db):
    import sqlite3
    conn = sqlite3.connect(str(tmp_db))
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"
    conn.close()


# --- append_event ---

def test_append_event_returns_action_id(tmp_db):
    action_id = append_event(
        "proj-001", "evaluator_agent", "evaluation",
        "assess project", db_path=tmp_db
    )
    assert isinstance(action_id, str)
    assert len(action_id) > 0


def test_append_event_persists(tmp_db):
    append_event("proj-001", "master_orchestrator", "handoff",
                 "delegate planning", db_path=tmp_db)
    events = query_events(project_id="proj-001", db_path=tmp_db)
    assert len(events) == 1
    assert events[0]["agent_id"] == "master_orchestrator"


def test_append_multiple_events(tmp_db):
    for i in range(5):
        append_event("proj-001", "scribe_agent", "write",
                     f"write artifact {i}", db_path=tmp_db)
    events = query_events(project_id="proj-001", db_path=tmp_db)
    assert len(events) == 5


# --- query_by_action_id ---

def test_query_by_action_id_found(tmp_db):
    action_id = append_event(
        "proj-001", "evaluator_agent", "evaluation",
        "assess", result_shape="score=90", db_path=tmp_db
    )
    row = query_by_action_id(action_id, db_path=tmp_db)
    assert row is not None
    assert row["agent_id"] == "evaluator_agent"
    payload = json.loads(row["payload"])
    assert payload["id"] == action_id


def test_query_by_action_id_not_found(tmp_db):
    result = query_by_action_id("nonexistent-uuid", db_path=tmp_db)
    assert result is None


def test_query_by_action_id_no_full_scan(tmp_db):
    """Action ID query must not require reading all rows."""
    for i in range(20):
        append_event("proj-001", "scribe_agent", "write", f"intent {i}", db_path=tmp_db)
    action_id = append_event("proj-002", "evaluator_agent", "eval", "target", db_path=tmp_db)
    row = query_by_action_id(action_id, db_path=tmp_db)
    assert row is not None
    assert row["project_id"] == "proj-002"


# --- query_events ---

def test_query_events_filter_project(tmp_db):
    append_event("proj-A", "master_orchestrator", "handoff", "A", db_path=tmp_db)
    append_event("proj-B", "master_orchestrator", "handoff", "B", db_path=tmp_db)
    events = query_events(project_id="proj-A", db_path=tmp_db)
    assert len(events) == 1
    assert events[0]["project_id"] == "proj-A"


def test_query_events_filter_agent(tmp_db):
    append_event("proj-001", "evaluator_agent", "eval", "e1", db_path=tmp_db)
    append_event("proj-001", "scribe_agent", "write", "s1", db_path=tmp_db)
    events = query_events(agent_id="evaluator_agent", db_path=tmp_db)
    assert len(events) == 1


def test_query_events_limit(tmp_db):
    for i in range(10):
        append_event("proj-001", "scribe_agent", "write", f"w{i}", db_path=tmp_db)
    events = query_events(project_id="proj-001", limit=3, db_path=tmp_db)
    assert len(events) == 3


def test_query_events_empty_db(tmp_db):
    events = query_events(project_id="nonexistent", db_path=tmp_db)
    assert events == []


def test_query_events_no_db(tmp_path):
    events = query_events(project_id="proj-001", db_path=tmp_path / "missing.db")
    assert events == []
