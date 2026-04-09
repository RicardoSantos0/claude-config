"""
Unit Tests — HandoffEngine
"""
import pytest
from core.shared_state_manager import SharedStateManager
from core.handoff_engine import HandoffEngine, REQUIRED_PAYLOAD_KEYS


@pytest.fixture
def sm(tmp_path):
    manager = SharedStateManager("proj-test-002", projects_root=tmp_path)
    manager.initialize(request_id="req-test-002")
    return manager


@pytest.fixture
def engine():
    return HandoffEngine()


@pytest.fixture
def sample_payload():
    return {
        "summary": "Test summary",
        "artifacts_produced": [],
        "decisions_made": [],
        "open_questions": [],
        "constraints_for_next": ["Must complete within 1 round"],
        "shared_state_fields_modified": ["core_identity.status"],
    }


def test_create_handoff_returns_dict(sm, engine, sample_payload):
    h = engine.create(sm, from_agent="master_orchestrator",
                      to_agent="scribe_agent", phase="intake",
                      task_description="Initialize project folder",
                      payload=sample_payload)
    assert isinstance(h, dict)


def test_create_handoff_has_correct_id_format(sm, engine, sample_payload):
    h = engine.create(sm, from_agent="master_orchestrator",
                      to_agent="scribe_agent", phase="intake",
                      task_description="Initialize", payload=sample_payload)
    assert h["handoff_id"].startswith("ho-proj-test-002-")


def test_create_handoff_sequential_ids(sm, engine, sample_payload):
    h1 = engine.create(sm, from_agent="master_orchestrator",
                       to_agent="scribe_agent", phase="intake",
                       task_description="Task 1", payload=sample_payload)
    h2 = engine.create(sm, from_agent="master_orchestrator",
                       to_agent="scribe_agent", phase="intake",
                       task_description="Task 2", payload=sample_payload)
    assert h1["handoff_id"] != h2["handoff_id"]
    assert "001" in h1["handoff_id"]
    assert "002" in h2["handoff_id"]


def test_create_handoff_initial_status_is_pending(sm, engine, sample_payload):
    h = engine.create(sm, from_agent="master_orchestrator",
                      to_agent="scribe_agent", phase="intake",
                      task_description="Initialize", payload=sample_payload)
    assert h["acceptance"]["status"] == "pending"


def test_create_handoff_recorded_in_state(sm, engine, sample_payload):
    h = engine.create(sm, from_agent="master_orchestrator",
                      to_agent="scribe_agent", phase="intake",
                      task_description="Initialize", payload=sample_payload)
    history = sm.read("workflow.handoff_history")
    assert len(history) == 1
    assert history[0]["handoff_id"] == h["handoff_id"]


def test_validate_valid_handoff(engine, sample_payload):
    handoff = {
        "handoff_id": "ho-001",
        "project_id": "proj-001",
        "from_agent": "master_orchestrator",
        "to_agent": "scribe_agent",
        "authorized_by": "master_orchestrator",
        "phase": "intake",
        "task_description": "Test task",
        "payload": sample_payload,
    }
    valid, errors = engine.validate(handoff)
    assert valid, errors


def test_validate_missing_field_returns_error(engine):
    handoff = {"handoff_id": "ho-001"}  # Missing most fields
    valid, errors = engine.validate(handoff)
    assert not valid
    assert len(errors) > 0


def test_accept_handoff_changes_status(sm, engine, sample_payload):
    h = engine.create(sm, from_agent="master_orchestrator",
                      to_agent="scribe_agent", phase="intake",
                      task_description="Initialize", payload=sample_payload)
    ok = engine.accept(sm, h["handoff_id"])
    assert ok
    updated = engine.get(sm, h["handoff_id"])
    assert updated["acceptance"]["status"] == "accepted"
    assert updated["acceptance"]["accepted_at"] is not None


def test_accept_with_questions_sets_correct_status(sm, engine, sample_payload):
    h = engine.create(sm, from_agent="master_orchestrator",
                      to_agent="scribe_agent", phase="intake",
                      task_description="Initialize", payload=sample_payload)
    engine.accept(sm, h["handoff_id"], follow_up_questions=["What is the deadline?"])
    updated = engine.get(sm, h["handoff_id"])
    assert updated["acceptance"]["status"] == "accepted_with_questions"


def test_reject_handoff_changes_status(sm, engine, sample_payload):
    h = engine.create(sm, from_agent="master_orchestrator",
                      to_agent="scribe_agent", phase="intake",
                      task_description="Initialize", payload=sample_payload)
    ok = engine.reject(sm, h["handoff_id"], reason="Incomplete payload")
    assert ok
    updated = engine.get(sm, h["handoff_id"])
    assert updated["acceptance"]["status"] == "rejected"
    assert updated["acceptance"]["rejection_reason"] == "Incomplete payload"


def test_get_pending_returns_only_pending(sm, engine, sample_payload):
    h1 = engine.create(sm, from_agent="master_orchestrator",
                       to_agent="scribe_agent", phase="intake",
                       task_description="Task 1", payload=sample_payload)
    h2 = engine.create(sm, from_agent="master_orchestrator",
                       to_agent="scribe_agent", phase="intake",
                       task_description="Task 2", payload=sample_payload)
    engine.accept(sm, h1["handoff_id"])
    pending = engine.get_pending(sm)
    assert len(pending) == 1
    assert pending[0]["handoff_id"] == h2["handoff_id"]


def test_get_pending_filtered_by_agent(sm, engine, sample_payload):
    engine.create(sm, from_agent="master_orchestrator",
                  to_agent="scribe_agent", phase="intake",
                  task_description="For scribe", payload=sample_payload)
    engine.create(sm, from_agent="master_orchestrator",
                  to_agent="inquirer_agent", phase="intake",
                  task_description="For inquirer", payload=sample_payload)
    scribe_pending = engine.get_pending(sm, to_agent="scribe_agent")
    assert len(scribe_pending) == 1
    assert scribe_pending[0]["to_agent"] == "scribe_agent"


def test_get_nonexistent_handoff_returns_none(sm, engine):
    result = engine.get(sm, "ho-does-not-exist")
    assert result is None


def test_get_all_returns_full_history(sm, engine, sample_payload):
    for i in range(3):
        engine.create(sm, from_agent="master_orchestrator",
                      to_agent="scribe_agent", phase="intake",
                      task_description=f"Task {i}", payload=sample_payload)
    all_h = engine.get_all(sm)
    assert len(all_h) == 3
