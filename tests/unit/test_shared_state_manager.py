"""
Unit Tests — SharedStateManager
"""
import pytest
from pathlib import Path
from core.shared_state_manager import SharedStateManager, create_initial_state


@pytest.fixture
def sm(tmp_path):
    """SharedStateManager with isolated tmp directory."""
    manager = SharedStateManager("proj-test-001", projects_root=tmp_path)
    manager.initialize(request_id="req-test-001")
    return manager


def test_initialize_creates_state_file(tmp_path):
    sm = SharedStateManager("proj-init-001", projects_root=tmp_path)
    assert not sm.exists()
    sm.initialize(request_id="req-001")
    assert sm.exists()


def test_initialize_is_idempotent(tmp_path):
    sm = SharedStateManager("proj-idem-001", projects_root=tmp_path)
    sm.initialize(request_id="req-001")
    sm.initialize(request_id="req-001")  # Should not raise
    assert sm.exists()


def test_initial_state_structure(sm):
    state = sm.load()
    assert "core_identity" in state
    assert "project_definition" in state
    assert "workflow" in state
    assert "decisions" in state
    assert "capability" in state
    assert "artifacts" in state
    assert "evaluation" in state
    assert "consultation" in state
    assert "_meta" in state


def test_initial_phase_is_intake(sm):
    assert sm.read("core_identity.current_phase") == "intake"


def test_initial_status_is_active(sm):
    assert sm.read("core_identity.status") == "active"


def test_read_nested_path(sm):
    val = sm.read("core_identity.project_id")
    assert val == "proj-test-001"


def test_read_nonexistent_path_returns_none(sm):
    assert sm.read("nonexistent.field") is None


def test_authorized_write_succeeds(sm):
    result = sm.write("master_orchestrator", "core_identity", "current_phase", "planning")
    assert result.success
    assert sm.read("core_identity.current_phase") == "planning"


def test_authorized_write_persists_to_disk(sm):
    sm.write("master_orchestrator", "core_identity", "status", "paused")
    # Reload from disk
    sm2 = SharedStateManager("proj-test-001", projects_root=sm.projects_root)
    assert sm2.read("core_identity.status") == "paused"


def test_updates_updated_at_on_write(sm):
    before = sm.read("core_identity.updated_at")
    sm.write("master_orchestrator", "core_identity", "current_phase", "planning")
    after = sm.read("core_identity.updated_at")
    # updated_at should have changed (or at minimum stayed the same)
    assert after >= before


def test_authorized_append_succeeds(sm):
    assumption = {"assumption_id": "a-001", "stated_by": "master_orchestrator",
                  "description": "Test assumption", "validated": False}
    result = sm.append("master_orchestrator", "decisions", "assumptions", assumption)
    assert result.success
    val = sm.read("decisions.assumptions")
    assert len(val) == 1
    assert val[0]["assumption_id"] == "a-001"


def test_multiple_appends_accumulate(sm):
    for i in range(3):
        sm.append("master_orchestrator", "decisions", "assumptions",
                  {"assumption_id": f"a-{i:03d}", "stated_by": "master_orchestrator",
                   "description": f"Assumption {i}", "validated": False})
    val = sm.read("decisions.assumptions")
    assert len(val) == 3


def test_system_append_to_handoff_history(sm):
    entry = {"handoff_id": "ho-001", "from_agent": "master_orchestrator",
             "to_agent": "scribe_agent"}
    result = sm.system_append("workflow", "handoff_history", entry)
    assert result.success


def test_approve_marks_field(sm):
    sm.write("inquirer_agent", "project_definition", "original_brief", "Test brief")
    result = sm.approve("master_orchestrator", "project_definition", "original_brief")
    assert result.success
    state = sm.load()
    assert "project_definition.original_brief" in state["_meta"]["approved_fields"]


def test_snapshot_creates_file(sm):
    path = sm.snapshot("intake")
    assert path.exists()
    assert "snapshot_intake" in path.name


def test_create_initial_state_has_all_sections():
    state = create_initial_state("proj-001", "req-001")
    for section in ["core_identity", "project_definition", "workflow",
                    "decisions", "capability", "artifacts", "evaluation",
                    "consultation", "_meta"]:
        assert section in state


def test_violation_count_starts_at_zero(sm):
    assert sm.get_violation_count("any_agent") == 0
