"""
Integration Tests — SQLite event logging via handoff_engine

Verifies that every handoff create/accept/reject call writes the
expected row to the agent_events table.
Uses tmp_path to avoid polluting mas/data/episodic.db.
"""
import json
import pytest
from pathlib import Path
from functools import partial

import core.db as _core_db
from core.utils.log_helpers import append_event as _real_append
from core.engine.shared_state_manager import SharedStateManager
from core.engine.handoff_engine import HandoffEngine
from core.db import init_db, query_events


PROJECT_ID = "proj-sqlite-test-001"

HANDOFF_PAYLOAD = {
    "summary": "Complete intake phase",
    "artifacts_produced": [],
    "decisions_made": [],
    "open_questions": [],
    "constraints_for_next": [],
    "shared_state_fields_modified": [],
}


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "events.db"
    init_db(db_path=p)
    return p


@pytest.fixture
def redirect_db(db, monkeypatch):
    """
    Redirect all append_event calls in core.db to the test database.
    Since handoff_engine does lazy 'from core.db import append_event',
    patching core.db.append_event is picked up on each call.
    """
    monkeypatch.setattr(_core_db, "append_event",
                        partial(_real_append, db_path=db))
    return db


@pytest.fixture
def sm(tmp_path):
    s = SharedStateManager(PROJECT_ID, projects_root=tmp_path)
    s.initialize(request_id="req-001")
    return s


@pytest.fixture
def engine():
    return HandoffEngine()


# ---------------------------------------------------------------------------
# Handoff create → SQLite
# ---------------------------------------------------------------------------

class TestHandoffCreateLogsToSQLite:

    def test_create_writes_handoff_created_event(self, sm, engine, redirect_db):
        """handoff_engine.create() must write a handoff_created event to SQLite."""
        handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="inquirer_agent",
            phase="intake",
            task_description="Run intake for project",
            payload=HANDOFF_PAYLOAD,
        )
        rows = query_events(
            project_id=PROJECT_ID,
            action_type="handoff_created",
            db_path=redirect_db,
        )
        assert len(rows) == 1
        assert rows[0]["agent_id"] == "master_orchestrator"
        assert rows[0]["intent"] == "Run intake for project"

    def test_create_payload_contains_handoff_id(self, sm, engine, redirect_db):
        """The SQLite payload must contain the handoff_id."""
        handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="scribe_agent",
            phase="intake",
            task_description="Initialize project",
            payload=HANDOFF_PAYLOAD,
        )
        rows = query_events(project_id=PROJECT_ID, db_path=redirect_db)
        assert len(rows) == 1
        payload = json.loads(rows[0]["payload"])
        inner = payload.get("params", {}).get("inputs", {})
        assert inner.get("handoff_id") == handoff["handoff_id"]


# ---------------------------------------------------------------------------
# Handoff accept → SQLite
# ---------------------------------------------------------------------------

class TestHandoffAcceptLogsToSQLite:

    def test_accept_writes_handoff_accepted_event(self, sm, engine, redirect_db):
        """handoff_engine.accept() must write a handoff_accepted event to SQLite."""
        handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="scribe_agent",
            phase="intake",
            task_description="Init scribe",
            payload=HANDOFF_PAYLOAD,
        )
        engine.accept(sm, handoff["handoff_id"])
        rows = query_events(
            project_id=PROJECT_ID,
            action_type="handoff_accepted",
            db_path=redirect_db,
        )
        assert len(rows) == 1
        assert handoff["handoff_id"] in rows[0]["intent"]


# ---------------------------------------------------------------------------
# Handoff reject → SQLite
# ---------------------------------------------------------------------------

class TestHandoffRejectLogsToSQLite:

    def test_reject_writes_handoff_rejected_event(self, sm, engine, redirect_db):
        """handoff_engine.reject() must write a handoff_rejected event to SQLite."""
        handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="scribe_agent",
            phase="intake",
            task_description="Init scribe",
            payload=HANDOFF_PAYLOAD,
        )
        engine.reject(sm, handoff["handoff_id"], reason="missing artifact")
        rows = query_events(
            project_id=PROJECT_ID,
            action_type="handoff_rejected",
            db_path=redirect_db,
        )
        assert len(rows) == 1
        assert "missing artifact" in rows[0]["intent"]


# ---------------------------------------------------------------------------
# Multiple events accumulate
# ---------------------------------------------------------------------------

class TestEventAccumulation:

    def test_multiple_handoffs_all_logged(self, sm, engine, redirect_db):
        """Each handoff create should add one row to agent_events."""
        for i in range(3):
            engine.create(
                sm,
                from_agent="master_orchestrator",
                to_agent="scribe_agent",
                phase="intake",
                task_description=f"Task {i}",
                payload=HANDOFF_PAYLOAD,
            )
        rows = query_events(
            project_id=PROJECT_ID,
            action_type="handoff_created",
            db_path=redirect_db,
        )
        assert len(rows) == 3
