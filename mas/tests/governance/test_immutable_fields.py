"""
Governance Tests — Immutable Field Protection
Fields marked immutable or immutable_after_approval must be protected.
"""
import pytest
from core.engine.shared_state_manager import SharedStateManager


@pytest.fixture
def sm(tmp_path):
    manager = SharedStateManager("proj-imm-001", projects_root=tmp_path)
    manager.initialize(request_id="req-imm-001")
    return manager


def test_immutable_field_created_at_cannot_be_overwritten(sm):
    """core_identity.created_at is always immutable — write must fail."""
    result = sm.write("system", "core_identity", "created_at", "2000-01-01T00:00:00Z")
    assert not result.success
    assert result.reason == "field_is_immutable"


def test_immutable_after_approval_writable_before_approval(sm):
    """project_definition.original_brief should be writable before approval."""
    result = sm.write("inquirer_agent", "project_definition",
                      "original_brief", "First brief")
    assert result.success


def test_immutable_after_approval_blocked_after_approval(sm):
    """project_definition.original_brief should be immutable after Master approves it."""
    # Write initial value
    sm.write("inquirer_agent", "project_definition", "original_brief", "First brief")
    # Approve
    sm.approve("master_orchestrator", "project_definition", "original_brief")
    # Attempt to change — must fail
    result = sm.write("inquirer_agent", "project_definition",
                      "original_brief", "Changed brief")
    assert not result.success
    assert result.reason == "field_is_immutable"


def test_approved_field_still_readable(sm):
    """Approving a field does not prevent reading it."""
    sm.write("inquirer_agent", "project_definition", "original_brief", "My brief")
    sm.approve("master_orchestrator", "project_definition", "original_brief")
    val = sm.read("project_definition.original_brief")
    assert val == "My brief"


def test_multiple_fields_can_be_independently_approved(sm):
    """Approving one field should not affect others."""
    sm.write("inquirer_agent", "project_definition", "original_brief", "Brief A")
    sm.write("inquirer_agent", "project_definition",
             "clarified_specification", {"goal": "Test"})

    sm.approve("master_orchestrator", "project_definition", "original_brief")

    # original_brief is now immutable
    result = sm.write("inquirer_agent", "project_definition", "original_brief", "Changed")
    assert not result.success

    # clarified_specification is still writable
    result2 = sm.write("inquirer_agent", "project_definition",
                        "clarified_specification", {"goal": "Updated"})
    assert result2.success


def test_only_master_can_approve_fields(sm):
    """Only master_orchestrator is allowed to approve fields."""
    sm.write("inquirer_agent", "project_definition", "original_brief", "Brief")
    result = sm.approve("inquirer_agent", "project_definition", "original_brief")
    assert not result.success
    assert result.reason == "only_master_can_approve"


def test_project_id_immutable_after_approval(sm):
    """core_identity.project_id must be immutable after approval."""
    sm.approve("master_orchestrator", "core_identity", "project_id")
    result = sm.write("master_orchestrator", "core_identity",
                      "project_id", "proj-hijacked")
    assert not result.success
    assert result.reason == "field_is_immutable"


def test_approval_persists_across_reload(sm):
    """Approved fields must remain approved after reloading state from disk."""
    sm.write("inquirer_agent", "project_definition", "original_brief", "Brief")
    sm.approve("master_orchestrator", "project_definition", "original_brief")

    # Reload
    sm2 = SharedStateManager("proj-imm-001", projects_root=sm.projects_root)
    result = sm2.write("inquirer_agent", "project_definition",
                       "original_brief", "Attempt after reload")
    assert not result.success
    assert result.reason == "field_is_immutable"
